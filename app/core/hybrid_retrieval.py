"""Hybrid retrieval scaffolding.

Current Status:
- Provides a placeholder BM25-like lexical fetch using simple term frequency over existing vector results.
- Wraps fusion logic (vector + pseudo-lexical) via hybrid_rank from fusion_rerank.
- Designed to be swapped out with real BM25 (OpenSearch / Elastic) later without changing caller code.

Environment Flags:
  HYBRID_RETRIEVAL_ENABLE=true      -> activates hybrid path in main query endpoint
  HYBRID_LEXICAL_DEPTH=60           -> depth for pseudo lexical layer
  HYBRID_VECTOR_DEPTH=60            -> depth for vector retrieval

Future TODO:
- Replace _pseudo_lexical_fetch with real BM25 client integration.
- Add third source (activities) and a recency source.
- Persist feature vectors for offline analysis.
"""
from __future__ import annotations
from typing import List, Dict, Optional, Any
import os, time, concurrent.futures
from .fusion_rerank import hybrid_rank, rrf_fuse, attach_features, linear_rerank
try:
    from .caching import hybrid_key, hybrid_cache_get, hybrid_cache_set
except Exception:
    def hybrid_key(q,p): return q
    def hybrid_cache_get(k): return None
    def hybrid_cache_set(k,v): return None
from .lexical_client import get_lexical_client
from .fusion_autotune import get_fusion_calibrator
from .cross_encoder_reranker import rerank_with_cross_encoder, cross_encoder_enabled
try:
    from .audit import log_event
except Exception:
    def log_event(*args, **kwargs):
        return None
try:
    from app.memory.memory_manager import get_query_history
except Exception:
    def get_query_history(session_id: str, limit: int = 5):
        return []

# Contract expected of retriever: retriever.retrieve(query, k, preferences) -> list[dict]

def _results_to_scored_docs(results: List[Dict]) -> List[Dict]:
    scored = []
    for r in results:
        text = r.get('chunk') or r.get('text') or ''
        rid = str(r.get('id') or r.get('_id') or len(scored))
        scored.append({
            'id': rid,
            'score': float(r.get('score', 0.0) or 0.0),
            'text': text,
            'metadata': r.get('metadata') or {}
        })
    return scored

def _pseudo_lexical_fetch(query: str, base_results: List[Dict], depth: int) -> List[Dict]:
    terms = [t for t in query.lower().split() if len(t) > 2]
    docs = []
    for r in base_results[:depth]:
        txt = (r.get('chunk') or r.get('text') or '').lower()
        if not txt:
            continue
        hits = sum(txt.count(t) for t in terms) or 0
        if hits == 0:
            # still keep with minimal score to allow fusion diversity
            hits = 0.1
        docs.append({
            'id': str(r.get('id') or r.get('_id') or len(docs)),
            'score': float(hits),
            'text': r.get('chunk') or r.get('text') or '',
            'metadata': r.get('metadata') or {}
        })
    # Sort descending by pseudo lexical score
    docs.sort(key=lambda d: d['score'], reverse=True)
    return docs

