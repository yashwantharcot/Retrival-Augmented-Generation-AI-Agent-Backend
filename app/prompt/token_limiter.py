# app/prompt/token_limiter.py
from app.core.embeddings import count_tokens
def format_structured_data(documents, query, preferences=None):
    """
    Formats retrieved documents and query into a structured response.
    
    Args:
        documents (List[Dict]): List of documents retrieved from vector search.
        query (str): The resolved user query.
    
    Returns:
        Dict: Structured response for the RAG pipeline.
    """
    if not documents:
        return {"answer": "No relevant documents found.", "context": []}


    user_tone = preferences.get('tone', 'default') if preferences else 'default'
    detail_level = preferences.get('detail_level', 'standard') if preferences else 'standard'
    max_tokens = 2048  # Example limit, adjust as needed
    included_context = []
    included_metadata = []
    total_tokens = count_tokens(query)
    for doc in documents:
        chunk_tokens = count_tokens(doc["chunk"])
        if total_tokens + chunk_tokens > max_tokens:
            break
        # Personalization: adjust chunk by preferred tone/detail if available
        tone = doc["metadata"].get("tone", user_tone)
        detail = doc["metadata"].get("detail_level", detail_level)
        personalized_chunk = f"[Tone: {tone}][Detail: {detail}] {doc['chunk']}"
        included_context.append(personalized_chunk)
        included_metadata.append(doc["metadata"])
        total_tokens += chunk_tokens

    # Weighted history prioritization (if available in metadata)
    weighted_context = []
    for i, ctx in enumerate(included_context):
        weight = included_metadata[i].get("weight", 1)
        weighted_context.append((weight, ctx))
    weighted_context.sort(reverse=True)
    sorted_context = [ctx for _, ctx in weighted_context]

    structured_response = {
        "answer": "Generated answer based on documents and query",
        "context": sorted_context,
        "metadata": included_metadata,
        "query": query
    }

    return structured_response

