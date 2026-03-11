# coreference.py
#WITHOUT DEBUG PRINTS
import re
import os
import openai
from openai import OpenAI
from pymongo import MongoClient
from datetime import datetime
import openai
import os

from app.config import LLM_MODEL
from app.core.embeddings import get_query_embedding

# Google GenAI Client
try:
    from google import genai
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    google_client = genai.Client(api_key=GOOGLE_API_KEY, http_options={"api_version": "v1"}) if GOOGLE_API_KEY else None
except ImportError:
    google_client = None
# ...existing code...
import os
from dotenv import load_dotenv
import logging

# Initialize logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger("pymongo").setLevel(logging.WARNING)


# Load .env variables
load_dotenv()
USE_OPENAI = os.getenv("USE_OPENAI", "true").lower() == "true"

# Together API client
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
together_client = OpenAI(
    api_key=TOGETHER_API_KEY,
    base_url="https://api.together.xyz/v1"
) if TOGETHER_API_KEY else None

# OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# OpenRouter client
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
openrouter_client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1"
) if OPENROUTER_API_KEY else None

# Then wherever you use `client`, replace with calls to openai, e.g.




# Setup MongoDB client for fetching and updating history (fail-safe)
mongo_client = None
rag_memory_collection = None
try:
    mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
    if mongo_uri:
        mongo_client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=3000,
            socketTimeoutMS=30000,
            connectTimeoutMS=5000,
        )
        rag_memory_collection = mongo_client["dev_db"].get("dd_memory_entries_rag") if hasattr(mongo_client["dev_db"], 'get') else mongo_client["dev_db"]["dd_memory_entries_rag"]
except Exception:
    mongo_client = None
    rag_memory_collection = None

def fetch_recent_history(session_id: str, limit: int = 5):
    if rag_memory_collection is None:
        return []
    try:
        docs = list(rag_memory_collection.find({"session_id": session_id}).sort("timestamp", -1).limit(limit))
    except Exception:
        return []
    history = []

    for doc in docs:
        # Check for new flat structure
        if "query_text" in doc and "llm_response" in doc:
            history.append({"query": doc.get("query_text", ""), "response": doc.get("llm_response", "")})
        # Check for old 'chats' array
        elif "chats" in doc:
            for chat in doc["chats"][-limit:]:
                history.append({"query": chat.get("query_text", ""), "response": chat.get("llm_response", "")})

    history = history[-limit:]  # Keep most recent N
    return history


def is_generic_coref_message(resolved: str) -> bool:
    resolved_lower = resolved.lower()
    patterns = [
        r"no pronouns",
        r"no coreferences",
        r"does not contain (any )?(pronouns|coreferences|ambiguous references)",
        r"doesn't contain (any )?(pronouns|coreferences|ambiguous references)",
        r"there (are|is) no (pronouns|coreferences|ambiguous references)",
        r"nothing to resolve",
        r"no reference to resolve",
        r"no need for clarification",
        r"does not require clarification",
        r"doesn't require clarification",
        r"does not require resolution",
        r"doesn't require resolution",
        r"no reference",
        r"no ambiguous reference",
        r"no pronoun",
        r"no coreference"
    ]
    for pattern in patterns:
        if re.search(pattern, resolved_lower):
            return True
    if "the sentence" in resolved_lower and "doesn't contain any pronouns" in resolved_lower:
        return True
    return False

