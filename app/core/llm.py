# app/core/llm.py
import os
from dotenv import load_dotenv
from app.config import LLM_MODEL
from app.core.embeddings import get_query_embedding
from app.db.vector_store import search_similar_documents
from openai import OpenAI
import logging
from typing import Optional
from app.utils.logger import logger  # central logger (configured once)

load_dotenv()
USE_OPENAI = os.getenv("USE_OPENAI", "true").lower() == "true"
DISABLE_FREE_MODELS = os.getenv("DISABLE_FREE_MODELS", "false").lower() == "true"
SKIP_GOOGLE_FREE = os.getenv("SKIP_GOOGLE_FREE", "false").lower() == "true"
SKIP_GROQ_FREE = os.getenv("SKIP_GROQ_FREE", "false").lower() == "true"

# Clients
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
together_client = OpenAI(api_key=TOGETHER_API_KEY, base_url="https://api.together.xyz/v1") if TOGETHER_API_KEY else None
openrouter_client = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1") if OPENROUTER_API_KEY else None

# Control prompt logging verbosity via env
LOG_FULL_PROMPT = os.getenv("LOG_FULL_PROMPT", "false").lower() == "true"
LOG_PROMPT_DEBUG = os.getenv("LOG_PROMPT_DEBUG", "false").lower() == "true"  # new gate
PROMPT_LOG_LIMIT = int(os.getenv("PROMPT_LOG_LIMIT", "4000"))

def _log_prompt_debug(prompt: str, origin: Optional[str] = None) -> None:
    """Log the final prompt/context sent to the LLM with safe truncation.

    Set LOG_FULL_PROMPT=true to log full prompt; otherwise logs first PROMPT_LOG_LIMIT chars.
    """
    if not LOG_PROMPT_DEBUG:
        return  # fast skip when disabled
    try:
        label = f"[{origin}]" if origin else ""
        total_len = len(prompt) if isinstance(prompt, str) else 0
        if not isinstance(prompt, str):
            logger.debug(f"[LLM PROMPT]{label} non-string prompt type={type(prompt)}")
            return
        if LOG_FULL_PROMPT:
            logger.debug(f"[LLM PROMPT]{label} len={total_len} chars\n{prompt}")
        else:
            snippet = prompt[:PROMPT_LOG_LIMIT]
            suffix = "\n...[truncated]" if total_len > PROMPT_LOG_LIMIT else ""
            logger.debug(f"[LLM PROMPT]{label} len={total_len} chars (showing up to {PROMPT_LOG_LIMIT})\n{snippet}{suffix}")
    except Exception as e:
        logger.debug(f"[LLM PROMPT] logging failed: {e}")

