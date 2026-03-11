# app/core/embeddings.py
from typing import List
import os
import requests
import time
from threading import Lock
from functools import wraps
from openai import OpenAI, OpenAIError
try:
    from google import genai
except ImportError:
    genai = None
try:
    from tiktoken import encoding_for_model
    import tiktoken
except ImportError:
    encoding_for_model = None
    tiktoken = None
from app.config import EMBEDDING_MODEL
USE_OPENAI = os.getenv("USE_OPENAI", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
# ===== API KEYS =====
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")  # HuggingFace access token

# ===== CLIENT SETUP =====
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
google_client = None
if genai and GOOGLE_API_KEY:
    google_client = genai.Client(api_key=GOOGLE_API_KEY, http_options={"api_version": "v1"})

# ===== TOKENIZER =====
_encoding_cache = None

def count_tokens(text: str) -> int:
    global _encoding_cache
    if not tiktoken:
        # Fallback if tiktoken is missing
        return len(text.split()) 
    if not _encoding_cache:
        try:
            _encoding_cache = encoding_for_model(EMBEDDING_MODEL)
        except Exception:
            try:
                _encoding_cache = tiktoken.get_encoding("cl100k_base")
            except Exception:
                return len(text.split())
    return len(_encoding_cache.encode(text))

# ===== FALLBACK PROVIDERS =====
SEARCH_FALLBACKS = (
    [("openai", EMBEDDING_MODEL)] if USE_OPENAI else []
) + [
    ("gemini", "text-embedding-004"),
]
# ===== STATE =====
openai_lock = Lock()
OPENAI_DISABLED = False

def _validate_provider(provider: str):
    """Validate provider configuration before use."""
    if provider == "openai" and not openai_client:
        raise ValueError("OpenAI client not initialized")
    if provider == "gemini" and not google_client:
        raise ValueError("Google GenAI client not initialized")

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
        if not google_client:
             raise ValueError("Google GenAI client not initialized")
        result = google_client.models.embed_content(model=model, contents=text)
        print(f"[DEBUG] Gemini embedding response: {result}")
        # The result object from new SDK has an 'embeddings' attribute which is a list
        return result.embeddings[0].values

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
        print("[WARNING] No embedding provider API keys (OpenAI/Google/HF) configured. Embedding features will fail.")
    if not client and "openai" in [p[0] for p in SEARCH_FALLBACKS]:
        print("[WARNING] OpenAI client required but not initialized (missing API key).")
        

# Initialize configuration
validate_config()
