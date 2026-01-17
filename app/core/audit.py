"""Lightweight audit logger for retrieval/ranking decisions.

Env:
  AUDIT_LOG_ENABLE=true|false
  AUDIT_LOG_PATH=logs/retrieval_audit.jsonl
"""
from __future__ import annotations
import os, json, time
from typing import Any, Dict

_LOG_PATH = os.getenv('AUDIT_LOG_PATH', 'logs/retrieval_audit.jsonl')

def _ensure_dir(path: str):
    try:
        d = os.path.dirname(path)
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
    except Exception:
        pass

def audit_enabled() -> bool:
    return os.getenv('AUDIT_LOG_ENABLE', 'false').lower() == 'true'

def log_event(event_type: str, payload: Dict[str, Any]):
    if not audit_enabled():
        return
    _ensure_dir(_LOG_PATH)
    rec = {
        'ts': time.time(),
        'type': event_type,
        **payload
    }
    try:
        with open(_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        # Swallow failures; audit must not break core flow
        pass

__all__ = ['log_event','audit_enabled']
