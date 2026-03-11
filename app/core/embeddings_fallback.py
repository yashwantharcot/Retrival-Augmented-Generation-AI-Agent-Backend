
# embeddings_fallback.py
from app.config import EMBEDDING_MODEL
from app.tasks.background_jobs import update_embeddings
from typing import List, Dict, Optional
import os
import re
import time
import threading
from datetime import datetime
from threading import Lock
from tenacity import retry, stop_after_attempt, wait_exponential
from openai import OpenAI, OpenAIError
from tiktoken import encoding_for_model, get_encoding
from google import genai
from pymongo import MongoClient, collection
from openai import OpenAI
from app.utils.logger import logger
try:
    from google.api_core import exceptions as g_exceptions
except Exception:  # pragma: no cover - optional import
    g_exceptions = None
USE_OPENAI = os.getenv("USE_OPENAI", "true").lower() == "true"

# OpenAI client is initialized properly below near line 83
# ===== CONFIGURATION =====
# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MONGO_URI = os.getenv("MONGODB_URI")

# Database configuration
DB_NAME = "dev_db"
SOURCE_COLLECTIONS = ["dd_accounts", "dd_opportunities", "dd_quotes"]
TARGET_COLLECTION = "dd_accounts_chunks"
GEMINI_EMBEDDING_COLLECTION = "dd_accounts_chunks_gemini"
VECTOR_INDEX_NAME = "vector_index_v2"
GEMINI_VECTOR_INDEX = "vector_index_gemini_v2"
EMBEDDING_MODEL = "text-embedding-3-small"
E5_MODEL_NAME = os.getenv("E5_MODEL_NAME", "intfloat/e5-base")
E5_LOCAL_PATH = os.getenv("LOCAL_E5_BASE_PATH", r"C:\\Users\\Admin\\models\\intfloat-e5-base")
E5_SHOW_PROGRESS = os.getenv("E5_SHOW_PROGRESS", "false").lower() == "true"  # default suppress
USE_GEMINI_EMBEDDINGS = os.getenv("USE_GEMINI_EMBEDDINGS", "true").lower() == "true"
EMBED_MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "8000"))
STRIP_HTML_EMBED = os.getenv("STRIP_HTML_EMBED", "true").lower() == "true"
# Env toggle (default true to avoid heavy local model unless explicitly enabled)
DISABLE_E5_SENTENCE_TRANSFORMERS = os.getenv("DISABLE_E5_SENTENCE_TRANSFORMERS", "true").lower() == "true"

# Runtime capability check: Torch >= 2.1 exposes float8 types used by recent transformers.
# On older Torch (e.g., 1.12) or when Torch/TF/Flax are missing, importing sentence-transformers
# can raise AttributeError: module 'torch' has no attribute 'float8_e4m3fn'.
def _torch_supports_e5() -> bool:
    try:
        import torch  # type: ignore
        # Fast path: attribute present
        if hasattr(torch, "float8_e4m3fn"):
            return True
        # Fallback: parse version
        ver = getattr(torch, "__version__", "")
        parts = ver.split(".")
        if len(parts) >= 2:
            try:
                major = int(parts[0])
                minor = int(parts[1])
                return (major > 2) or (major == 2 and minor >= 1)
            except Exception:
                return False
        return False
    except Exception:
        return False

# Effective disable flag and reason (exported for diagnostics)
E5_RUNTIME_BLOCKED = not _torch_supports_e5()
E5_EFFECTIVE_DISABLED = DISABLE_E5_SENTENCE_TRANSFORMERS or E5_RUNTIME_BLOCKED
E5_DISABLED_REASON = (
    "disabled by env flag"
    if DISABLE_E5_SENTENCE_TRANSFORMERS
    else ("unsupported torch runtime (requires torch>=2.1 or float8 support)" if E5_RUNTIME_BLOCKED else "")
)

# ===== INITIALIZATION =====
# API Clients
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
google_client = None
if genai and GOOGLE_API_KEY:
    google_client = genai.Client(api_key=GOOGLE_API_KEY)

# MongoDB Client with connection pooling (optional)
mongo_client = None
db = None
source_collections = []
target_collection = None
gemini_collection = None
try:
    if MONGO_URI:
        mongo_client = MongoClient(
            MONGO_URI,
            maxPoolSize=100,
            socketTimeoutMS=30000,
            connectTimeoutMS=10000,
            serverSelectionTimeoutMS=3000,
            retryWrites=True,
            retryReads=True
        )
        db = mongo_client[DB_NAME]
        source_collections = [db[name] for name in SOURCE_COLLECTIONS]
        target_collection = db[TARGET_COLLECTION]
        gemini_collection = db[GEMINI_EMBEDDING_COLLECTION]
