# app/memory/memory_manager.py
from typing import List, Optional
from pymongo import MongoClient
from app.memory.memory_entry import MemoryEntry
from app.config import MONGO_URI

# Initialize MongoDB client
client = None
db = None
memory_collection = None

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["dev_db"]
    memory_collection = db["dd_memory_entries_rag"]
except Exception as e:
    print(f"[WARNING] MongoDB connection failed in memory/memory_manager.py: {e}")

# In app/memory/memory_manager.py

def get_metadata_filter(session_id: str) -> dict:
    """
    Returns a metadata filter dictionary for MongoDB vector search,
    based on the session ID.
    """
    
    filter_dict = {"metadata.session_id": session_id}
    
    return filter_dict

def add_query_to_memory(session_id: str, query: str):
    """
    Store the user's query in memory with a timestamp for the given session.
    """
    
    memory_entry = {
        "query": query,
        "metadata": {
            "session_id": session_id,
        },
        "created_at": datetime.utcnow()
    }
    
    result = memory_collection.insert_one(memory_entry)
    
    return str(result.inserted_id)

def get_entity_manager(session_id: str) -> Optional[str]:
    """
    Get the last stored entity for a session.
    GPT-based entity should already be stored in memory.
    """
    
    doc = memory_collection.find_one(
        {"metadata.session_id": session_id, "metadata.entity": {"$exists": True}},
        sort=[("created_at", -1)]
    )
    
    return doc["metadata"]["entity"] if doc else None
from datetime import datetime

def set_entity_from_query(session_id: str, query: str, entity: str):
    """
    Store a user query and its extracted entity from GPT in memory.
    """
    
    entry = {
        "query": query,
        "metadata": {
            "session_id": session_id,
            "entity": entity
        },
        "created_at": datetime.utcnow()
    }
    
    result = memory_collection.insert_one(entry)
    
from typing import List

def get_query_history(session_id: str, limit: int = 5) -> List[dict]:
    
    docs = (
        memory_collection.find({"metadata.session_id": session_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    results = list(docs)
    
    
    return results




