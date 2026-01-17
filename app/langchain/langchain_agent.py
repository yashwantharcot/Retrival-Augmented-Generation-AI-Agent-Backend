import os
from app.core.embeddings import get_query_embedding
from app.config import LLM_MODEL
from app.core.llm import OpenAIEngine
from app.db.vector_store import search_similar_documents

def rag_with_tavily(query: str, user_id: str = None, session_id: str = None):
    """
    Hybrid RAG: First search vector DB, if not relevant then Tavily web search.
    """
    context = ""
    source = "None"

    # Step 1: Try vector DB
    try:
        query_embedding = [float(x) for x in get_query_embedding(query)]
        vector_results = search_similar_documents(query_vector=query_embedding, k=3)
    except Exception as e:
        print(f"[ERROR] Vector search failed: {e}")
        vector_results = []

    if vector_results and len(vector_results) > 0:
        context = "\n".join([doc.get("text", "") for doc in vector_results if doc.get("text")])
        source = "VectorDB"
    else:
        # Step 2: Fallback to Tavily web search
        try:
            raise NotImplementedError("Tavily search has been removed.")
            if tavily_results:
                context = "\n".join([r.get("content", "") for r in tavily_results if r.get("content")])
                source = "Tavily"
        except Exception as e:
            print(f"[ERROR] Tavily search failed: {e}")
            context = ""
            source = "None"

    # Step 3: Build prompt
    prompt = f"""
    You are a helpful assistant.
    
    User query:
    {query}

    Retrieved context ({source}):
    {context if context else "[No relevant context found]"}
    
    Answer the question using the above context. 
    If the context does not contain the answer, say you don't know.
    """

    # Step 4: Call LLM
    engine = OpenAIEngine(model=LLM_MODEL)
    answer = engine.generate(prompt)

    return {
        "query": query,
        "answer": answer,
        "source": source
    }

