"""Lexical search client abstraction (BM25 via OpenSearch / Elastic) with synonym expansion.

Environment Variables:
  LEXICAL_ENABLE=true                   Enable lexical layer (else fallback to pseudo lexical)
  LEXICAL_ENDPOINT=http://localhost:9200  Base URL
  LEXICAL_INDEX=dealdox_quotes_search   Index name
  LEXICAL_USERNAME=... (optional basic auth)
  LEXICAL_PASSWORD=... (optional basic auth)
  LEXICAL_API_KEY=...  (alternative auth header)
  LEXICAL_SEARCH_FIELDS=account_name,opportunity_name,line_items_summary,chunk_text
  LEXICAL_TIMEOUT_SECS=3
  LEXICAL_SYNONYMS_PATH=config/lexical_synonyms.json
  LEXICAL_SYNONYM_EXPAND_MAX=2   Max terms to expand (avoid query blowup)

Returned document contract:
  { 'id': str, 'score': float, 'text': str, 'metadata': {...} }

Notes:
- If OpenSearch/Elastic client import fails or request errors, returns empty list (caller should fallback).
- Only minimal error handling to keep fast path; heavy logging suppressed unless RAG_DEBUG.
"""
from __future__ import annotations
from typing import List, Dict, Any
import os, json, time

try:
    # Prefer opensearch; fallback to elasticsearch client naming
    from opensearchpy import OpenSearch  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    try:
        from elasticsearch import Elasticsearch as OpenSearch  # type: ignore
    except Exception:  # pragma: no cover
        OpenSearch = None  # type: ignore

_synonyms_cache = None


def _load_synonyms(path: str):
    global _synonyms_cache
    if _synonyms_cache is not None:
        return _synonyms_cache
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                _synonyms_cache = data
            else:
                _synonyms_cache = {}
    except Exception:
        _synonyms_cache = {}
    return _synonyms_cache


def _expand_query_with_synonyms(query: str) -> str:
    path = os.getenv("LEXICAL_SYNONYMS_PATH", "config/lexical_synonyms.json")
    syns = _load_synonyms(path)
    if not syns:
        return query
    tokens = [t for t in query.split() if t.isalpha()]
    max_expand = int(os.getenv("LEXICAL_SYNONYM_EXPAND_MAX", "2"))
    expansions = []
    for t in tokens:
        ls = syns.get(t.lower())
        if ls:
            expansions.extend(ls[:max_expand])
    if not expansions:
        return query
    # Simple OR style expansion appended
    return query + " " + " ".join(set(expansions))


class LexicalClient:
    def __init__(self):
        self.enabled = os.getenv("LEXICAL_ENABLE", "false").lower() == "true"
        self.endpoint = os.getenv("LEXICAL_ENDPOINT")
        self.index = os.getenv("LEXICAL_INDEX", "dealdox_quotes_search")
        self.timeout = int(os.getenv("LEXICAL_TIMEOUT_SECS", "3"))
        self.client = None
        if self.enabled and OpenSearch:
            auth_kwargs = {}
            user = os.getenv("LEXICAL_USERNAME")
            pwd = os.getenv("LEXICAL_PASSWORD")
            api_key = os.getenv("LEXICAL_API_KEY")
            try:
                if api_key:
                    auth_kwargs['api_key'] = api_key
                elif user and pwd:
                    auth_kwargs['http_auth'] = (user, pwd)
                self.client = OpenSearch(hosts=[self.endpoint], timeout=self.timeout, **auth_kwargs)
            except Exception:
                self.client = None
                self.enabled = False
    def search(self, query: str, k: int = 50, filters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        """Execute lexical search with optional structured filters.

        filters contract (subset supported):
          owner_regex: str (case-insensitive phrase match on owner field)
          stage_regex: str
          amount_min / amount_max: float range on amount
          date_from / date_to: ISO date strings (applied to date or created_at)
          raw_metadata: dict -> additional term/range clauses already in ES syntax (advanced hook)
        """
        if not (self.enabled and self.client and self.endpoint):
            return []
        q_expanded = _expand_query_with_synonyms(query)
        fields = [f.strip() for f in os.getenv("LEXICAL_SEARCH_FIELDS", "account_name,opportunity_name,line_items_summary,chunk_text").split(',') if f.strip()]

        bool_filters: List[Dict[str, Any]] = []
        if filters and isinstance(filters, dict):
            try:
                # Owner / stage phrase matches
                if filters.get('owner_regex'):
                    bool_filters.append({"match_phrase": {"owner": filters['owner_regex']}})
                if filters.get('stage_regex'):
                    bool_filters.append({"match_phrase": {"stage": filters['stage_regex']}})
                # Amount range
                amt_range = {}
                if filters.get('amount_min') is not None:
                    amt_range['gte'] = float(filters['amount_min'])
                if filters.get('amount_max') is not None:
                    amt_range['lte'] = float(filters['amount_max'])
                if amt_range:
                    bool_filters.append({"range": {"amount": amt_range}})
                # Date range (try date or created_at using should OR)
                date_range = {}
                if filters.get('date_from'):
                    date_range['gte'] = filters['date_from']
                if filters.get('date_to'):
                    date_range['lte'] = filters['date_to']
                if date_range:
                    bool_filters.append({
                        "bool": {
                            "should": [
                                {"range": {"date": date_range}},
                                {"range": {"created_at": date_range}},
                                {"range": {"createdAt": date_range}}
                            ],
                            "minimum_should_match": 1
                        }
                    })
                # Advanced raw metadata passthrough
                raw_meta = filters.get('raw_metadata')
                if isinstance(raw_meta, list):
                    for clause in raw_meta:
                        if isinstance(clause, dict):
                            bool_filters.append(clause)
            except Exception:
                # Swallow filter build issues (fail open)
                bool_filters = []

        # Build bool query
        multi_match = {
            "multi_match": {
                "query": q_expanded,
                "fields": fields,
                "type": "best_fields",
                "operator": "or"
            }
        }
        if bool_filters:
            query_body: Dict[str, Any] = {"bool": {"must": [multi_match], "filter": bool_filters}}
        else:
            query_body = multi_match
        body = {"size": k, "query": query_body}
        try:
            t0 = time.perf_counter()
            res = self.client.search(index=self.index, body=body, request_timeout=self.timeout)
            took_ms = round((time.perf_counter() - t0)*1000,2)
            hits = res.get('hits', {}).get('hits', [])
            out = []
            for h in hits:
                src = h.get('_source', {}) or {}
                doc_id = h.get('_id') or src.get('id') or src.get('_id') or ''
                text = src.get('summary') or src.get('line_items_summary') or src.get('description') or ''
                out.append({
                    'id': str(doc_id),
                    'score': float(h.get('_score') or 0.0),
                    'text': text,
                    'metadata': {'lexical_took_ms': took_ms, 'fields': fields, 'filters_applied': bool(bool_filters)}
                })
            return out
        except Exception:
            return []

# Singleton access
_lexical_client_singleton: LexicalClient | None = None

def get_lexical_client() -> LexicalClient:
    global _lexical_client_singleton
    if _lexical_client_singleton is None:
        _lexical_client_singleton = LexicalClient()
    return _lexical_client_singleton
