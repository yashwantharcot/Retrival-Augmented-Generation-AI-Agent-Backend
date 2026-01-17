# app/services/memory_logger.py

from app.core.embeddings import get_embedding_for_text
from app.core.memory_schema import build_memory_entry
from app.db.memory import insert_memory

def add_query_to_memory_logger(  # renamed for consistency
    user_id: str,
    query_text: str,
    resolved_query: str = None,
    entities: list = None,
    topics: list = None,
    account_id: str = None,
    quarter: str = None,
    session_id: str = None,        
    chunk_id: str = None,         
    llm_response: str = None,
    source_docs: list = None
):
    embedding = get_embedding_for_text(resolved_query or query_text)

    memory_entry = build_memory_entry(
        user_id=user_id,
        query_text=query_text,
        resolved_query=resolved_query,
        embedding=embedding,
        entities=entities,
        topics=topics,
        account_id=account_id,
        quarter=quarter,
        session_id=session_id,    
        chunk_id=chunk_id,       
        llm_response=llm_response,
        source_docs=source_docs
    )

    memory_id = insert_memory(memory_entry)
    return memory_id
    

