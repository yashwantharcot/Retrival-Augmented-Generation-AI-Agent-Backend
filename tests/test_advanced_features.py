import os
import types
import pytest

from app.main import (
    _adaptive_requery_if_sparse,
    _multi_pass_cluster_summarize,
    _compute_hallucination_metrics,
    align_answer_with_context,
)
from app.core.retriever import Retriever
from app.db import user_preferences as up

# ---------- Helpers ---------- #
class FakeCollection:
    def __init__(self, prefs_map=None):
        self.docs = []
        self._store = {}

    def find_one(self, query, projection=None):
        return self._store.get(query.get("user_id"))

    def update_one(self, query, update, upsert=False):
        uid = query.get("user_id")
        existing = self._store.get(uid, {"user_id": uid, "preferences": {}, "version":1})
        prefs = existing.get("preferences", {})
        if "$set" in update:
            new_prefs = update["$set"].get("preferences", prefs)
            existing.update({"preferences": new_prefs, **update["$set"]})
        self._store[uid] = existing

    def insert_one(self, doc):
        self._store[doc["user_id"]] = doc

    def distinct(self, field):
        # Simulate metadata distinct values
        if field.endswith("industry"):
            return ["Healthcare", "Technology", "Finance"]
        if field.endswith("region"):
            return ["EMEA", "APAC", "NA"]
        return []


class FakeRetriever:
    def __init__(self, extra_results):
        self.extra_results = extra_results
    def retrieve(self, query, k=20, preferences=None):
        # Return extra results if expansion terms appended
        if "insights metrics" in query:
            return self.extra_results
        return []

# Monkeypatch the user preference collection
@pytest.fixture(autouse=True)
def patch_user_pref_collection(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr(up, "_collection", fake)
    # Clear caches
    up._in_memory_cache.clear()
    up._in_memory_cache_time.clear()
    yield

# ---------- Tests ---------- #

def test_preference_rerank_basic():
    # Prepare retriever with preference rerank private method
    r = Retriever(openai_collection=None, gemini_collection=None, openai_index="x", gemini_index="y")
    # Fabricate results
    results = [
        {"chunk": "Premium revenue grew strongly in APAC region", "score": 0.7, "metadata": {"region": "APAC"}},
        {"chunk": "Legacy costs impacted gross margin", "score": 0.75, "metadata": {"region": "NA"}},
    ]
    prefs = {"boostKeywords": "revenue,margin", "demoteKeywords": "legacy", "focusRegions": "APAC"}
    reranked = r._apply_preference_rerank(results, prefs)
    # Expect APAC revenue doc boosted above legacy cost doc
    assert reranked[0]["chunk"].startswith("Premium revenue"), "Preference re-rank did not boost expected chunk"


def test_auto_tune_preferences_adjusts_detail(monkeypatch):
    # Seed prefs
    up.upsert_user_preferences("u1", {"detailLevel": "high", "responseStyle": "default"})
    from app.db.user_preferences import auto_tune_preferences
    tuned = auto_tune_preferences("u1", "down", recent_query="format please")
    assert tuned.get("detailLevel") in ("medium", "medium"), "Detail level not reduced"
    assert tuned.get("responseStyle") == "bullets", "Style not switched to bullets on format feedback"


def test_align_answer_with_context_and_metrics():
    answer = "Revenue increased. Novel biotech discovery. Consult CDC guidance."
    context_blocks = ["Revenue increased 20% year over year in APAC region."]
    aligned, annotations = align_answer_with_context(answer, context_blocks)
    metrics = _compute_hallucination_metrics(aligned, annotations, context_blocks)
    assert metrics["grounded_sentences"] >= 1, "Expected at least one grounded sentence"
    assert 0 <= metrics["lexical_novelty_ratio"] <= 1, "Novelty ratio out of bounds"


def test_adaptive_requery_if_sparse():
    base_results = []
    extra = [{"chunk": f"Context block {i}", "score": 0.5} for i in range(5)]
    fr = FakeRetriever(extra)
    os.environ["ADAPTIVE_REQUERY_MIN_BLOCKS"] = "3"
    merged = _adaptive_requery_if_sparse("Quarterly performance", base_results, fr, None)
    assert len(merged) >= 5, "Adaptive re-query did not add extra results"


def test_multi_pass_cluster_summarize():
    # Provide many similar results to trigger clustering
    os.environ["MULTIPASS_CLUSTER_MIN_BLOCKS"] = "5"
    results = []
    for i in range(8):
        results.append({"chunk": f"Growth in revenue segment {i}. Revenue improved year over year.", "score": 0.6})
    summarized, meta = _multi_pass_cluster_summarize(results, None)
    assert meta is not None, "Expected clustering metadata"
    assert len(summarized) <= len(results), "Summarization should not increase block count"


def test_hallucination_risk_levels():
    # High novelty scenario
    answer = "Completely unrelated astrophysics statement about quasars and pulsars."
    context_blocks = ["Revenue data for enterprise software market."]
    aligned, annotations = align_answer_with_context(answer, context_blocks)
    metrics = _compute_hallucination_metrics(aligned, annotations, context_blocks)
    assert metrics["risk_level"] in ("medium", "high"), "Risk level should elevate for unrelated content"

