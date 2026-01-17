"""Intent classification skeleton for Dealdox CPQ agent.

Phase: B (Skeleton)

Design Goals:
- Lightweight, fast, dependency‑free rule baseline
- Pluggable upgrade path (ML / embedding / fine-tuned model)
- Deterministic output for early pipeline branching
- Provide rationale + matched features for observability

Intents (initial set):
  AGGREGATION        e.g. "total discount last quarter", "how many quotes this month"
  COMPARISON         e.g. "compare Acme vs Globex Q3 quotes"
  ANALYTIC_INSIGHT   e.g. "why are win rates down", "trend in discount percentage"
  ENTITY_LOOKUP      e.g. "status of quote QT123", "owner of opportunity Phoenix"
  FACTOID            e.g. "who owns Phoenix expansion", simple field lookups
  DOCUMENT_EXPLORATION e.g. "show recent pricing exceptions", "list approval notes"
  GENERAL_CHAT       fallback smalltalk / unsupported

Return Object:
  IntentResult(intent: IntentType, confidence: float, reasons: list[str], features: dict)

Upgrade Hooks:
  - add register_model() to plug an ML classifier
  - add feature extraction module (token stats, ngrams, embeddings)
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
import re
from typing import List, Dict
try:
    from .caching import intent_cache_get, intent_cache_set
except Exception:  # fallback if caching module missing
    def intent_cache_get(q): return None
    def intent_cache_set(q,v): return None

class IntentType(str, Enum):
    AGGREGATION = "AGGREGATION"
    COMPARISON = "COMPARISON"
    ANALYTIC_INSIGHT = "ANALYTIC_INSIGHT"
    ENTITY_LOOKUP = "ENTITY_LOOKUP"
    FACTOID = "FACTOID"
    DOCUMENT_EXPLORATION = "DOCUMENT_EXPLORATION"
    GENERAL_CHAT = "GENERAL_CHAT"

@dataclass
class IntentResult:
    intent: IntentType
    confidence: float
    reasons: List[str] = field(default_factory=list)
    features: Dict[str, object] = field(default_factory=dict)

AGG_PATTERNS = [
    r"\bhow many\b",
    r"\bnumber of\b",
    r"\bcount of\b",
    r"\btotal(?:\s+amount|)\b",
    r"\bsum(?:mary)? of\b",
    r"\baverage|avg|min|max|median\b"
]
COMP_PATTERNS = [r"\bcompare\b", r"\bversus\b", r"\bvs\b", r"difference between"]
INSIGHT_PATTERNS = [r"\bwhy\b", r"\breasons?\b", r"\btrend\b", r"\bincrease\b", r"\bdecrease\b", r"\bimprov", r"\bdeclin"]
LOOKUP_PATTERNS = [r"status of", r"stage of", r"owner of", r"amount of", r"quote\s+\w+", r"opportunity\s+\w+"]
FACTOID_PATTERNS = [r"^who ", r"^what ", r"^when ", r"^which "]
DOC_EXP_PATTERNS = [r"show recent", r"list ", r"show all", r"latest", r"approval notes", r"pricing exceptions", r"notes", r"activities"]

NUMBER_RE = re.compile(r"[-+]?[0-9]+(?:\.[0-9]+)?")
DATE_HINT_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|last month|last quarter|this month|today|yesterday|q[1-4])\b", re.I)


def _match_any(patterns: List[str], text: str) -> List[str]:
    hits = []
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            hits.append(p)
    return hits


def classify_intent(query: str) -> IntentResult:
    if not query:
        return IntentResult(IntentType.GENERAL_CHAT, 0.1, ["empty"], {})
    cached = intent_cache_get(query)
    if cached:
        return cached
    q = query.strip()
    q_l = q.lower()

    features = {
        "length": len(q_l.split()),
        "has_number": bool(NUMBER_RE.search(q_l)),
        "has_date_hint": bool(DATE_HINT_RE.search(q_l)),
    }

    scored = []  # (intent, reasons, base_score)

    # Aggregation
    agg_hits = _match_any(AGG_PATTERNS, q_l)
    if agg_hits:
        base = 0.55 + 0.05 * min(3, len(agg_hits))
        if features["has_date_hint"]: base += 0.05
        scored.append((IntentType.AGGREGATION, agg_hits, base))

    # Comparison
    comp_hits = _match_any(COMP_PATTERNS, q_l)
    if comp_hits:
        scored.append((IntentType.COMPARISON, comp_hits, 0.65))

    # Analytic insight
    ins_hits = _match_any(INSIGHT_PATTERNS, q_l)
    if ins_hits:
        scored.append((IntentType.ANALYTIC_INSIGHT, ins_hits, 0.6 + 0.05 * min(2, len(ins_hits))))

    # Entity lookup
    look_hits = _match_any(LOOKUP_PATTERNS, q_l)
    if look_hits:
        scored.append((IntentType.ENTITY_LOOKUP, look_hits, 0.5))

    # Factoid
    fact_hits = _match_any(FACTOID_PATTERNS, q_l)
    if fact_hits and len(q_l.split()) <= 10:
        scored.append((IntentType.FACTOID, fact_hits, 0.55))

    # Document exploration
    doc_hits = _match_any(DOC_EXP_PATTERNS, q_l)
    if doc_hits:
        base = 0.5 + 0.05 * min(2, len(doc_hits))
        scored.append((IntentType.DOCUMENT_EXPLORATION, doc_hits, base))

    if not scored:
        # Heuristic: very short generic queries → GENERAL_CHAT
        if features["length"] <= 3:
            return IntentResult(IntentType.GENERAL_CHAT, 0.4, ["short generic"], features)
        # Fallback assume lookup-ish
        return IntentResult(IntentType.ENTITY_LOOKUP, 0.35, ["fallback"], features)

    # Pick top by score; if tie prefer more specific ordering
    priority_order = [
        IntentType.COMPARISON,
        IntentType.AGGREGATION,
        IntentType.ANALYTIC_INSIGHT,
        IntentType.DOCUMENT_EXPLORATION,
        IntentType.ENTITY_LOOKUP,
        IntentType.FACTOID,
    ]
    max_score = max(s[2] for s in scored)
    winners = [s for s in scored if abs(s[2]-max_score) < 1e-6]
    if len(winners) > 1:
        # resolve by priority
        winners.sort(key=lambda x: priority_order.index(x[0]) if x[0] in priority_order else 99)
    intent, reasons, score = winners[0]

    # Clip and adjust
    confidence = min(0.92, score)

    result = IntentResult(intent, confidence, reasons, features)
    intent_cache_set(query, result)
    return result

# Simple manual test (only runs if executed directly)
if __name__ == "__main__":
    samples = [
        "total discount last quarter",
        "compare Acme vs Globex quotes",
        "why are win rates down",
        "status of quote QT123",
        "who owns Phoenix expansion",
        "show recent pricing exceptions",
        "hi",
    ]
    for s in samples:
        r = classify_intent(s)
        print(f"{s:40} -> {r.intent} ({r.confidence:.2f}) reasons={r.reasons} features={r.features}")
