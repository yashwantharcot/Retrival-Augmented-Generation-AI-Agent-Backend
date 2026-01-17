"""Feedback capture & adaptive fusion weight nudging.

Features:
  - POST /feedback/click : user clicked a document (implies relevance)
  - POST /feedback/rate  : user rated an answer (thumbs up/down + optional comment)
  - Lightweight adaptive adjustment: accumulate per-source positive signals and
    periodically adjust dynamic weights baseline (does not overwrite auto-calibration, only scales).

Environment:
  FEEDBACK_ENABLE=true|false
  FEEDBACK_NUDGE_INTERVAL=20    (# feedback events before applying scaling)
  FEEDBACK_NUDGE_ALPHA=0.08     (learning rate scaling)

Data Model (Mongo collections):
  feedback_clicks { user_id, query, doc_id, source, ts }
  feedback_ratings { user_id, query, rating(+1/-1), answer_hash, ts, comment }

Adaptive Algorithm:
  Maintain counters pos[source], neg[source] from ratings + clicks (click=positive).
  On interval: effective_gain = (pos - 0.5*neg) / max(1, total_events)
    weight_scale = 1 + alpha * effective_gain (clamped 0.7..1.3)
  Store scale factors in-memory; fusion pipeline multiplies dynamic weight by scale if present.

Integration: fusion_rerank already merges dynamic weights; we inject scale factors by monkey patching
get_fusion_calibrator().get_dynamic_weights to apply scaling (non-invasive) OR expose helper.
Here we implement a helper that fusion_autotune can optionally call if env FEEDBACK_ENABLE.
"""
from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
import os, time, hashlib
from typing import Dict
from app.db.mongo import db
from app.core.fusion_autotune import get_fusion_calibrator

router = APIRouter()

class ClickEvent(BaseModel):
    user_id: str
    query: str
    doc_id: str
    source: str

class RatingEvent(BaseModel):
    user_id: str
    query: str
    rating: int  # +1 / -1
    answer: str
    comment: str | None = None

_feedback_state = {
    'pos': {},  # source -> count
    'neg': {},
    'events': 0,
    'scales': {},
}

def _update_scale_if_needed():
    if os.getenv('FEEDBACK_ENABLE','true').lower() != 'true':
        return
    interval = int(os.getenv('FEEDBACK_NUDGE_INTERVAL','20'))
    alpha = float(os.getenv('FEEDBACK_NUDGE_ALPHA','0.08'))
    if _feedback_state['events'] % interval != 0:
        return
    scales = {}
    for src, pc in _feedback_state['pos'].items():
        nc = _feedback_state['neg'].get(src,0)
        total = pc + nc
        gain = (pc - 0.5*nc) / max(1,total)
        scale = 1 + alpha * gain
        if scale < 0.7: scale = 0.7
        if scale > 1.3: scale = 1.3
        scales[src] = round(scale,4)
    _feedback_state['scales'] = scales

def get_feedback_weight_scales() -> Dict[str,float]:
    return dict(_feedback_state.get('scales') or {})

@router.post('/feedback/click')
async def feedback_click(ev: ClickEvent):
    if os.getenv('FEEDBACK_ENABLE','true').lower() != 'true':
        return {'status':'disabled'}
    db.get_collection('feedback_clicks').insert_one({
        'user_id': ev.user_id,
        'query': ev.query,
        'doc_id': ev.doc_id,
        'source': ev.source,
        'ts': time.time()
    })
    _feedback_state['pos'][ev.source] = _feedback_state['pos'].get(ev.source,0)+1
    _feedback_state['events'] += 1
    _update_scale_if_needed()
    return {'ok': True, 'scales': _feedback_state['scales']}

@router.post('/feedback/rate')
async def feedback_rate(ev: RatingEvent):
    if os.getenv('FEEDBACK_ENABLE','true').lower() != 'true':
        return {'status':'disabled'}
    rating = 1 if ev.rating > 0 else -1
    ahash = hashlib.sha256(ev.answer.encode('utf-8')).hexdigest()[:16]
    db.get_collection('feedback_ratings').insert_one({
        'user_id': ev.user_id,
        'query': ev.query,
        'rating': rating,
        'answer_hash': ahash,
        'comment': ev.comment,
        'ts': time.time()
    })
    target = _feedback_state['pos'] if rating > 0 else _feedback_state['neg']
    target['vector'] = target.get('vector',0) + (1 if rating>0 else 1)  # generic bucket if source unknown
    _feedback_state['events'] += 1
    _update_scale_if_needed()
    return {'ok': True, 'scales': _feedback_state['scales']}

# Hook dynamic weight scaling: monkey patch accessor (safe additive behavior)
orig_get_dynamic = get_fusion_calibrator().get_dynamic_weights
def _patched_get_dynamic():
    base = orig_get_dynamic()
    scales = get_feedback_weight_scales()
    if not scales:
        return base
    out = {}
    for k,v in base.items():
        scale = scales.get(k,1.0)
        out[k] = round(v * scale,4)
    for k,scale in scales.items():
        if k not in out:
            out[k] = scale
    return out
if os.getenv('FEEDBACK_ENABLE','true').lower() == 'true':
    get_fusion_calibrator().get_dynamic_weights = _patched_get_dynamic  # type: ignore

__all__ = ['router','get_feedback_weight_scales']