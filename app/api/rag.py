# app/routes/rag.py

from fastapi import Request, APIRouter
from app.memory.memory_manager import get_entity_manager, set_entity
from app.pipeline.rag_engine import rag_pipeline
from app.utils.entity_extractor import extract_account_name  # if you modularized it

router = APIRouter()




@router.post("/rag")
async def rag_query(request: Request):
    data = await request.json()
    session_id = data["session_id"]
    query = data["query"]

    # Try to get last account from memory
    last_account = get_entity_manager(session_id, "last_account")

    # Replace 'it' or 'its' if available
    import re
    if last_account:
        query = re.sub(r'\bits\b', f"{last_account}'s", query, flags=re.IGNORECASE)
        query = re.sub(r'\bit\b', last_account, query, flags=re.IGNORECASE)


    # Extract new entity if present
    entity = extract_account_name(query)
    if entity:
        set_entity(session_id, "last_account", entity)

    # Run RAG
    answer = rag_pipeline(query)
    return {"query_used": query, "response": answer}


