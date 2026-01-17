# app/db/memory.py
from pymongo import MongoClient
from app.config import MONGO_URI
from datetime import datetime

client = MongoClient(MONGO_URI)
memory_collection = client["dev_db"]["dd_memory_entries_rag"]

def search_similar_memories(query_vector, k=5, metadata_filter: dict = None):
    """
    Perform a vector similarity search over memory entries.
    Args:
        query_vector (list[float]): The vector representation of the query.
        k (int): Number of top similar memories to return.
        metadata_filter (dict, optional): Metadata filters to narrow down search scope.
    Returns:
        list: List of matching memory entries with similarity scores.
    """
    
    
        
    query_vector = [float(x) for x in query_vector]
    pipeline = [
        {
            "$vectorSearch": {
                "index": "memory_embedding_index",  # Ensure this index exists in MongoDB Atlas
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
                "score": {"$meta": "vectorSearchScore"}
            }
        },
        {
            "$project": {
                "_id": 0,
                "user_id": 1,
                "query_text": 1,
                "resolved_query": 1,
                "llm_response": 1,
                "embedding": 1,
                "timestamp": 1,
                "score": 1
            }
        }
    ]
    
    try:
        results = list(memory_collection.aggregate(pipeline))
        
        if results:
            for i, doc in enumerate(results[:4]):
                print(f"[DEBUG] Memory {i+1}: user_id={doc.get('user_id')}, score={doc.get('score')}, query_text={doc.get('query_text')[:100]}")
        return results if results is not None else []
    except Exception as e:
        print(f"[ERROR] Memory vector search failed: {e}")
        return []



def insert_memory(entry: dict):
    from datetime import datetime

    

    session_id = entry.get("session_id")
    user_id = entry.get("user_id")
    llm_response = entry.get("llm_response")

    # safety check
    if not session_id or not user_id or llm_response is None:
        print(f"[ERROR] insert_memory(): missing session_id, user_id, or llm_response → {entry}")
        return None

    # Ensure document exists for user/session
    memory_collection.update_one(
        {"session_id": session_id, "user_id": user_id},
        {"$setOnInsert": {"session_id": session_id, "user_id": user_id}},
        upsert=True
    )

    embedding = entry.get('embedding')
    embedding_len = len(embedding) if embedding is not None else 0
    

    # Push chat entry
    result = memory_collection.update_one(
        {"session_id": session_id, "user_id": user_id},
        {
            "$push": {
                "chats": {
                    "query_text": entry.get("query_text"),
                    "resolved_query": entry.get("resolved_query"),
                    "embedding": entry.get("embedding"),
                    "entities": entry.get("entities"),
                    "topics": entry.get("topics"),
                    "account_id": entry.get("account_id"),
                    "quarter": entry.get("quarter"),
                    "chunk_id": entry.get("chunk_id"),
                    "llm_response": llm_response,
                    "source_docs": entry.get("source_docs"),
                    "timestamp": entry.get("timestamp") or datetime.utcnow()
                }
            }
        },
        upsert=True
    )

    

    return result.upserted_id if result.upserted_id else session_id





def get_last_memory(session_id: str, limit: int = 1):
    
    results = list(memory_collection.find({"session_id": session_id}).sort("timestamp", -1).limit(limit))
    
    
        
    return results







