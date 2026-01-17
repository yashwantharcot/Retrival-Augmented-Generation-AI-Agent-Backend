"""Lightweight in-memory diagnostics collection for retrieval pipeline.

Stores recent hybrid retrieval timing + cross-encoder meta to power a diagnostics endpoint.

Env:
  DIAG_RETRIEVAL_BUFFER (int) default 120  - ring buffer size

Functions:
  record_retrieval_metrics(meta: dict) -> None
  get_retrieval_metrics() -> dict
"""
from __future__ import annotations
from collections import deque
from typing import Deque, Dict, Any, List
import os, time

_BUFFER: Deque[Dict[str, Any]] | None = None

def _get_buffer() -> Deque[Dict[str, Any]]:
    global _BUFFER
    if _BUFFER is None:
        size = int(os.getenv("DIAG_RETRIEVAL_BUFFER", "120"))
        _BUFFER = deque(maxlen=size)
    return _BUFFER

def record_retrieval_metrics(meta: Dict[str, Any] | None):
    if not meta:
        return
    buf = _get_buffer()
    entry = dict(meta)
    entry['ts'] = time.time()
    buf.append(entry)

def get_retrieval_metrics() -> Dict[str, Any]:
    buf = _get_buffer()
    items: List[Dict[str, Any]] = list(buf)
    if not items:
        return {"count": 0, "entries": [], "averages": {}}
    # Aggregate numeric fields
    num_fields = [
        'vector_ms','lexical_ms','total_ms'
    ]
    sums = {f: 0.0 for f in num_fields}
    counts = {f: 0 for f in num_fields}
    cross_applied = 0
    cross_total_ms = 0.0
    parallel_true = 0
    for it in items:
        for f in num_fields:
            if isinstance(it.get(f), (int,float)):
                sums[f] += float(it[f]); counts[f] += 1
        ce = it.get('cross_encoder') or {}
        if ce.get('applied'):
            cross_applied += 1
            if isinstance(ce.get('ms'), (int,float)):
                cross_total_ms += float(ce['ms'])
        if it.get('parallel'):
            parallel_true += 1
    avgs = {f: round(sums[f]/counts[f],2) if counts[f] else None for f in num_fields}
    avgs['cross_applied_rate'] = round(cross_applied/len(items),3)
    avgs['cross_avg_ms'] = round(cross_total_ms/max(1,cross_applied),2) if cross_applied else None
    avgs['parallel_rate'] = round(parallel_true/len(items),3)
    return {
        "count": len(items),
        "buffer_max": _get_buffer().maxlen,
        "averages": avgs,
        "last": items[-5:]  # last few samples for quick inspection
    }

__all__ = ["record_retrieval_metrics", "get_retrieval_metrics"]