except Exception:
    mongo_client = None
    db = None
    source_collections = []
    target_collection = None
    gemini_collection = None

# Tokenizer
try:
    encoding = encoding_for_model(EMBEDDING_MODEL)
except Exception:
    encoding = get_encoding("cl100k_base")

# State management
openai_lock = Lock()
OPENAI_DISABLED = False
GEMINI_DISABLED = False  # set True after quota errors to skip rest of session
e5_model = None
e5_lock = Lock()

# ===== CORE FUNCTIONS =====
def count_tokens(text: str) -> int:
    """Count tokens in text using cached encoding."""
    return len(encoding.encode(text))

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def _sanitize_text(text: str) -> str:
    """Lightweight sanitization to prevent huge HTML/base64 blobs in embedding calls.

    - Optionally strips HTML tags
    - Removes <img ... base64 data URIs>
    - Collapses whitespace
    - Truncates to EMBED_MAX_CHARS
    """
    if STRIP_HTML_EMBED:
        # Remove base64 image tags first to shrink
        text = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '[image]', text)
        # Strip tags
        text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > EMBED_MAX_CHARS:
        text = text[:EMBED_MAX_CHARS] + ' …'
    return text


def _get_embedding_from_provider(provider: str, model: str, text: str) -> List[float]:
    """Get embedding from specified provider with retry logic."""
    global OPENAI_DISABLED
    global e5_model
    
    if provider == "openai":
        if not USE_OPENAI:
            
            raise RuntimeError("USE_OPENAI is false — skipping OpenAI embedding")

        if not openai_client:
            
            raise ValueError("OpenAI client not initialized")
        with openai_lock:
            if OPENAI_DISABLED:
                
                raise RuntimeError("OpenAI disabled due to insufficient quota")
            try:
                resp = openai_client.embeddings.create(
                    model=model,
                    input=text,
                    timeout=10
                )
                
                return resp.data[0].embedding
            except OpenAIError as e:
                
                if "insufficient_quota" in str(e):
                    OPENAI_DISABLED = True
                    
                    raise RuntimeError("OpenAI quota exceeded — disabling for session")
                raise

    elif provider == "intfloat":
        if E5_EFFECTIVE_DISABLED:
            raise RuntimeError("E5 embeddings disabled (" + (E5_DISABLED_REASON or "unknown") + ")")
        # Sentence-Transformers E5 model (intfloat/e5-*)
        # Prefer cached global model; init once with local path if available, otherwise allow download
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            logger.debug(f"sentence-transformers not available: {e}")
            raise

        if e5_model is None:
            with e5_lock:
                if e5_model is None:
                    try:
                        # Try local path first if it exists
                        if E5_LOCAL_PATH and os.path.exists(E5_LOCAL_PATH):
                            logger.debug(f"Loading E5 model from local path: {E5_LOCAL_PATH}")
                            _model = SentenceTransformer(E5_LOCAL_PATH, local_files_only=True)
                        else:
                            logger.debug(f"Loading E5 model by name: {E5_MODEL_NAME}")
                            _model = SentenceTransformer(E5_MODEL_NAME)
                        e5_model = _model
                    except Exception as e:
                        logger.debug(f"Failed to initialize E5 model: {e}")
                        raise

        # E5 expects task prefixes: 'query: ' for queries and 'passage: ' for docs.
        # Here we default to query-style for get_query_embedding use.
        try:
            return e5_model.encode([f"query: {text}"], convert_to_numpy=True, show_progress_bar=E5_SHOW_PROGRESS)[0].tolist()
        except Exception as e:
            logger.debug(f"E5 encoding failed: {e}")
            raise

    elif provider == "gemini":
        global GEMINI_DISABLED
        if GEMINI_DISABLED or not USE_GEMINI_EMBEDDINGS:
            raise RuntimeError("Gemini embeddings disabled (session or config)")
        if not google_client:
            raise ValueError("Google GenAI client not initialized")
        safe_text = _sanitize_text(text)
        try:
            result = google_client.models.embed_content(
                model=model,
                contents=safe_text,
                config={"http_options": {"timeout": 10}}
            )
            return result.embeddings[0].values
        except Exception as e:  # capture quota and set disable
            quota_hit = False
            msg = str(e).lower()
            if g_exceptions and isinstance(e, g_exceptions.ResourceExhausted):
                quota_hit = True
            elif 'resourceexhausted' in msg or 'quota' in msg:
                quota_hit = True
            if quota_hit:
                GEMINI_DISABLED = True
                logger.warning("Gemini quota exhausted — disabling further Gemini embedding attempts this session")
            raise

    logger.debug(f"Unknown provider: {provider}")
    raise ValueError(f"Unknown provider: {provider}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def store_embedding(doc_id: str, text: str, embedding: List[float], provider: str) -> None:
    """Store embedding in the appropriate collection with retry logic."""
    try:
        
        record = {
            "_id": doc_id,
            "text": text,
            "embedding": embedding,
            "provider": provider,
            "created_at": datetime.utcnow(),
            "token_count": count_tokens(text)
        }
        
        collection = target_collection if provider == "openai" else gemini_collection
        result = collection.update_one(
            {"_id": doc_id},
            {"$set": record},
            upsert=True
        )
        
    except Exception as e:
        logger.debug(f"Failed to store embedding for {doc_id}: {str(e)}")
        raise

def get_query_embedding(query: str) -> List[float]:
    """Get embedding for query with automatic fallback through providers."""
    
    last_error = None
    import traceback
    providers = [
        ("openai", EMBEDDING_MODEL), 
        ("gemini", "text-embedding-004"),
        ("gemini", "gemini-embedding-001")
    ]
    if not E5_EFFECTIVE_DISABLED:
        providers.append(("intfloat", E5_MODEL_NAME))
    for provider, model in providers:
        if provider == "openai" and not USE_OPENAI:
            continue
        if provider == "gemini" and (not USE_GEMINI_EMBEDDINGS or GEMINI_DISABLED):
            continue
        try:
            emb = _get_embedding_from_provider(provider, model, query)
            return emb
        except Exception as e:
            last_error = e
            logger.error(f"[Embedding Fallback] {provider} ({model}) failed: {e}")
            # If gemini quota exhausted we just continue to next provider without noisy stack
            if not (provider == 'gemini' and 'quota' in str(e).lower()):
                traceback.print_exc()

    # Skip local-only fallback by default unless explicitly allowed and runtime supports it
    if (not E5_EFFECTIVE_DISABLED) and E5_LOCAL_PATH and os.path.exists(E5_LOCAL_PATH):
        try:
            logger.info("Trying final local-only E5 embedding fallback...")
            from sentence_transformers import SentenceTransformer
            local_model = SentenceTransformer(E5_LOCAL_PATH, local_files_only=True)
            emb = local_model.encode([f"query: {query}"], convert_to_numpy=True, show_progress_bar=E5_SHOW_PROGRESS)[0].tolist()
            logger.info("Local-only E5 embedding generated successfully.")
            return emb
        except Exception as e:
            logger.error(f"Local intfloat/e5-base embedding failed: {e}")
            traceback.print_exc()

    logger.error(f"All embedding providers failed. Last error: {str(last_error)}")
    if last_error:
        logger.error("Full traceback for last error follows")
        traceback.print_exception(type(last_error), last_error, last_error.__traceback__)
    raise RuntimeError(f"All embedding providers failed. Last error: {str(last_error)}")

def list_active_embedding_providers() -> List[str]:
    """Return list of embedding providers that are currently eligible (before runtime failures)."""
    active = []
    if USE_OPENAI:
        active.append("openai")
    if USE_GEMINI_EMBEDDINGS and not GEMINI_DISABLED:
        active.append("gemini")
    # Local intfloat only when not disabled and runtime-capable
    if not E5_EFFECTIVE_DISABLED:
        active.append("intfloat-e5")
    return active

# ===== DATABASE OPERATIONS =====
def verify_vector_indexes() -> None:
    """Verify required vector indexes exist."""
    
    required_indexes = {
        TARGET_COLLECTION: [VECTOR_INDEX_NAME],
        GEMINI_EMBEDDING_COLLECTION: [GEMINI_VECTOR_INDEX]
    }
    for coll_name, indexes in required_indexes.items():
        coll = db[coll_name]
        existing = [idx['name'] for idx in coll.list_indexes()]
        
        for idx in indexes:
            if idx not in existing:
                logger.debug(f"Missing required index {idx} in {coll_name}")
                raise RuntimeError(f"Missing required index {idx} in {coll_name}")

def check_mongo_health() -> bool:
    """Check MongoDB connection health."""
    
    try:
        result = mongo_client.admin.command('ping')
        
        return result.get('ok', 0) == 1
    except Exception as e:
        
        return False

# ===== WATCHER THREADS =====
def watch_collection(collection: collection.Collection) -> None:
    """Watch a collection for changes and update embeddings."""
    logger.debug(f"[Watcher] Listening for changes on {collection.name}...")
    with collection.watch(full_document='updateLookup') as stream:
        for change in stream:
            try:
                if change["operationType"] in ["insert", "update", "replace"]:
                    doc = change["fullDocument"]
                    doc_id = str(doc["_id"])
                    text = doc.get("content") or doc.get("text") or ""
                    
                    if not text.strip():
                        continue

                    try:
                        if not google_client:
                            logger.error("[Watcher] Google GenAI client not initialized")
                            continue
                        emb_result = google_client.models.embed_content(
                            model="text-embedding-004", 
                            contents=text
                        )
                        emb = emb_result.embeddings[0].values
                        store_embedding(doc_id, text, emb, "gemini")
                        logger.debug(f"[Watcher] Stored embedding for doc {doc_id}")
                    except Exception as e:
                        logger.debug(f"[Watcher] Failed to process doc {doc_id}: {e}")

            except Exception as e:
                logger.debug(f"[Watcher] Error processing change: {e}")

def watch_and_update_embeddings() -> None:
    """Start watcher threads for all source collections."""
    # Create dedicated client for watchers
    watcher_client = MongoClient(
        MONGO_URI,
        maxPoolSize=len(SOURCE_COLLECTIONS) * 2,
        socketTimeoutMS=30000,
        connectTimeoutMS=10000
    )
    
    threads = []
    for col_name in SOURCE_COLLECTIONS:
        thread = threading.Thread(
            target=watch_collection,
            args=(watcher_client[DB_NAME][col_name],),
            daemon=True
        )
        thread.start()
        threads.append(thread)
    
    logger.debug(f"[Watcher] Started {len(threads)} watcher threads")
    
    try:
        while True:
            time.sleep(10)
            # Monitor thread health
            for i, thread in enumerate(threads[:]):
                if not thread.is_alive():
                    logger.debug(f"[Watcher] Restarting dead thread for {SOURCE_COLLECTIONS[i]}")
                    new_thread = threading.Thread(
                        target=watch_collection,
                        args=(watcher_client[DB_NAME][SOURCE_COLLECTIONS[i]],),
                        daemon=True
                    )
                    new_thread.start()
                    threads[i] = new_thread
    except KeyboardInterrupt:
        logger.debug("[Watcher] Shutting down watchers (KeyboardInterrupt)...")
    except Exception as e:
        logger.debug(f"[Watcher] Exiting due to unexpected error: {e}")
import os

# Will be True only if USE_OPENAI in .env is set to "true" (case-insensitive)
USE_OPENAI = os.getenv("USE_OPENAI", "true").lower() == "true"
# ===== HYBRID SEARCH =====
def retrieve_hybrid(query: str, k: int = 20) -> List[Dict]:
    
    query_emb = get_query_embedding(query)
    

    def search_collection(collection: collection.Collection, index_name: str) -> List[Dict]:
        try:
            
            results = list(collection.aggregate([
                {
                    "$vectorSearch": {
                        "queryVector": query_emb,
                        "path": "embedding",
                        "numCandidates": min(100, k * 5),
                        "limit": k,
                        "index": index_name
                    }
                }
            ], maxTimeMS=10000))
            
            
        except Exception as e:
            logger.debug(f"Vector search failed on {collection.name}: {e}")
            return []

    if USE_OPENAI:
        results = search_collection(target_collection, VECTOR_INDEX_NAME)
    else:
        results = search_collection(gemini_collection, GEMINI_VECTOR_INDEX)

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    
    return results[:k]


    # Normalize and combine results
    def normalize_results(results: List[Dict], provider: str) -> List[Dict]:
        return [{
            "document": r,
            "score": r.get("score", 0),
            "provider": provider
        } for r in results]

    combined = (
        normalize_results(openai_results, "openai") + 
        normalize_results(gemini_results, "gemini")
    )
    combined.sort(key=lambda x: x["score"], reverse=True)
    
    return combined[:k]

# ===== MAIN =====
if __name__ == "__main__":
    
    verify_vector_indexes()
    if not check_mongo_health():
        raise RuntimeError("MongoDB connection failed")
    
    
    watch_and_update_embeddings()
    update_embeddings()