def resolve_coreference(query: str, session_id: str = None, history: list = None) -> str:
    resolved = query  # fallback to original query
    error_type = None
    if session_id and history is None:
        history = fetch_recent_history(session_id)
         
        

    if isinstance(history, list) and all(isinstance(item, dict) and "query" in item and "response" in item for item in history):
        formatted_history = "\n".join([
            f"User: {item.get('query','')}\nBot: {item.get('response','')}" for item in history[-5:]
        ])

        history_context = f"\nConversation History:\n{formatted_history}\n"
        
    else:
        history_context = ""
        

    prompt = f"""
You are a coreference resolver. Given the input sentence and optional conversation history, resolve all pronouns and ambiguous references with their explicit nouns for clarity.

{history_context}
Input: "{query}"
Output:
"""
    
    # Paid GPT models
    paid_models = ["gpt-4o", "gpt-4"]

    # Free/open models
    free_models = [   
    {"provider": "google", "model": "gemini-1.5-pro"},
    {"provider": "groq", "model": "llama-3.3-70b-versatile"},
    {"provider": "groq", "model": "mixtral-8x7b-32768"},
    {"provider": "groq", "model": "llama-3.1-8b-instant"},      # Fast + decent reasoning
    {"provider": "groq", "model": "llama3-8b-8192"},            # Slightly older, smaller context
    {"provider": "google", "model": "gemini-1.5-flash"},
    {"provider": "groq", "model": "llama-3.3-70b-versatile"},     # Best reasoning & accuracy
    {"provider": "groq", "model": "llama-3.1-70b-versatile"},     # Previous stable 70B
    {"provider": "groq", "model": "llama-3.1-8b-instant"},        # Fast + decent reasoning
    {"provider": "groq", "model": "llama3-8b-8192"},              # Older, smaller context
    {"provider": "groq", "model": "mixtral-8x7b-32768"},          # Sparse MoE, large context
    {"provider": "groq", "model": "gemma2-9b-it"},
    {"provider": "google", "model": "gemini-1.5-flash"},          # Fast, great for RAG
    {"provider": "google", "model": "gemini-1.5-pro"},            # Better reasoning, slower
    {"provider": "google", "model": "gemini-1.0-pro"},            # Older stable
    {"provider": "google", "model": "gemini-1.0-pro-vision"},
    {"provider": "openrouter", "model": "openai/gpt-oss-20b"},
    {"provider": "openrouter", "model": "z.ai/glm-4.5-air"},
    {"provider": "openrouter", "model": "qwen/qwen3-coder"},
    {"provider": "openrouter", "model": "moonshotai/kimi-k2"},
    {"provider": "openrouter", "model": "deepseek/deepseek-r1:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-v3-0324:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-r1-0528:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-v3-0528:free"},
    {"provider": "openrouter", "model": "meta-llama/llama-4-maverick:free"},
    {"provider": "openrouter", "model": "qwen/qwen3-235b-a22b:free"},
    {"provider": "openrouter", "model": "qwen/qwen3-30b-a3b:free"},
    {"provider": "openrouter", "model": "google/gemma-3-27b-it:free"},
    {"provider": "openrouter", "model": "google/gemma-3-12b-it:free"},
    {"provider": "openrouter", "model": "openrouter/cypher-alpha:free"},
    {"provider": "openrouter", "model": "openrouter/optimus-alpha:free"},
    {"provider": "openrouter", "model": "openrouter/quasar-alpha:free"},
    {"provider": "openrouter", "model": "nvidia/llama-3.1-nemotron-nano-8b-v1:free"},
    {"provider": "openrouter", "model": "moonshotai/kimi-vl-a3b-thinking:free"},
    {"provider": "openrouter", "model": "nousresearch/deephermes-3-llama-3-8b-preview:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-r1-zero:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-r1:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-v3-0324:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-r1-0528:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-v3-0528:free"},
    {"provider": "openrouter", "model": "qwen/qwen3-coder:free"},
    {"provider": "openrouter", "model": "qwen/qwen3-235b-a22b:free"},
    {"provider": "openrouter", "model": "qwen/qwen3-30b-a3b:free"},
    {"provider": "openrouter", "model": "z.ai/glm-4.5-air:free"},
    {"provider": "openrouter", "model": "openai/gpt-oss-20b:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-chat-v3-0324:free"},
    {"provider": "openrouter", "model": "meta-llama/llama-4-maverick:free"},
    {"provider": "openrouter", "model": "google/gemma-3-27b-it:free"},
    {"provider": "openrouter", "model": "openrouter/cypher-alpha:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-r1:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-v3-0324:free"},
    {"provider": "openrouter", "model": "qwen/qwen3-coder:free"},
    {"provider": "openrouter", "model": "z.ai/glm-4.5-air:free"},
    {"provider": "openrouter", "model": "openai/gpt-oss-20b:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-chat-v3-0324:free"},
    {"provider": "openrouter", "model": "meta-llama/llama-4-maverick:free"},
    {"provider": "openrouter", "model": "qwen/qwen3-235b-a22b:free"},
    {"provider": "openrouter", "model": "deepseek/deepseek-r1:free"},
    {"provider": "groq", "model": "llama-3.3-70b-versatile"},   # Best reasoning & accuracy
    {"provider": "groq", "model": "mixtral-8x7b-32768"},        # Strong reasoning, large context
    {"provider": "groq", "model": "llama-3.1-8b-instant"},      # Fast + decent reasoning
    {"provider": "groq", "model": "llama3-8b-8192"},            # Slightly older, smaller context
    {"provider": "google", "model": "gemini-1.5-flash"},
    {"provider": "groq", "model": "llama-3.3-70b-versatile"},     # Best reasoning & accuracy
    {"provider": "groq", "model": "llama-3.1-70b-versatile"},     # Previous stable 70B
    {"provider": "groq", "model": "llama-3.1-8b-instant"},        # Fast + decent reasoning
    {"provider": "groq", "model": "llama3-8b-8192"},              # Older, smaller context
    {"provider": "groq", "model": "mixtral-8x7b-32768"},          # Sparse MoE, large context
    {"provider": "groq", "model": "gemma2-9b-it"},
    {"provider": "google", "model": "gemini-1.5-flash"},          # Fast, great for RAG
    {"provider": "google", "model": "gemini-1.5-pro"},            # Better reasoning, slower
    {"provider": "google", "model": "gemini-1.0-pro"},            # Older stable
    {"provider": "google", "model": "gemini-1.0-pro-vision"},
    {"provider": "openrouter", "model": "nousresearch/hermes-2-pro-llama-3-8b"},  
    {"provider": "openrouter", "model": "meta-llama/llama-3-8b-instruct"},        
    {"provider": "openrouter", "model": "meta-llama/llama-3-70b-instruct"},       
    {"provider": "openrouter", "model": "mistralai/mixtral-8x7b-instruct"},       
    {"provider": "openrouter", "model": "mistralai/mistral-7b-instruct"},         
    {"provider": "openrouter", "model": "tiiuae/falcon-40b-instruct"},            
    {"provider": "openrouter", "model": "tiiuae/falcon-7b-instruct"},
    {"provider": "together", "model": "mistralai/Mixtral-8x7B-Instruct-v0.1"},
    {"provider": "together", "model": "meta-llama/Llama-3-70b-chat-hf"},
    {"provider": "together", "model": "meta-llama/Llama-3-8b-chat-hf"},
    {"provider": "together", "model": "togethercomputer/StripedHyena-Nous-7B"},
    {"provider": "groq", "model": "llama-3.1-8b-instant"},
    {"provider": "groq", "model": "llama-3.1-70b-versatile"},
    {"provider": "groq", "model": "mixtral-8x7b"},
    {"provider": "google", "model": "gemini-1.5-flash"},
    ]



    resolved = resolved or query

