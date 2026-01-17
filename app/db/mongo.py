def get_user_profile(user_id):
    """
    Fetch user profile and preferences for personalization.
    :param user_id: str
    :return: dict (user profile)
    """
    user_collection = db.get("users", None)
    if not user_collection:
        return {}
    profile = user_collection.find_one({"user_id": user_id})
    return profile if profile else {}
# app/db/mongo.py
from pymongo import MongoClient
from datetime import datetime
from app.config import MONGO_URI, DB_NAME, TARGET_COLLECTION, SOURCE_COLLECTIONS

# === Setup MongoDB Connection ===
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
target_col = db[TARGET_COLLECTION]
source_cols = [db[name] for name in SOURCE_COLLECTIONS]
history_col = db["query_history"]
memory_collection = db["dd_memory_entries_rag"]
conversation_col = db["conversation_history"]

class MongoHandler:
    def __init__(self, uri=MONGO_URI, db_name=DB_NAME):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]

    # === Generic CRUD ===
    def insert_document(self, collection: str, doc: dict):
        
        result = self.db[collection].insert_one(doc)
        
        return result

    def find_documents(self, collection: str, query: dict):
        
        results = list(self.db[collection].find(query))
        
        return results

   

    # === Save Conversation with Resolved Coreferences ===
    def save_conversation(self, session_id, original_query, resolved_query, response):
        
        document = {
            "session_id": session_id,
            "original_query": original_query,
            "resolved_query": resolved_query,
            "response": response,
            "timestamp": datetime.utcnow()
        }
        result = self.db["conversation_history"].insert_one(document)
        
        return result

    # === Retrieve Last Query for Coreference Resolution ===
    def get_last_query(self, session_id):
        
        result = self.db["conversation_history"].find_one(
            {"session_id": session_id},
            sort=[("timestamp", -1)]
        )
        
        return result

    # === Retrieve Conversation History (e.g., last N queries) ===
    def get_conversation_history(self, session_id, limit=5):
        
        results = list(
            self.db["conversation_history"]
                .find({"session_id": session_id})
                .sort("timestamp", -1)
                .limit(limit)
        )
        
        return results

    # === Vector Search with Metadata (Stub - for later vector DB support) ===
    def vector_search_with_metadata(self, embedding, metadata_filter: dict):
        
        # Replace with your real vector DB search call
        results = list(self.db[TARGET_COLLECTION].find(metadata_filter))
        
        return results

# === Instantiate Global MongoHandler ===
mongo_handler = MongoHandler()

# === Convenience Wrappers ===
def save_conversation(session_id, original_query, resolved_query, response):
    
    return mongo_handler.save_conversation(session_id, original_query, resolved_query, response)



def get_last_query(session_id):
    
    return mongo_handler.get_last_query(session_id)


# app/db/mongo.py

from pymongo import MongoClient
from datetime import datetime
import os

# initialize client (you can refactor to singleton if you already have one globally)
client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("MONGODB_DB")]
collection = db[os.getenv("MONGODB_COLLECTION")]  # e.g. "documents"

def get_documents_modified_since(cutoff_time: datetime):
    """
    Fetch all documents updated after the given cutoff_time
    :param cutoff_time: datetime
    :return: list of documents
    """
    
    results = list(
        collection.find({
            "modified_at": { "$gte": cutoff_time }
        })
    )
    
    return results

# app/db/mongo.py

from pymongo import MongoClient
from bson.objectid import ObjectId
import os



def update_document_embedding(doc_id: str, embedding):
    """
    Update the embedding for the document with the given _id.
    :param doc_id: str representation of MongoDB ObjectId
    :param embedding: list or numpy array of floats
    """
    
    result = collection.update_one(
        {"_id": ObjectId(doc_id)},
        {
            "$set": {
                "embedding": embedding,
                "modified_at": datetime.utcnow()   # optional: update timestamp
            }
        }
    )
    