def hybrid_retrieve(query: str, retriever, preferences=None, k: int = 25, meta: Optional[Dict]=None, structured_filters: Optional[Dict[str, Any]] = None, metadata_filter: Optional[Dict[str, Any]] = None) -> List[Dict]:
    """Run hybrid (vector + lexical) retrieval with optional parallelism and timing.

    Args:
      query: user query
      retriever: primary vector retriever instance
      preferences: preference dict
      k: number of final fused docs
      meta: optional dict to populate with timing + stage info
    Returns list of RAG-ready dicts (id, chunk, score, metadata)
    """
    meta = meta if meta is not None else {}
    t_start = time.perf_counter()
    vec_depth = int(os.getenv('HYBRID_VECTOR_DEPTH', '60'))
    lex_depth = int(os.getenv('HYBRID_LEXICAL_DEPTH', '60'))
    parallel = os.getenv('HYBRID_PARALLEL_ENABLE','true').lower() == 'true'
    lexical_client = get_lexical_client()
    # Extract metadata filter string (user-level) potentially inside preferences
    if preferences and isinstance(preferences, dict) and metadata_filter is None:
        mfil = preferences.get('metadataFilter') or preferences.get('metadata_filter')
        if isinstance(mfil, str) and mfil.strip():
            metadata_filter = mfil  # retriever will parse if string

    cache_sig = hybrid_key(query, preferences)
    cached = hybrid_cache_get(cache_sig)
    if cached:
        meta['cache'] = 'hit'
        return cached[:k]
    raw_vector = []
    lexical_docs_raw = []
    t_vec0 = t_lex0 = None
    # Strategy: if lexical client enabled & parallel flag -> run both in thread pool
    if lexical_client.enabled and parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_vec = ex.submit(lambda: retriever.retrieve(query, k=vec_depth, preferences=preferences, metadata_filter=metadata_filter) or [])
            f_lex = ex.submit(lambda: lexical_client.search(query, k=lex_depth, filters=structured_filters) or [])
            t_vec0 = time.perf_counter(); raw_vector = f_vec.result(); t_vec1 = time.perf_counter()
            t_lex0 = time.perf_counter();
            try:
                lexical_docs_raw = f_lex.result()
            except Exception:
                lexical_docs_raw = []
            t_lex1 = time.perf_counter()
    else:
        # Sequential path
        t_vec0 = time.perf_counter(); raw_vector = retriever.retrieve(query, k=vec_depth, preferences=preferences, metadata_filter=metadata_filter) or []; t_vec1 = time.perf_counter()
        if lexical_client.enabled:
            try:
                t_lex0 = time.perf_counter(); lexical_docs_raw = lexical_client.search(query, k=lex_depth, filters=structured_filters) or []; t_lex1 = time.perf_counter()
            except Exception:
                lexical_docs_raw = []
                t_lex1 = time.perf_counter()
        else:
            lexical_docs_raw = []
            t_lex0 = t_lex1 = None

    # Fallback pseudo lexical if needed
    if not lexical_docs_raw:
        lexical_docs_raw = _pseudo_lexical_fetch(query, raw_vector, lex_depth)

    vector_docs = _results_to_scored_docs(raw_vector)
    lexical_docs = lexical_docs_raw  # already in scored doc shape from client

    # Optional: session memory as an extra source (lightweight scoring)
    extra_sources = {}
    if os.getenv('HYBRID_MEMORY_SOURCE','true').lower() == 'true' and isinstance(preferences, dict):
        sid = preferences.get('sessionId') or preferences.get('session_id')
        if sid:
            try:
                hist = get_query_history(sid, limit=int(os.getenv('HYBRID_MEMORY_SOURCE_DEPTH','8'))) or []
                mem_docs = []
                q_terms = [t for t in query.lower().split() if len(t) > 2]
                for i, h in enumerate(hist):
                    txt = (h.get('query') or '')
                    if not txt:
                        continue
                    score = sum(txt.lower().count(t) for t in q_terms) or 0.1
                    mem_docs.append({'id': f"mem_{i}", 'score': float(score), 'text': txt, 'metadata': {'source':'session_query','created_at': h.get('created_at')}})
                if mem_docs:
                    extra_sources['memory'] = mem_docs
            except Exception:
                pass

    # Auto-calibration dynamic weights are merged inside hybrid_rank (static * dynamic scaling)
    fused = hybrid_rank(query, bm25_fetch=lambda q,_: lexical_docs, vector_fetch=lambda q,_: vector_docs, k=k, extra_sources=extra_sources if extra_sources else None)
    cross_meta = None
    if cross_encoder_enabled():
        try:
            cross_meta = rerank_with_cross_encoder(query, fused)
        except Exception as e:
            cross_meta = {"enabled": True, "applied": False, "error": str(e)}
    # Record calibration stats (full candidate list before truncation would be ideal; we only have truncated top-k now)
    try:
        get_fusion_calibrator().record(fused)
    except Exception:
        pass
    # Map back to RAG expected structure
    out = []
    for c in fused:
        meta_c = {**(c.metadata or {}), 'fusion_source': c.source, 'fusion_fused_score': c.fused_score}
        if 'cross_score' in c.features:
            meta_c['cross_score'] = c.features['cross_score']
        if cross_meta and meta_c.get('_fusion_weights') and cross_meta.get('applied'):
            meta_c['cross_encoder_model'] = cross_meta.get('model')
            meta_c['cross_encoder_ms'] = cross_meta.get('ms')
        out.append({
            'id': c.id,
            'chunk': c.text,
            'score': c.features.get('cross_score') or c.features.get('linear_score', c.fused_score),
            'metadata': meta_c
        })
    # Populate timing meta
    if t_vec0 is not None:
        meta['vector_ms'] = round((t_vec1 - t_vec0)*1000,2)
    if t_lex0 is not None:
        meta['lexical_ms'] = round((t_lex1 - t_lex0)*1000,2)
    meta['parallel'] = parallel and lexical_client.enabled
    if cross_meta:
        meta['cross_encoder'] = cross_meta
    meta['total_ms'] = round((time.perf_counter()-t_start)*1000,2)
    # Audit log snapshot (non-blocking)
    try:
        log_event('hybrid_retrieve', {
            'k': k,
            'vector_count': len(vector_docs),
            'lexical_count': len(lexical_docs),
            'extra_sources': list(extra_sources.keys()) if extra_sources else [],
            'timings': {k2:v for k2,v in meta.items() if k2.endswith('_ms')},
        })
    except Exception:
        pass
    hybrid_cache_set(cache_sig, out)
    return out

