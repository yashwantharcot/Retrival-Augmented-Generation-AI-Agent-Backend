"""Fusion + Re‑rank pipeline skeleton for Dealdox CPQ agent.

Phase: C (Skeleton)

Goals:
- Provide hybrid candidate fusion (lexical + vector) via Reciprocal Rank Fusion (RRF)
- Attach lightweight feature set for downstream ML / heuristic re‑ranking
- Offer pluggable re_rank() hook (current: heuristic linear blend)
- Keep dependency free (pure Python) and fast

Intended Usage:
    from app.core.fusion_rerank import hybrid_rank
    results = hybrid_rank(query, bm25_fetch, vector_fetch, k=20)

Where bm25_fetch(query, k) -> list[ScoredDoc]
      vector_fetch(query, k) -> list[ScoredDoc]

ScoredDoc minimal contract:
    {"id": str, "score": float, "text": str, "metadata": {...}}

Env toggles (optional):
    FUSION_RRF_K       (int)  default 60  - depth per source before fusion
    FUSION_RRF_K_COEFF (int)  default 60  - standard RRF k constant
    FUSION_SOURCE_WEIGHTS JSON mapping e.g. '{"bm25":1.0,"vector":1.1}'
    RERANK_LINEAR_WEIGHTS JSON mapping for feature weights
    RERANK_TOP_N       (int) limit for expensive future model invocation (placeholder)

Extend Later:
- Add third source (activity_chunks) or (recent_memory)
- Integrate cross-encoder stage on top-N
- Feature store persistence
- A/B hooks
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Optional
import os, json, math, statistics, datetime
try:
    from .ontology import ontology_boost
except Exception:
    def ontology_boost(q,t): return 0.0
try:
    # Lazy optional import to avoid circular issues (fusion_autotune does not import us)
    from .fusion_autotune import get_fusion_calibrator  # type: ignore
except Exception:  # pragma: no cover - fallback if module path changes
    def get_fusion_calibrator():  # type: ignore
        class _Dummy:  # minimal stub
            def get_dynamic_weights(self):
                return {}
        return _Dummy()

@dataclass
class Candidate:
    id: str
    text: str
    source: str  # 'bm25' | 'vector' | etc
    base_score: float
    fused_score: float = 0.0
    features: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, object] = field(default_factory=dict)

# ------------------ Core Fusion (RRF) ------------------ #

def _reciprocal(rank: int, k_const: int) -> float:
    return 1.0 / (k_const + rank)

def rrf_fuse(
    sources: Dict[str, List[Dict]],
    k_const: int = 60,
    source_weights: Optional[Dict[str, float]] = None
) -> List[Candidate]:
    """Perform Reciprocal Rank Fusion over multiple ranked lists.
    sources: mapping source_name -> list of scored docs (each must have id, score, text)
    Returns unified candidate list with fused_score set.
    """
    source_weights = source_weights or {}
    ranks: Dict[str, Dict[str, int]] = {}
    # Build rank maps
    for src, docs in sources.items():
        for idx, d in enumerate(docs):
            ranks.setdefault(src, {})[d["id"]] = idx + 1  # 1-based
    fused: Dict[str, Candidate] = {}
    for src, docs in sources.items():
        weight = source_weights.get(src, 1.0)
        for idx, d in enumerate(docs):
            cid = d["id"]
            c = fused.get(cid)
            if not c:
                c = Candidate(id=cid, text=d.get("text",""), source=src, base_score=d.get("score",0.0), metadata=d.get("metadata",{}))
                fused[cid] = c
            rank_val = ranks[src][cid]
            c.fused_score += weight * _reciprocal(rank_val, k_const)
    # Return sorted by fused_score desc
    out = list(fused.values())
    out.sort(key=lambda x: x.fused_score, reverse=True)
    return out

# ------------------ Feature Extraction ------------------ #

def _parse_dt(val):
    if not val:
        return None
    if isinstance(val, (datetime.datetime, datetime.date)):
        # Normalize to datetime
        if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
            return datetime.datetime(val.year, val.month, val.day)
        return val
    try:
        # Strip Z if present
        return datetime.datetime.fromisoformat(str(val).replace('Z',''))
    except Exception:
        return None

def attach_features(candidates: List[Candidate], query: str):
    q_lower = query.lower()
    q_terms = [t for t in q_lower.split() if len(t) > 2]
    q_term_set = set(q_terms)
    # Pre-compute stats
    fused_scores = [c.fused_score for c in candidates] or [1.0]
    max_fused = max(fused_scores)
    min_fused = min(fused_scores)
    span = max(1e-9, max_fused - min_fused)
    # Recency configuration
    recency_enable = os.getenv('RECENCY_FEATURE_ENABLE','true').lower() == 'true'
    # Half-life days (score decays by half every N days) or lambda override
    half_life = float(os.getenv('RECENCY_HALF_LIFE_DAYS','30'))
    now = datetime.datetime.utcnow()
    lambda_decay = math.log(2)/half_life if half_life > 0 else 0.0

    for rank, c in enumerate(candidates, start=1):
        txt_lower = c.text.lower()
        term_hits = sum(1 for t in q_terms if t in txt_lower)
        unique_hits = len({t for t in q_term_set if t in txt_lower})
        length = len(c.text)
        tokens = len(c.text.split())
        recency_score = 0.0
        if recency_enable:
            # Search for timestamp fields in metadata
            md = c.metadata or {}
            ts_val = None
            for key in ('last_activity_at','updated_at','created_at','timestamp','date'):
                if key in md:
                    ts_val = _parse_dt(md.get(key))
                    if ts_val:
                        break
            if ts_val:
                age_days = max(0.0, (now - ts_val).total_seconds()/86400.0)
                if lambda_decay > 0:
                    recency_score = math.exp(-lambda_decay * age_days)
                else:
                    recency_score = 1.0
        c.features.update({
            "rank_initial": float(rank),
            "fused_norm": (c.fused_score - min_fused) / span,
            "term_hits": float(term_hits),
            "unique_term_hits": float(unique_hits),
            "text_len": float(length),
            "token_count": float(tokens),
            "short_text": 1.0 if tokens < 50 else 0.0,
            "very_short": 1.0 if tokens < 15 else 0.0,
            "recency_score": recency_score,
        })
    # Aggregate statistics for context if needed
    return candidates

# ------------------ Heuristic Re-ranker ------------------ #

_DEF_LINEAR_WEIGHTS = {
    "fused_norm": 1.0,
    "unique_term_hits": 0.6,
    "term_hits": 0.3,
    "very_short": -0.05,  # slight penalty to excessively short
    "recency_score": 0.25  # modest preference for fresher content
}

def _load_linear_weights():
    raw = os.getenv("RERANK_LINEAR_WEIGHTS")
    if not raw:
        return _DEF_LINEAR_WEIGHTS
    try:
        user_map = json.loads(raw)
        return {**_DEF_LINEAR_WEIGHTS, **user_map}
    except Exception:
        return _DEF_LINEAR_WEIGHTS


def linear_rerank(candidates: List[Candidate], query: str | None = None):
    weights = _load_linear_weights()
    for c in candidates:
        score = 0.0
        for feat, w in weights.items():
            if feat in c.features:
                score += w * c.features[feat]
        if query:
            ob = ontology_boost(query, c.text)
            if ob:
                c.features['ontology_boost'] = ob
                score += ob
        c.features["linear_score"] = score
    # Optional diversity pass (greedy MMR-lite using Jaccard token overlap)
    if os.getenv('RERANK_DIVERSITY_ENABLE','true').lower() == 'true' and len(candidates) > 2:
        def _tokset(txt: str):
            return {t for t in txt.lower().split() if len(t) > 2}
        selected: List[Candidate] = []
        pool = candidates[:]
        pool.sort(key=lambda x: x.features.get('linear_score', 0.0), reverse=True)
        selected.append(pool.pop(0))
        sel_sets = [_tokset(selected[0].text)]
        lam = float(os.getenv('RERANK_DIVERSITY_LAMBDA','0.15'))
        cap = int(os.getenv('RERANK_DIVERSITY_TOP', str(len(candidates))))
        while pool and len(selected) < cap:
            best = None
            best_val = -1e18
            for c in pool:
                base = c.features.get('linear_score', 0.0)
                ts = _tokset(c.text)
                # max similarity to any selected
                max_j = 0.0
                for ss in sel_sets:
                    inter = len(ts & ss)
                    union = max(1, len(ts | ss))
                    max_j = max(max_j, inter/union)
                val = base - lam * max_j
                if val > best_val:
                    best_val = val
                    best = c
            if best is None:
                break
            selected.append(best)
            sel_sets.append(_tokset(best.text))
            pool.remove(best)
        # append remainder preserving order
        selected.extend(pool)
        candidates[:] = selected
    # Final sort for stability by linear then fused
    candidates.sort(key=lambda x: (x.features.get("linear_score", 0.0), x.fused_score), reverse=True)
    return candidates

# ------------------ Hybrid Ranking Orchestrator ------------------ #

def hybrid_rank(
    query: str,
    bm25_fetch: Callable[[str, int], List[Dict]],
    vector_fetch: Callable[[str, int], List[Dict]],
    k: int = 20,
    include_features: bool = True,
    extra_sources: Optional[Dict[str, List[Dict]]] = None,
) -> List[Candidate]:
    depth = int(os.getenv("FUSION_RRF_K", "60"))
    k_const = int(os.getenv("FUSION_RRF_K_COEFF", "60"))
    # Fetch from sources
    bm25_docs = bm25_fetch(query, depth) if bm25_fetch else []
    vec_docs = vector_fetch(query, depth) if vector_fetch else []
    # Build source weights
    try:
        src_w_raw = os.getenv("FUSION_SOURCE_WEIGHTS")
        static_weights = json.loads(src_w_raw) if src_w_raw else {"bm25":1.0, "vector":1.0}
    except Exception:
        static_weights = {"bm25":1.0, "vector":1.0}

    # Merge dynamic weights (auto-calibration) if available: final = static * dynamic (multiplicative scaling)
    dynamic_weights = {}
    try:
        dynamic_weights = get_fusion_calibrator().get_dynamic_weights() or {}
    except Exception:
        dynamic_weights = {}
    if dynamic_weights:
        merged = {}
        for src, base_w in static_weights.items():
            dyn = dynamic_weights.get(src, 1.0)
            merged[src] = base_w * dyn
        # include any new sources present only in dynamic map
        for src, dyn in dynamic_weights.items():
            if src not in merged:
                merged[src] = dyn
        source_weights = merged
    else:
        source_weights = static_weights

    # Compose sources; optionally include extra sources like 'memory' or 'activities'
    sources_map: Dict[str, List[Dict]] = {"bm25": bm25_docs, "vector": vec_docs}
    if extra_sources:
        for name, docs in extra_sources.items():
            if docs:
                sources_map[name] = docs
                if name not in source_weights:
                    source_weights[name] = 1.0
    fused = rrf_fuse(sources_map, k_const=k_const, source_weights=source_weights)
    # Attach weight metadata for diagnostics (only on first candidate to avoid repetition)
    if fused:
        for c in fused:
            c.metadata = c.metadata or {}
            # lightweight copy; don't overwrite if already exists
            if '_fusion_weights' not in c.metadata:
                c.metadata['_fusion_weights'] = source_weights
        # mark weights only on top candidate to reduce payload size (optional optimization)
        top_weights = source_weights
        for c in fused[1:]:
            # keep just a flag to indicate weights applied
            c.metadata.pop('_fusion_weights', None)
            c.metadata['_fusion_weights_applied'] = True
    if include_features:
        attach_features(fused, query)
        linear_rerank(fused, query)
    return fused[:k]

# ------------------ Stub Fetchers (for local quick test) ------------------ #
if __name__ == "__main__":
    def _fake_bm25(q, k):
        return [{"id": f"bm25_{i}", "score": 1/(i+1), "text": f"Doc {i} about {q}", "metadata": {}} for i in range(5)]
    def _fake_vec(q, k):
        return [{"id": f"vec_{i}", "score": 0.9/(i+1), "text": f"Vector Doc {i} referencing {q}", "metadata": {}} for i in range(5)]
    ranked = hybrid_rank("discount trend", _fake_bm25, _fake_vec, k=6)
    for c in ranked:
        print(c.id, round(c.fused_score,4), round(c.features.get("linear_score",0),3), c.features)
