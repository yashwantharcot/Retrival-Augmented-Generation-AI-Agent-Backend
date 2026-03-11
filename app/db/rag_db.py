# app/db/rag_db.py

from pymongo import MongoClient
from datetime import datetime
import uuid

# MongoDB connection details (use your secure URI or load from env)
from app.config import MONGO_URI, DB_NAME, TARGET_COLLECTION as MEMORY_COLLECTION

# === Setup Client ===
client = None
db = None
memory_collection = None

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[DB_NAME]
    memory_collection = db[MEMORY_COLLECTION]
except Exception as e:
    print(f"[WARNING] MongoDB connection failed in db/rag_db.py: {e}")



# === Get last N memory entries (optional filtering by session) ===
def get_recent_memory_entries(session_id: str = None, limit: int = 5):
    
    query = {}
    if session_id:
        query["session_id"] = session_id
    
    results = list(
        memory_collection.find(query)
                         .sort("timestamp", -1)
                         .limit(limit)
    )
    
    
    return results

# === Get memory by keyword or metadata (for filtered RAG retrieval) ===
def search_memory_by_metadata(metadata_query: dict):
    
    results = list(memory_collection.find(metadata_query))
    
    
    return results


