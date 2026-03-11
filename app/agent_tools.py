"""
Agent Orchestration Tools for RAG Agent
Provides db_query and structured_search functions for specialized retrieval.
"""

from pymongo import MongoClient

from app.config import MONGO_URI

# Initialize MongoDB client
client = None
db = None

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["dev_db"]
except Exception as e:
    print(f"[WARNING] MongoDB connection failed in agent_tools.py: {e}")

# Tool: DB Query

def db_query(collection_name, filter_dict, projection=None):
    collection = db[collection_name]
    return list(collection.find(filter_dict, projection or {}))

# Tool: Structured Search (e.g., keyword or field-based)

def structured_search(collection_name, keywords, fields=None):
    collection = db[collection_name]
    query = {"$text": {"$search": " ".join(keywords)}} if keywords else {}
    if fields:
        projection = {field: 1 for field in fields}
    else:
        projection = None
    return list(collection.find(query, projection))

# Dispatcher Example

def agent_dispatcher(query_text):
    # Simple intent detection (expand as needed)
    if "show all quotes" in query_text.lower():
        return db_query("dd_quotes", {}, {"_id": 0})
    elif "search account" in query_text.lower():
        keywords = query_text.lower().split()
        return structured_search("dd_accounts_chunks", keywords, fields=["chunk", "account_id"])
    else:
        return None  # Fallback to normal RAG
