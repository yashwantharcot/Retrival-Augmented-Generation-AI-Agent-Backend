
# app/db/vector_store.py
from pymongo import MongoClient
from fastapi import HTTPException
from bson.errors import InvalidDocument
from app.config import MONGO_URI, DB_NAME, TARGET_COLLECTION, VECTOR_INDEX_NAME
import json
import logging

logger = logging.getLogger(__name__)

# Initialize MongoDB client
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[TARGET_COLLECTION]
'''
def search_similar_documents(query_vector, k=20, metadata_filter: dict = None):
    """
    Perform a vector similarity search with optional metadata filtering.
    
    Args:
        query_vector (list[float]): The vector representation of the query.
        k (int): Number of top similar documents to return.
        metadata_filter (dict, optional): Metadata filters to narrow down search scope.

    Returns:
        list: List of matching documents with similarity scores.
    """

    # ✅ Fix 1: Convert to native Python float
    query_vector = [float(x) for x in query_vector]

    

    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": k,
                "similarity": "cosine",
                **({"filter": metadata_filter} if metadata_filter else {})
            }
        },
        {
            "$addFields": {
                "doc_id": {"$ifNull": ["$doc_id", ""]},
                "chunk": {"$ifNull": ["$chunk", ""]},
                "metadata": {"$ifNull": ["$metadata", {}]},
                "structured_data": {"$ifNull": ["$structured_data", {}]},
            }
        },
        {
            "$project": {
                "_id": 0,
                "doc_id": 1,
                "chunk": 1,
                "metadata": 1,
                "structured_data": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]

    try:
        results = list(collection.aggregate(pipeline))
        return results if results is not None else []
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        return []'''




def search_similar_documents(query_vector, k=20, metadata_filter: dict = None):
    query_vector = [float(x) for x in query_vector]
    dim = len(query_vector)

    # Dynamically pick collection + index
    if dim == 1536:
        collection = db["dd_accounts_chunks"]
        index_name = "vector_index_v2"
    elif dim == 1024:
        collection = db["dd_accounts_chunks_gemini"]
        index_name = "vector_index_gemini_v2"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported embedding dimension: {dim}")

    pipeline = [
        {
            "$vectorSearch": {
                "index": index_name,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": k,
                "similarity": "cosine",
                **({"filter": metadata_filter} if metadata_filter else {})
            }
        },
        {
            "$addFields": {
                "doc_id": {"$ifNull": ["$doc_id", ""]},
                "chunk": {"$ifNull": ["$chunk", ""]},
                "metadata": {"$ifNull": ["$metadata", {}]},
                "structured_data": {"$ifNull": ["$structured_data", {}]},
            }
        },
        {
            "$project": {
                "_id": 0,
                "doc_id": 1,
                "chunk": 1,
                "metadata": 1,
                "structured_data": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]

    try:
        results = list(collection.aggregate(pipeline))
        
        
        
        return results if results is not None else []
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        return []

   


