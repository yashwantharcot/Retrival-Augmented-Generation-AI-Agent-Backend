# app/utils/entity_extractor.py

import re

def extract_account_entity(query: str) -> str | None:
    """
    Extract account/entity name from query.
    First tries regex for patterns like 'account XyzTech_2023',
    then falls back to keyword-based rule extraction.
    """
    # Regex-based approach
    match = re.search(r'\baccount\s+([a-zA-Z0-9_]+)', query, flags=re.IGNORECASE)
    if match:
        return match.group(1)

    # Keyword-based fallback
    keywords = ["Tech", "Bank", "Corp", "Solutions", "Systems", "2023"]
    for word in query.split():
        for key in keywords:
            if key.lower() in word.lower():
                return word

    return None

