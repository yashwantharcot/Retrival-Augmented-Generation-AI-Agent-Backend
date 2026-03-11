import os
from datetime import datetime
from typing import Dict, Optional
from pymongo import MongoClient
from functools import lru_cache

_mongo_uri = os.getenv("MONGODB_URI")
_client = None
_db = None
_collection = None

try:
    _client = MongoClient(_mongo_uri, serverSelectionTimeoutMS=5000)
    _db = _client[os.getenv("MONGODB_DB", "dev_db")]
    _collection = _db["user_preferences"]
except Exception as e:
    print(f"[WARNING] MongoDB connection failed in db/user_preferences.py: {e}")


_CACHE_TTL_SECONDS = int(os.getenv("USER_PREF_CACHE_TTL", "300"))
_in_memory_cache: Dict[str, Dict] = {}
_in_memory_cache_time: Dict[str, float] = {}

def _is_fresh(ts: float) -> bool:
    import time
    return (time.time() - ts) < _CACHE_TTL_SECONDS

def get_user_preferences(user_id: str) -> Dict:
    if not user_id:
        return {}
    import time
    ts = _in_memory_cache_time.get(user_id)
    if ts and _is_fresh(ts):
        return _in_memory_cache.get(user_id, {})
    doc = _collection.find_one({"user_id": user_id}, {"_id": 0})
    prefs = doc.get("preferences", {}) if doc else {}
    _in_memory_cache[user_id] = prefs
    _in_memory_cache_time[user_id] = time.time()
    return prefs


def upsert_user_preferences(user_id: str, new_prefs: Dict, mode: str = "merge") -> Dict:
    if not user_id:
        return {}
    now = datetime.utcnow()
    existing = _collection.find_one({"user_id": user_id})
    if existing:
        if mode == "replace":
            merged = new_prefs or {}
        else:
            merged = {**(existing.get("preferences", {})), **(new_prefs or {})}
        version = existing.get("version", 1) + 1 if merged != existing.get("preferences", {}) else existing.get("version", 1)
        _collection.update_one(
            {"user_id": user_id},
            {"$set": {"preferences": merged, "updated_at": now, "version": version}}
        )
    else:
        merged = new_prefs or {}
        _collection.insert_one({
            "user_id": user_id,
            "preferences": merged,
            "created_at": now,
            "updated_at": now,
            "version": 1
        })
    # Invalidate cache
    if user_id in _in_memory_cache:
        del _in_memory_cache[user_id]
        _in_memory_cache_time.pop(user_id, None)
    return merged


def preference_diff(old: Dict, new: Dict) -> Dict:
    diff = {}
    for k, v in (new or {}).items():
        if old.get(k) != v:
            diff[k] = {"old": old.get(k), "new": v}
    return diff

# ================= Automated Feedback → Preference Tuning =================== #
def auto_tune_preferences(user_id: str, feedback: str, recent_query: str | None = None) -> Dict:
    """Lightweight heuristic updates to preferences based on thumbs feedback.

    Rules (initial simple version):
      - Negative feedback and answer was long: decrease detailLevel (if high/deep -> medium, medium -> low)
      - Positive feedback and answer was short: increase detailLevel (low->medium, medium->high)
      - Negative feedback with keywords like 'format' or 'structure': switch responseStyle to 'bullets'
      - Positive feedback with 'table' or 'summary': set responseStyle accordingly
    """
    if feedback not in ("up","down"):
        return get_user_preferences(user_id)
    prefs = get_user_preferences(user_id) or {}
    changed = False
    dl = prefs.get("detailLevel") or prefs.get("detaillevel") or "medium"
    style = prefs.get("responseStyle") or prefs.get("responsestyle") or "default"
    rq_low = (recent_query or "").lower()
    if feedback == "down":
        if dl in ("deep","high"):
            prefs["detailLevel"] = "medium"; changed = True
        elif dl == "medium":
            prefs["detailLevel"] = "low"; changed = True
        if any(k in rq_low for k in ["format","structure","bullets"]):
            if style != "bullets":
                prefs["responseStyle"] = "bullets"; changed = True
    else:  # up
        if dl == "low":
            prefs["detailLevel"] = "medium"; changed = True
        elif dl == "medium":
            prefs["detailLevel"] = "high"; changed = True
        if any(k in rq_low for k in ["table","summary"]):
            target = "table" if "table" in rq_low else "summary"
            if style != target:
                prefs["responseStyle"] = target; changed = True
    if changed:
        upsert_user_preferences(user_id, prefs, mode="merge")
    return prefs
