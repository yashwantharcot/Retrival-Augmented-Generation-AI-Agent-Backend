# app/core/query_resolver.py
from app.memory.memory_manager import get_entity_manager
from app.core.coreference import resolve_coreference  # import your GPT coreference resolver

def resolve_query(session_id: str, query: str):
    memory = get_entity_manager(session_id)
    
    # Optionally enrich query with memory (for GPT context)
    enriched_query = query
    if 'last_account' in memory:
        enriched_query += f" (context: last_account is {memory['last_account']})"
    
    resolved_query = resolve_coreference(enriched_query)
    return resolved_query
