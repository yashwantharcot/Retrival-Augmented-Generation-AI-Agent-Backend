import re
#import spacy
import logging


# ----------------------------------
# 🟡 1. Specific Rule-Based Function
# ----------------------------------
from typing import Optional

def extract_account_name(query: str) -> Optional[str]:

    match = re.search(r'account\s+(\w+)', query.lower())
    if match:
        
        return match.group(1)
    return None

# ----------------------------------
# 🟡 2. General Rule-Based Entity Extractor
# ----------------------------------
from typing import Optional

def extract_entity(query: str) -> Optional[str]:

    match = re.search(r'\b([A-Z][a-zA-Z0-9& ]+)\b', query)
    if match:
        entity = match.group(1).strip()
        
        return entity
    return None
