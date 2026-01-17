"""Ontology & synonym alias boosting utilities.

Loads alias map (primary term -> list[aliases]) and provides helper to compute
boost factors for candidate texts based on presence of preferred canonical terms
or their aliases. Used to modestly adjust fused/linear scores before final ranking.

Env:
  ONTOLOGY_ALIASES_PATH=config/ontology_aliases.json
  ONTOLOGY_BOOST_PER_HIT=0.04
  ONTOLOGY_MAX_BOOST=0.25
"""
from __future__ import annotations
import json, os
from functools import lru_cache
from typing import Dict, List

@lru_cache(maxsize=1)
def load_alias_map() -> Dict[str,List[str]]:
    path = os.getenv('ONTOLOGY_ALIASES_PATH','config/ontology_aliases.json')
    try:
        with open(path,'r',encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {k.lower(): [a.lower() for a in v if isinstance(a,str)] for k,v in data.items()}
    except Exception:
        return {}
    return {}

def expand_alias_map(candidates: Dict[str, list[str]] | None = None) -> bool:
    """Append new aliases into ontology file from provided candidates.

    candidates: mapping canonical -> list of alias strings
    Returns True if file updated, else False.
    """
    path = os.getenv('ONTOLOGY_ALIASES_PATH','config/ontology_aliases.json')
    try:
        current = load_alias_map() or {}
        updated: Dict[str, List[str]] = {k: list(set(v)) for k,v in current.items()}
        if candidates:
            for canon, alias_list in candidates.items():
                canon_l = str(canon or '').lower().strip()
                if not canon_l:
                    continue
                al = [a.lower().strip() for a in alias_list if isinstance(a,str) and a.strip()]
                if not al:
                    continue
                merged = set(updated.get(canon_l, [])) | set(al)
                updated[canon_l] = sorted(merged)
        # Only write if changed
        if updated != current:
            # refresh cache after write
            with open(path,'w',encoding='utf-8') as f:
                json.dump(updated, f, ensure_ascii=False, indent=2)
            load_alias_map.cache_clear()  # type: ignore
            return True
    except Exception:
        return False
    return False

def ontology_boost(query: str, text: str) -> float:
    aliases = load_alias_map()
    if not aliases:
        return 0.0
    ql = query.lower()
    tl = text.lower()
    per_hit = float(os.getenv('ONTOLOGY_BOOST_PER_HIT','0.04'))
    max_boost = float(os.getenv('ONTOLOGY_MAX_BOOST','0.25'))
    boost = 0.0
    # If canonical term in query -> boost docs containing any alias
    for canonical, alias_list in aliases.items():
        if canonical in ql:
            for a in alias_list:
                if a in tl:
                    boost += per_hit
        else:
            # if alias appears in query and canonical appears in doc
            if any(a in ql for a in alias_list) and canonical in tl:
                boost += per_hit
        if boost >= max_boost:
            break
    if boost > max_boost:
        boost = max_boost
    return boost

__all__ = ['ontology_boost','load_alias_map','expand_alias_map']