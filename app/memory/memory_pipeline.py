from app.memory.memory_utils import insert_memory_entry
from app.memory.memory_manager import set_entity_from_query
from pymongo import MongoClient
from app.config import MONGO_URI





def enrich_query_with_memory(session_id: str, query: str) -> str:
    """
    Replace pronouns in the query using stored session memory to create a clearer context.
    """
    import re

    
    replacements = {
        "he": get_entity(session_id, "entity_nlp"),
        "she": get_entity(session_id, "entity_nlp"),
        "they": get_entity(session_id, "entity_nlp"),
        "it": get_entity(session_id, "entity_nlp"),
        "that account": get_entity(session_id, "account"),
        "the company": get_entity(session_id, "account")
    }
    
    enriched_query = query
    for pronoun, actual in replacements.items():
        if actual:
            
            enriched_query = re.sub(rf"\b{pronoun}\b", actual, enriched_query, flags=re.IGNORECASE)
    
    return enriched_query

client = MongoClient(MONGO_URI)
memory_collection = client["dev_db"]["dd_memory_entries_rag"]

def get_entity(session_id: str, entity_type: str) -> list:
    """
    Fetches entries from memory_collection based on session_id and entity_type (e.g., 'entity_nlp').

    Args:
        session_id (str): The session ID for the user session.
        entity_type (str): The type of entity to retrieve (e.g., 'entity_nlp', 'intent').

    Returns:
        list: A list of matched memory entries for the session and type.
    """
    
    query = {
        "session_id": session_id,
        "type": entity_type
    }
    
    results = memory_collection.find(query).sort("timestamp", -1)
    results_list = list(results)
    
    
    return results_list
