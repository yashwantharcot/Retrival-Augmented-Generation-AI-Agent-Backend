"""Optional cross-encoder re-ranking stage.

Environment Flags:
  CROSS_ENCODER_ENABLE=true|false
  CROSS_ENCODER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2 (default)
  CROSS_ENCODER_TOP_N=15        # number of fused candidates to re-rank (<= provided list)
  CROSS_ENCODER_TIMEOUT_MS=1800 # abort if model scoring exceeds this wall time

Behavior:
  - If disabled or model load fails, returns candidates unchanged.
  - Scores query/document pairs with a cross-encoder producing relevance logits.
  - Attaches feature 'cross_score' and resorts by it (descending) while preserving
    previously attached metadata.
  - Falls back (no resort) on timeout.

Dependencies: sentence-transformers (already in requirements). torch is required;
if missing we abort gracefully.
"""
from __future__ import annotations
import os, time, threading
try:
    from .caching import cross_pair_key, cross_cache_get, cross_cache_set
except Exception:
    def cross_pair_key(q,d):
        return q[:16]+d[:16]
    def cross_cache_get(k):
        return None
    def cross_cache_set(k,v):
        return None
from typing import List, Any

# We purposely avoid importing heavy libs at module import time.
_MODEL_SINGLETON = {
    'model': None,
    'failed': False,
    'name': None,
}

DEFAULT_MODEL = 'cross-encoder/ms-marco-MiniLM-L-6-v2'

def _load_model():
    if _MODEL_SINGLETON['model'] or _MODEL_SINGLETON['failed']:
        return _MODEL_SINGLETON['model']
    model_name = os.getenv('CROSS_ENCODER_MODEL', DEFAULT_MODEL)
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        _MODEL_SINGLETON['model'] = CrossEncoder(model_name, trust_remote_code=True)
        _MODEL_SINGLETON['name'] = model_name
    except Exception:
        _MODEL_SINGLETON['failed'] = True
    return _MODEL_SINGLETON['model']


def cross_encoder_enabled() -> bool:
    return os.getenv('CROSS_ENCODER_ENABLE', 'false').lower() == 'true'


def rerank_with_cross_encoder(query: str, candidates: List[Any]):
    """Re-rank candidate objects (fusion_rerank.Candidate) in place.
    Adds c.features['cross_score'] and resorts if scoring succeeds within timeout.
    """
    if not cross_encoder_enabled():
        return {'enabled': False, 'applied': False}
    model = _load_model()
    if model is None:
        return {'enabled': True, 'applied': False, 'reason': 'model_load_failed'}
    if not candidates:
        return {'enabled': True, 'applied': False, 'reason': 'no_candidates'}

    top_n = int(os.getenv('CROSS_ENCODER_TOP_N', '15'))
    timeout_ms = int(os.getenv('CROSS_ENCODER_TIMEOUT_MS', '1800'))
    subset = candidates[:top_n]
    pairs = [(query, c.text) for c in subset]
    scores_holder = {}

    def _score():
        try:
            # Attempt cache retrieval for each pair; only score misses
            scores = []
            misses = []
            miss_indices = []
            for idx,(qtext, dtext) in enumerate(pairs):
                ck = cross_pair_key(qtext, dtext)
                cached = cross_cache_get(ck)
                if cached is not None:
                    scores.append(cached)
                else:
                    scores.append(None)
                    misses.append((qtext, dtext))
                    miss_indices.append(idx)
            if misses:
                new_scores = model.predict(misses)
                for mi, sc in zip(miss_indices, new_scores):
                    scores[mi] = float(sc)
                    # store
                    ck = cross_pair_key(pairs[mi][0], pairs[mi][1])
                    cross_cache_set(ck, float(sc))
            scores_holder['scores'] = [float(s) for s in scores]
        except Exception as e:
            scores_holder['error'] = str(e)

    t0 = time.time()
    thread = threading.Thread(target=_score, daemon=True)
    thread.start()
    thread.join(timeout=timeout_ms / 1000.0)
    duration = (time.time() - t0) * 1000.0

    if thread.is_alive():
        # Timed out; abandon
        return {'enabled': True, 'applied': False, 'reason': 'timeout', 'ms': duration}
    if 'error' in scores_holder or 'scores' not in scores_holder:
        return {'enabled': True, 'applied': False, 'reason': scores_holder.get('error','unknown_error')}

    scores = scores_holder['scores']
    for c, s in zip(subset, scores):
        # Higher score == more relevant (for ms-marco models)
        c.features['cross_score'] = float(s)
    # Shadow mode: don't change order, only log comparison
    shadow = os.getenv('CROSS_ENCODER_SHADOW', 'false').lower() == 'true'
    if shadow:
        try:
            from .audit import log_event
            baseline = [(getattr(c,'id',None), float(c.features.get('linear_score', c.fused_score))) for c in candidates]
            shadow_scores = [(getattr(c,'id',None), float(c.features.get('cross_score', 0.0))) for c in candidates]
            log_event('shadow_rerank', {
                'model': _MODEL_SINGLETON.get('name'),
                'ms': duration,
                'top_n': len(subset),
                'baseline': baseline,
                'cross_scores': shadow_scores,
            })
        except Exception:
            pass
        return {'enabled': True, 'applied': False, 'shadow': True, 'ms': duration, 'top_n': len(subset), 'model': _MODEL_SINGLETON.get('name')}
    # Resort: prioritize cross_score then fallback to prior linear score
    candidates.sort(key=lambda x: (x.features.get('cross_score', -1e9), x.features.get('linear_score', -1e9)), reverse=True)
    return {'enabled': True, 'applied': True, 'ms': duration, 'top_n': len(subset), 'model': _MODEL_SINGLETON.get('name')}

__all__ = ['rerank_with_cross_encoder', 'cross_encoder_enabled']
