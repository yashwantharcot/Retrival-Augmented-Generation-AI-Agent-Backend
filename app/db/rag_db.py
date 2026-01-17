# app/db/rag_db.py

from pymongo import MongoClient
from datetime import datetime
import uuid

# MongoDB connection details (use your secure URI or load from env)
MONGO_URI = "MONGODB_URI"  # Replace with actual value or import from config
DB_NAME = "dev_db"
MEMORY_COLLECTION = "dd_memory_entries_rag"

# === Setup Client ===
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
memory_collection = db[MEMORY_COLLECTION]



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


