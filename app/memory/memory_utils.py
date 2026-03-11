from datetime import datetime
from .memory_entry import MemoryEntry
from app.core.embeddings import get_query_embedding
from app.core.rag_service import extract_entities  # Assumed custom NER function


def is_company(entity: str) -> bool:
    """
    Basic check to determine if an entity looks like a company name.
    You can customize this with better NER models or knowledge base.
    """
    company_keywords = ["Inc", "Corp", "Ltd", "LLC", "Technologies", "Enterprises"]
    result = any(word in entity for word in company_keywords)
    
    return result




# app/memory/memory.py

from typing import List, Optional
from datetime import datetime
from app.db.memory import insert_memory
from app.memory.memory_entry import MemoryEntry
from app.core.embeddings import get_query_embedding
from app.core.rag_service import extract_entities 
from bson.objectid import ObjectId
from datetime import datetime
from pymongo import MongoClient
from app.config import MONGO_URI

client = None
memory_collection = None
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    memory_collection = client["dev_db"]["dd_memory_entries_rag"]
except Exception as e:
    print(f"[WARNING] MongoDB connection failed in memory/memory_utils.py: {e}")





def insert_memory_entry(entry: MemoryEntry) -> str:
    print(f"[DEBUG] insert_memory_entry called with entry: {entry}")
    result = memory_collection.insert_one(entry.dict())
    print(f"[DEBUG] Inserted memory entry with _id={result.inserted_id}")
    return str(result.inserted_id)

def get_last_chats(user_id, session_id, n=3):
    print(f"[DEBUG] get_last_chats called with user_id={user_id}, session_id={session_id}, n={n}")
    doc = memory_collection.find_one(
        {"user_id": user_id, "session_id": session_id},
        {"chats": {"$slice": -n}}
    )
    if doc and "chats" in doc:
        print(f"[DEBUG] Retrieved {len(doc['chats'])} chats.")
        for i, chat in enumerate(doc["chats"]):
            print(f"[DEBUG] Chat {i+1}: query_text={chat.get('query_text', '')[:100]}, timestamp={chat.get('timestamp', '')}")
        return doc["chats"]
    print(f"[DEBUG] No chats found.")
    return []
