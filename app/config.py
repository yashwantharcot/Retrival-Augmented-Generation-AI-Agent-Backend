from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGODB_URI")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # for Gemini fallback
HF_API_KEY = os.getenv("HF_API_KEY") 
MAX_PROMPT_TOKENS = 4096  # or some integer

GEMINI_EMBEDDING_COLLECTION = "dd_accounts_chunks_gemini"
# Configurations
DB_NAME = "dev_db"
COLLECTION_NAME = "dd_accounts_chunks"
VECTOR_INDEX_NAME = "vector_index_v2"
EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"  # or "gpt-3.5-turbo"
GEMINI_VECTOR_INDEX = "vector_index_gemini_v2"
# Source collections
SOURCE_COLLECTIONS = ["dd_accounts", "dd_opportunities", "dd_quotes"]
TARGET_COLLECTION = "dd_accounts_chunks"

# Optional Mongo client (lazy, fail-safe)
from pymongo import MongoClient
from pymongo.errors import ConfigurationError

MONGO_CLIENT = None

def get_mongo_client() -> MongoClient | None:
    """Return a shared MongoClient or None if not available.

    Avoids import-time SRV lookups that can crash the app in local/dev.
    """
    global MONGO_CLIENT
    if MONGO_CLIENT is not None:
        return MONGO_CLIENT
    uri = MONGO_URI
    if not uri:
        return None
    try:
        # Keep short timeouts; connection may still fail later at first operation
        MONGO_CLIENT = MongoClient(
            uri,
            maxPoolSize=50,
            waitQueueTimeoutMS=10000,
            socketTimeoutMS=30000,
            serverSelectionTimeoutMS=3000,
        )
        return MONGO_CLIENT
    except ConfigurationError:
        # Bad DNS SRV or URI; continue without DB
        MONGO_CLIENT = None
        return None
    except Exception:
        MONGO_CLIENT = None
        return None