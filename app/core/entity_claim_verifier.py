"""Entity & claim verification scaffold.

Purpose:
  Extract named entities (orgs, people, products) and key factual claims from an LLM answer
  then cross-check grounding within provided context blocks.

Current Implementation (lightweight heuristic):
  - Simple regex / pattern extraction for entities (capitalized multi-word spans) and numeric-year claims.
  - For each entity, verify at least one context block contains the entity (case-insensitive)
  - For each year claim (YYYY) ensure appears in some context block; otherwise mark ungrounded.

Metrics exposed:
  entity_total, entity_grounded, entity_ungrounded
  year_total, year_grounded, year_ungrounded

Future Extensions:
  - Integrate spaCy / transformer NER when available
  - Relationship / comparison claim validation
  - Confidence scoring & hallucination risk estimate
  - Provide grounding snippets for UI highlighting
"""
from __future__ import annotations
import re
from typing import List, Dict

ENTITY_PATTERN = re.compile(r'\b([A-Z][A-Za-z0-9&]+(?:\s+[A-Z][A-Za-z0-9&]+){0,3})\b')
YEAR_PATTERN = re.compile(r'\b(20\d{2}|19\d{2})\b')

def verify_entities_and_claims(answer: str, context_blocks: List[str]) -> Dict[str, int]:
    if not answer:
        return {}
    ctx_join = '\n'.join(context_blocks or [])
    ctx_lower = ctx_join.lower()
    entities = []
    for m in ENTITY_PATTERN.finditer(answer):
        span = m.group(1).strip()
        # filter out very short common words
        if len(span) < 3:
            continue
        if span.lower() in {"the","and","for","with","from"}:
            continue
        entities.append(span)
    # Deduplicate
    entities = list(dict.fromkeys(entities))
    years = list(dict.fromkeys(YEAR_PATTERN.findall(answer)))

    grounded_entities = 0
    for e in entities:
        if e.lower() in ctx_lower:
            grounded_entities += 1
    grounded_years = 0
    for y in years:
        if y in ctx_join:
            grounded_years += 1
    return {
        'entity_total': len(entities),
        'entity_grounded': grounded_entities,
        'entity_ungrounded': len(entities) - grounded_entities,
        'year_total': len(years),
        'year_grounded': grounded_years,
        'year_ungrounded': len(years) - grounded_years
    }

__all__ = ['verify_entities_and_claims']