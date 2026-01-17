"""Lightweight in-process caching utilities (LRU) for intent, cross-encoder, rerank.

Environment:
  CACHE_INTENT_SIZE=512
  CACHE_CROSS_ENCODER_SIZE=512
  CACHE_HYBRID_RESULT_SIZE=256 (vector+lexical fused intermediate for identical query hash + prefs signature)
"""
from __future__ import annotations
from collections import OrderedDict
import hashlib, json, os, time
from typing import Any, Tuple

class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.store: OrderedDict[str, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0
    def get(self, key: str):
        if key in self.store:
            self.store.move_to_end(key)
            self.hits += 1
            return self.store[key]
        self.misses += 1
        return None
    def set(self, key: str, value: Any):
        if self.capacity <= 0:
            return
        self.store[key] = value
        self.store.move_to_end(key)
        if len(self.store) > self.capacity:
            self.store.popitem(last=False)
    def stats(self):
        total = self.hits + self.misses
        hit_rate = (self.hits/total) if total else 0.0
        return {"capacity": self.capacity, "size": len(self.store), "hits": self.hits, "misses": self.misses, "hit_rate": round(hit_rate,3)}

_intent_cache = LRUCache(int(os.getenv('CACHE_INTENT_SIZE','512')))
_cross_cache = LRUCache(int(os.getenv('CACHE_CROSS_ENCODER_SIZE','512')))
_hybrid_cache = LRUCache(int(os.getenv('CACHE_HYBRID_RESULT_SIZE','256')))

def intent_cache_get(q: str):
    return _intent_cache.get(q.strip().lower())
def intent_cache_set(q: str, val):
    _intent_cache.set(q.strip().lower(), val)

def cross_pair_key(query: str, doc_text: str) -> str:
    h = hashlib.sha256()
    for part in (query, doc_text[:400]):
        h.update(part.encode('utf-8'))
    return h.hexdigest()[:32]
def cross_cache_get(key: str):
    return _cross_cache.get(key)
def cross_cache_set(key: str, val):
    _cross_cache.set(key, val)

def hybrid_key(query: str, prefs) -> str:
    sig = json.dumps(prefs or {}, sort_keys=True)
    return hashlib.sha1((query+'|'+sig).encode('utf-8')).hexdigest()[:32]
def hybrid_cache_get(key: str):
    return _hybrid_cache.get(key)
def hybrid_cache_set(key: str, val):
    _hybrid_cache.set(key, val)

def cache_diagnostics():
    return {
        'intent': _intent_cache.stats(),
        'cross_encoder': _cross_cache.stats(),
        'hybrid_results': _hybrid_cache.stats()
    }

__all__ = [
    'intent_cache_get','intent_cache_set',
    'cross_pair_key','cross_cache_get','cross_cache_set',
    'hybrid_key','hybrid_cache_get','hybrid_cache_set','cache_diagnostics'
]