# Try paid OpenAI models *only if USE_OPENAI=true*
    response_text = None
    if USE_OPENAI and openai_client:
        for model_name in paid_models:
            try:
                response = openai_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "You resolve coreferences in text."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0,
                )
                response_text = response.choices[0].message.content.strip()
                
                break
            except Exception as e:
                print(f"Paid model {model_name} failed: {e}")
                continue

# If paid didn’t return a confident result OR OpenAI disabled → try free fallback models
    if (not response_text) or (not USE_OPENAI):
        for fm in free_models:
            print(f"[USING FREE MODEL] provider={fm['provider']} model={fm['model']}")
            try:
                if fm["provider"] == "groq":
                    from groq import Groq
                    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
                    resp = groq_client.chat.completions.create(
                        model=fm["model"],
                        messages=[
                            {"role": "system", "content": "You resolve coreferences in text."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0,
                    )
                    response_text = resp.choices[0].message.content.strip()

                elif fm["provider"] == "google":
                    if not google_client:
                        print(f"Skipping Google model {fm['model']} (client not initialized)")
                        continue
                    resp = google_client.models.generate_content(
                        model=fm["model"],
                        contents=prompt
                    )
                    response_text = resp.text.strip()

                
                break

            except Exception as e:
                print(f"Free model {fm['model']} failed: {e}")
                continue

# Use query itself if resolved is generic, empty or useless
    if not response_text or (response_text == query) or is_generic_coref_message(response_text):
        resolved = query
    else:
        resolved = response_text

            

  

    
    rag_memory_collection.update_one(
        {"session_id": session_id, "query_text": query, "timestamp": {"$exists": True}},
        {"$set": {"resolved_query": resolved, "coref_resolved_at": datetime.utcnow()}},
        upsert=False
    )



    
    
    if resolved is None:
        resolved = resolved or query

    


    return resolved
