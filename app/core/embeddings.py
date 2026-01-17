# app/core/embeddings.py
from typing import List
import os
import requests
import time
from threading import Lock
from functools import wraps
from openai import OpenAI, OpenAIError
from tiktoken import encoding_for_model
import google.generativeai as genai
import tiktoken  # For fallback encoding
from app.config import EMBEDDING_MODEL
from openai import OpenAI
USE_OPENAI = os.getenv("USE_OPENAI", "false").lower() == "true"
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# ===== API KEYS =====
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")  # HuggingFace access token

# ===== CLIENT SETUP =====
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# ===== TOKENIZER =====
_encoding_cache = None

def count_tokens(text: str) -> int:
    global _encoding_cache
    if not _encoding_cache:
        try:
            _encoding_cache = encoding_for_model(EMBEDDING_MODEL)
        except Exception:
            _encoding_cache = tiktoken.get_encoding("cl100k_base")
    return len(_encoding_cache.encode(text))

# ===== FALLBACK PROVIDERS =====
SEARCH_FALLBACKS = (
    [("openai", EMBEDDING_MODEL)] if USE_OPENAI else []
) + [
    ("gemini", "models/embedding-001"),
    ("huggingface", "intfloat/e5-large-v2"),
    ("huggingface", "sentence-transformers/all-MiniLM-L6-v2"),
]
# ===== STATE =====
openai_lock = Lock()
OPENAI_DISABLED = False

def _validate_provider(provider: str):
    """Validate provider configuration before use."""
    if provider == "openai" and not openai_client:
        raise ValueError("OpenAI client not initialized")
    if provider == "gemini" and not GOOGLE_API_KEY:
        raise ValueError("Gemini API key not configured")

def time_operation(func):
    """Decorator to log operation execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            duration = time.time() - start
            print(f"{func.__name__} took {duration:.2f}s")
    return wrapper

@time_operation
def _get_embedding_from_provider(provider: str, model: str, text: str) -> List[float]:
    """Core function to get embeddings from specified provider."""
    global OPENAI_DISABLED
    
    _validate_provider(provider)

    if provider == "openai":
        with openai_lock:
            if OPENAI_DISABLED:
                
                raise RuntimeError("OpenAI disabled due to insufficient quota")
            try:
                resp = openai_client.embeddings.create(model=model, input=text)
                
                return resp.data[0].embedding
            except OpenAIError as e:
                
                if "insufficient_quota" in str(e):
                    OPENAI_DISABLED = True
                    
                    raise RuntimeError("OpenAI quota exceeded - disabling for session")
                raise

    elif provider == "gemini":
        print(f"[DEBUG] Requesting Gemini embedding for: {text}")
        result = genai.embed_content(model=model, content=text)
        print(f"[DEBUG] Gemini embedding response: {result}")
        return result["embedding"]

    elif provider == "huggingface":
        url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{model}"
        headers = {"Authorization": f"Bearer {HF_API_KEY}"} if HF_API_KEY else {}
        print(f"[DEBUG] Requesting HuggingFace embedding for: {text}")
        response = requests.post(url, headers=headers, json={"inputs": text}, timeout=10)
        print(f"[DEBUG] HuggingFace response status: {response.status_code}")
        response.raise_for_status()
        print(f"[DEBUG] HuggingFace embedding response: {response.json()}")
        return response.json()

    print(f"[DEBUG] Unknown provider: {provider}")
    raise ValueError(f"Unknown provider: {provider}")

@time_operation
def get_query_embedding(query: str) -> List[float]:
    """Get embedding for query with automatic fallback."""
    
    last_error = None
    for provider, model in SEARCH_FALLBACKS:
        
        try:
            emb = _get_embedding_from_provider(provider, model, query)
            
            return emb
        except Exception as e:
            last_error = e
            print(f"[DEBUG] [Embedding Fallback] {provider} ({model}) failed: {e}")
    
    raise RuntimeError(f"All embedding providers failed. Last error: {str(last_error)}")

def get_embedding_for_text(text: str) -> List[float]:
    
    if not USE_OPENAI:
        
        return None
    try:
        emb = _get_embedding_from_provider("openai", EMBEDDING_MODEL, text)
        
        return emb
    except Exception as e:
        print(f"[DEBUG] [Embedding Storage] Skipped: {e}")
        return None


def validate_config():
    """Validate required configuration at startup."""
    
    if not any([OPENAI_API_KEY, GOOGLE_API_KEY, HF_API_KEY]):
        
        raise RuntimeError("At least one embedding provider API key must be configured")
    if not openai_client and "openai" in [p[0] for p in SEARCH_FALLBACKS]:
        raise RuntimeError("OpenAI client required but not initialized")
        

# Initialize configuration
validate_config()
