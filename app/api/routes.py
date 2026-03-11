from fastapi import APIRouter, Request
from typing import Optional
from pydantic import BaseModel
from app.memory.memory_manager import get_entity_manager, set_entity_from_query
from app.pipeline.rag_engine import RAGEngine
from app.db.mongo import save_conversation
from app.pipeline.rag_engine import RAGEngine
from app.db.memory import insert_memory, search_similar_memories
from app.db.mongo import memory_collection
from app.api.pdf_qa import router as pdf_qa_router
router = APIRouter()

class RAGQueryInput(BaseModel):
    session_id: str
    query: str

class MemoryEntry(BaseModel):
    session_id: str
    user_id: str
    query_text: str
    resolved_query: str = None
    embedding: list = None
    entities: list = None
    topics: list = None
    account_id: str = None
    quarter: str = None
    chunk_id: str = None
    llm_response: str = None
    source_docs: list = None
    timestamp: str = None

class MemorySearchInput(BaseModel):
    query_vector: list
    k: int = 5
    metadata_filter: dict = None

@router.get("/ping")
def ping():
    return {"ping": "pong"}

# --- Memory Endpoints ---
@router.post("/memory")
def store_memory(entry: MemoryEntry):
    result = insert_memory(entry.dict())
    return {"result": result}

@router.get("/memory/{session_id}")
def get_memory(session_id: str, limit: int = 50, user_id: Optional[str] = None):
    """Return embedded chats for a session; user_id optional.

    Shape is compatible with FE's res.data.chats expectation.
    """
    query = {"session_id": session_id}
    if user_id:
        query["user_id"] = user_id
    doc = memory_collection.find_one(query, {"_id": 0})
    if not doc:
        return {"session_id": session_id, "user_id": user_id, "chats": []}
    chats = doc.get("chats", [])
    if limit and limit > 0:
        chats = chats[-limit:]
    return {"session_id": doc.get("session_id"), "user_id": doc.get("user_id"), "chats": chats}

@router.post("/memory/search")
def search_memory(input_data: MemorySearchInput):
    results = search_similar_memories(input_data.query_vector, input_data.k, input_data.metadata_filter)
    return {"results": results}

@router.post("/ask")
def ask_question(input_data: RAGQueryInput):
    answer = RAGEngine(input_data.query, input_data.session_id)
    return {"answer": answer}


@router.post("/rag")
async def rag_query(request: Request):
    data = await request.json()
    session_id = data["session_id"]
    original_query = data["query"]
    query = original_query

   

    # 1. Replace pronouns with last known entity
    last_entity = get_entity_manager(session_id, "entity_nlp") or get_entity_manager(session_id, "entity_rule")
    if last_entity:
        query = re.sub(r'\bits\b', f"{last_entity}'s", query, flags=re.IGNORECASE)
        query = re.sub(r'\bit\b', last_entity, query, flags=re.IGNORECASE)
        

    # 2. Extract new entity from query (GPT/rule-based inside this function)
    set_entity_from_query(session_id, query)
    

    # 3. Run RAG
    answer = RAGEngine(query, session_id)
    

    # 4. Save to DB
    save_conversation(session_id, original_query, query, answer)

    return {"query_used": query, "response": answer}


# Mount PDF Q&A subrouter
router.include_router(pdf_qa_router, prefix="/pdf-qa")



