# app/core/memory_schema.py
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

def build_memory_entry(
    user_id: str,
    query_text: str,
    resolved_query: Optional[str],
    embedding: List[float],
    entities: Optional[List[str]] = None,
    topics: Optional[List[str]] = None,
    account_id: Optional[str] = None,
    quarter: Optional[str] = None,
    llm_response: Optional[str] = None,
    source_docs: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    chunk_id: Optional[str] = None
) -> dict:
    return {
        "memory_id": str(uuid4()),
        "user_id": user_id,
        "query_text": query_text,
        "resolved_query": resolved_query or query_text,
        "embedding": embedding,
        "timestamp": datetime.utcnow(),
        "entities": entities or [],
        "topics": topics or [],
        "account_id": account_id,
        "quarter": quarter,
        "llm_response": llm_response,
        "source_docs": source_docs or [],
        "session_id": session_id,
        "chunk_id": chunk_id
    }
