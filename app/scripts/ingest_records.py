import uuid
from app.core.chunker import record_to_chunks
from app.core.embeddings import get_query_embedding
from app.core.data_ingest import insert_structured_document
from app.db.vector_store import vector_store
from app.memory.memory_manager import add_query_to_memory  # ✅ Memory system

def ingest_record(record):
    
    account = record.get("account")
    year = record.get("year")
    quarter = record.get("quarter")
    revenue = record.get("revenue")
    session_id = record.get("session_id", "default_session")

    
    chunks = record_to_chunks(record)
    

    for i, chunk in enumerate(chunks):
        
        chunk_id = str(uuid.uuid4())  # ✅ Unique ID for tracking
        embedding = get_query_embedding(chunk)
        

        metadata = {
            "account": account,
            "year": year,
            "quarter": quarter,
            "revenue": revenue,
            "session_id": session_id,
            "chunk_id": chunk_id,
        }
        

        # ✅ Insert into vector DB
        
        vector_store.insert({
            "id": chunk_id,
            "text": chunk,
            "embedding": embedding,
            "metadata": metadata
        })

        # ✅ Insert into MongoDB
        
        insert_structured_document(
            text=chunk,
            account=account,
            year=year,
            quarter=quarter,
            revenue=revenue,
            session_id=session_id,
            chunk_id=chunk_id
        )

        # ✅ Update memory system
       
        add_query_to_memory(query=chunk, metadata=metadata)

# Example usage
if __name__ == "__main__":
    sample_record = {
        "account": "Apple",
        "year": 2024,
        "quarter": "Q1",
        "revenue": 117200000000.00,
        "session_id": "session_apple_q1",
        "notes": "Record Q1 revenue driven by iPhone and services."
    }

    ingest_record(sample_record)