class OpenAIEngine:
    def __init__(self, model=LLM_MODEL):
        self.model = model
        self.client = openai_client
        
    def build_prompt(self, query, context_chunks):
        context = "\n\n---\n\n".join(chunk["chunk"] for chunk in context_chunks)
        agent_identity = "You are an AI assistant named Doxi. Always introduce yourself as Doxi when asked your name."
        return f"""You are a helpful assistant. {agent_identity}
        Use the following context to answer the question.
        If the answer is not in the context you can use your own knowledge. Whenever you are asked for a quote, give it in clear highlighted order.
        Context:
        {context}
        Question: {query}
        Answer:"""

    def generate(self, query: str):
        docs = search_similar_documents(get_query_embedding(query))

        if not docs:
            print("[WARNING] No relevant documents found from vector search.")
            return "❌ No relevant documents found. Try again after update."
        prompt = self.build_prompt(query, docs)
        _log_prompt_debug(prompt, origin="generate")

        paid_models = [self.model, "gpt-4o-mini"]
        # Prefer Groq first to avoid Gemini 429 delays
        free_models = [
            {"provider": "groq", "model": "llama-3.3-70b-versatile"},
            {"provider": "groq", "model": "mixtral-8x7b-32768"},
            {"provider": "google", "model": "gemini-1.5-flash"},
        ]
        if SKIP_GROQ_FREE:
            free_models = [m for m in free_models if m["provider"] != "groq"]
        if SKIP_GOOGLE_FREE or not os.getenv("GOOGLE_API_KEY"):
            free_models = [m for m in free_models if m["provider"] != "google"]
        response_text = None
        error_type = None
        if USE_OPENAI:
            for model_name in paid_models:
                try:
                    if self.client:
                        response = self.client.chat.completions.create(
                            model=model_name,
                            messages=[
                                {"role": "system", "content": "You are a knowledgeable assistant."},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.2
                        )
                        response_text = response.choices[0].message.content.strip()
                        break
                    else:
                        print(f"Skipping paid model {model_name} (OpenAI client not initialized)")
                except Exception as e:
                    print(f"Paid model {model_name} failed: {e}")
                    error_type = str(e).lower()
                    continue
        if ((not USE_OPENAI) or (not response_text)) and (not DISABLE_FREE_MODELS):
            for fm in free_models:
                try:
                    if fm["provider"] == "groq":
                        from groq import Groq
                        groq_key = os.getenv("GROQ_API_KEY")
                        if groq_key:
                            groq_client = Groq(api_key=groq_key)
                            resp = groq_client.chat.completions.create(
                                model=fm["model"],
                                messages=[
                                    {"role": "system", "content": "You are a knowledgeable assistant."},
                                    {"role": "user", "content": prompt}
                                ],
                                temperature=0.2
                            )
                            response_text = resp.choices[0].message.content.strip()
                        else:
                            print(f"Skipping Groq model {fm['model']} (API key missing)")
                    elif fm["provider"] == "google":
                        import google.generativeai as genai
                        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
                        model = genai.GenerativeModel(fm["model"])
                        resp = model.generate_content(prompt)
                        response_text = resp.text.strip()
                    if response_text:
                        warning_msg = (
                            "⚠️ GPT balance finished, recharge for accurate answers now. "
                            "Doxi is using free models; accuracy will be less."
                        )
                        response_text = f"{warning_msg}\n\n{response_text}"
                        break
                except Exception as e:
                    print(f"Free model {fm['model']} failed: {e}")
                    continue
        return response_text or "⚠️ GPT balance finished, recharge for accurate answers now."
    
    def chat(self, prompt: str) -> str:
        _log_prompt_debug(prompt, origin="chat")
        paid_models = [self.model, "gpt-4o-mini"]
        free_models = [
            {"provider": "groq", "model": "llama-3.3-70b-versatile"},
            {"provider": "groq", "model": "mixtral-8x7b-32768"},
            {"provider": "google", "model": "gemini-1.5-flash"},
        ]
        if SKIP_GROQ_FREE:
            free_models = [m for m in free_models if m["provider"] != "groq"]
        if SKIP_GOOGLE_FREE or not os.getenv("GOOGLE_API_KEY"):
            free_models = [m for m in free_models if m["provider"] != "google"]
        response_text = None
        error_type = None
        if USE_OPENAI:
            for model_name in paid_models:
                try:
                    if self.client:
                        response = self.client.chat.completions.create(
                            model=model_name,
                            messages=[
                                {"role": "system", "content": "You are a knowledgeable assistant."},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.2
                        )
                        response_text = response.choices[0].message.content.strip()
                        break
                    else:
                        print(f"Skipping paid model {model_name} (OpenAI client not initialized)")
                except Exception as e:
                    print(f"Paid model {model_name} failed: {e}")
                    error_type = str(e).lower()
                    continue
        if ((not USE_OPENAI) or (not response_text)) and (not DISABLE_FREE_MODELS):
            for fm in free_models:
                try:
                    if fm["provider"] == "groq":
                        from groq import Groq
                        groq_key = os.getenv("GROQ_API_KEY")
                        if groq_key:
                            groq_client = Groq(api_key=groq_key)
                            resp = groq_client.chat.completions.create(
                                model=fm["model"],
                                messages=[
                                    {"role": "system", "content": "You are a knowledgeable assistant."},
                                    {"role": "user", "content": prompt}
                                ],
                                temperature=0.2
                            )
                            response_text = resp.choices[0].message.content.strip()
                        else:
                            print(f"Skipping Groq model {fm['model']} (API key missing)")
                    elif fm["provider"] == "google":
                        import google.generativeai as genai
                        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
                        model = genai.GenerativeModel(fm["model"])
                        resp = model.generate_content(prompt)
                        response_text = resp.text.strip()
                    if response_text:
                        warning_msg = (
                            "⚠️ GPT balance finished, recharge for accurate answers now. "
                            "Doxi is using free models; accuracy will be less."
                        )
                        response_text = f"{warning_msg}\n\n{response_text}"
                        break
                except Exception as e:
                    print(f"Free model {fm['model']} failed: {e}")
                    continue
        return response_text or "⚠️ GPT balance finished, recharge for accurate answers now."

# Create the llm_engine instance that will be imported by other modules
llm_engine = OpenAIEngine()

# Placeholder for pdf_sessions_collection
# You should replace this with your actual implementation
pdf_sessions_collection = None  # Replace with your actual collection initialization