def hybrid_diagnostics(query: str, retriever, preferences=None, k: int = 25, vec_depth: int | None = None, lex_depth: int | None = None) -> Dict:
    """Return detailed hybrid retrieval diagnostic artifacts.

    Includes raw vector docs, lexical docs, fused candidates with feature vectors,
    and (if enabled) cross-encoder scores.
    """
    vec_depth = vec_depth or int(os.getenv('HYBRID_VECTOR_DEPTH', '60'))
    lex_depth = lex_depth or int(os.getenv('HYBRID_LEXICAL_DEPTH', '60'))
    lexical_client = get_lexical_client()
    # Raw vector
    raw_vector = retriever.retrieve(query, k=vec_depth, preferences=preferences) or []
    vector_docs = _results_to_scored_docs(raw_vector)
    # Raw lexical
    if lexical_client.enabled:
        try:
            lexical_docs = lexical_client.search(query, k=lex_depth) or []
        except Exception:
            lexical_docs = _pseudo_lexical_fetch(query, raw_vector, lex_depth)
    else:
        lexical_docs = _pseudo_lexical_fetch(query, raw_vector, lex_depth)
    # Fused (manual to capture full feature state)
    fused = hybrid_rank(query, bm25_fetch=lambda q,_: lexical_docs, vector_fetch=lambda q,_: vector_docs, k=k)
    cross_meta = None
    if cross_encoder_enabled():
        try:
            cross_meta = rerank_with_cross_encoder(query, fused)
        except Exception as e:
            cross_meta = {"enabled": True, "applied": False, "error": str(e)}
    fused_serialized = []
    for c in fused:
        fused_serialized.append({
            'id': c.id,
            'source': c.source,
            'text_preview': c.text[:160],
            'fused_score': c.fused_score,
            'features': {k: v for k,v in c.features.items() if isinstance(v,(int,float))},
            'metadata_keys': list((c.metadata or {}).keys())
        })
    return {
        'vector_docs': [{'id': d['id'], 'score': d['score'], 'text_preview': d['text'][:160]} for d in vector_docs[:k]],
        'lexical_docs': [{'id': d['id'], 'score': d['score'], 'text_preview': d['text'][:160]} for d in lexical_docs[:k]],
        'fused': fused_serialized,
        'cross_encoder': cross_meta
    }

try:
    __all__  # type: ignore
except NameError:  # pragma: no cover
    __all__ = []  # type: ignore
__all__.append('hybrid_diagnostics')
