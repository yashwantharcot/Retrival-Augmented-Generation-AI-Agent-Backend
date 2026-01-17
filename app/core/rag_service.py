from app.core.embeddings import get_query_embedding
from app.core.retriever import Retriever
from app.core.llm import OpenAIEngine
from app.db.mongo import collection
from app.config import VECTOR_INDEX_NAME
from app.core.query_resolver import resolve_query 
import os
import re
from app.db.vector_store import search_similar_documents
from app.core.retriever import Retriever

from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGODB_URI")
client = MongoClient(MONGO_URI)
db = client["dev_db"]    # <-- database name you want to use
 
llm = OpenAIEngine()
def extract_entities(query: str) -> dict:
    
    """
    Basic entity extraction using regular expressions.
    Returns entities like companies, dates, and numbers.
    """
    entities = {
        "ORG": [],
        "DATE": [],
        "MONEY": [],
        "QUARTER": [],
        "YEAR": []
    }
    
    # Extract companies (words starting with capital letters)
    entities["ORG"] = re.findall(r'\b([A-Z][a-z]+)\b', query)
    
    # Extract years (4-digit numbers)
    entities["YEAR"] = re.findall(r'\b(20\d{2}|19\d{2})\b', query)
    
    # Extract quarters (Q1-Q4)
    entities["QUARTER"] = re.findall(r'\b(Q[1-4])\b', query, flags=re.IGNORECASE)
    
    # Extract money ($1M, $500K, etc.)
    entities["MONEY"] = re.findall(r'\$\d+[MK]?\b', query)
    
    # Combine quarters and years into DATE
    if entities["QUARTER"] and entities["YEAR"]:
        entities["DATE"] = [f"{q} {y}" for q in entities["QUARTER"] for y in entities["YEAR"]]
    
    return {k: v for k, v in entities.items() if v} # Empty metadata for now, you can simulate test metadata if needed

#  CORRECT Retriever initialization
retriever = Retriever(
    openai_collection=db["dd_accounts_chunks"],
    gemini_collection=db["dd_accounts_chunks_gemini"],
    openai_index="vector_index_v2",
    gemini_index="vector_index_gemini_v2"
)

 # <- This wraps GPT coref logic

'''def handle_query(session_id: str, query: str) -> dict:
    # Step 0: Resolve coreference using GPT and memory
    
    resolved_query = resolve_query(session_id, query)
    
    embedding = get_query_embedding(query)
    
    results = search_similar_documents(embedding)
    
    

    metadata = extract_entities(resolved_query)
    

    
    save_query_to_history(
        session_id=session_id,
        query=query,
        metadata=metadata,
        embedding=embedding
    )

    
    retrieved_docs = retriever.retrieve(
        query=resolved_query,
        metadata_filter=metadata,
        vector=embedding
    )
    
    

    
    history = get_recent_queries(session_id)
    

    
    prompt = build_enriched_prompt(resolved_query, retrieved_docs, history)
    

    
    response = generate_answer(prompt)
    

    
    save_query_to_history(
        session_id=session_id,
        query=query,
        metadata=metadata,
        embedding=embedding,
        response=response
    )

    return {
        "query_used": resolved_query,
        "response": response,
        "retrieved_docs": retrieved_docs
    }
llm = OpenAIEngine()'''



from app.services.web_search import search_web, search_youtube  # <-- you’ll create this
from app.core.llm import OpenAIEngine

llm = OpenAIEngine()

def handle_query(session_id: str, query: str) -> dict:
    # Step 0: Resolve coreference
    resolved_query = resolve_query(session_id, query)

    # Step 1: Embed & search in vector DB
    embedding = get_query_embedding(resolved_query)
    results = search_similar_documents(embedding)

    metadata = extract_entities(resolved_query)

    save_query_to_history(
        session_id=session_id,
        query=query,
        metadata=metadata,
        embedding=embedding
    )

    retrieved_docs = retriever.retrieve(
        query=resolved_query,
        metadata_filter=metadata,
        vector=embedding
    )

    # ✅ Step 2: If no relevant docs, fallback to web
    if not retrieved_docs or len(retrieved_docs) == 0:
        web_results = search_web(resolved_query)       # returns [{"title":..., "link":...}, ...]
        yt_results = search_youtube(resolved_query)    # returns [{"title":..., "link":...}, ...]

        prompt = f"""
        Question: {resolved_query}

        I couldn't find enough info in the internal knowledge base.
        Here are some relevant external sources:

        Websites:
        { [r['link'] for r in web_results[:3]] }

        YouTube:
        { [r['link'] for r in yt_results[:2]] }

        Please provide a helpful answer and recommend the above links.
        """

        response = llm.generate(prompt)

        return {
            "query_used": resolved_query,
            "response": response,
            "retrieved_docs": [],
            "external_links": {
                "websites": [r['link'] for r in web_results[:3]],
                "youtube": [r['link'] for r in yt_results[:2]]
            }
        }

    # ✅ Step 3: Otherwise, use normal RAG flow
    history = get_recent_queries(session_id)
    prompt = build_enriched_prompt(resolved_query, retrieved_docs, history)
    response = generate_answer(prompt)

    save_query_to_history(
        session_id=session_id,
        query=query,
        metadata=metadata,
        embedding=embedding,
        response=response
    )

    return {
        "query_used": resolved_query,
        "response": response,
        "retrieved_docs": retrieved_docs
    }


def generate_answer(query: str):
    
    return llm.generate(query)