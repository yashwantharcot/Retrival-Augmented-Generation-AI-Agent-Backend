"""Structured answer template rendering for intent-specific fast paths.

Environment Flags:
  ANSWER_TEMPLATES_ENABLE=true|false      Master switch (default true)
  ANSWER_TEMPLATES_LLM_AUGMENT=true|false If true, template prepends structured preamble then still calls LLM.
  ANSWER_TEMPLATES_MIN_RESULTS=1          Min docs required to attempt a template.

Templates Implemented:
    ENTITY_LOOKUP / FACTOID: Extract key fields from top doc.
    AGGREGATION: Aggregate over result set (count, total, avg, median, optional timeframe & simple trend).
    COMPARISON: Compare two entities (account or opportunity) on amount & stage counts.
    DOCUMENT_EXPLORATION: Curated list of top N docs with one-line snippets.

Returns: dict with keys { 'answer': str, 'meta': {..} } or None.
"""
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
import os, re, statistics

def _get_meta(doc: Dict) -> Dict:
    return doc.get('metadata') or {}

def _num(val):
    try:
        if val is None: return None
        return float(val)
    except Exception:
        return None

def _collect_amounts(docs: List[Dict]) -> List[float]:
    out = []
    for d in docs:
        m = _get_meta(d)
        for k in ('amount','total','value','net_price_total','netTotal'):
            if k in m:
                v = _num(m.get(k))
                if v is not None:
                    out.append(v); break
    return out

def render_entity_lookup(docs: List[Dict]) -> Optional[Dict]:
    if not docs: return None
    top = docs[0]
    m = _get_meta(top)
    account = m.get('account_name') or m.get('account')
    opp = m.get('opportunity_name') or m.get('opportunity')
    stage = m.get('stage') or m.get('status')
    owner = m.get('owner') or m.get('owner_name')
    amount = None
    for k in ('amount','total','value','net_price_total'):
        if k in m:
            amount = m.get(k); break
    parts = []
    if account: parts.append(f"Account: {account}")
    if opp: parts.append(f"Opportunity: {opp}")
    if stage: parts.append(f"Stage: {stage}")
    if owner: parts.append(f"Owner: {owner}")
    if amount is not None: parts.append(f"Amount: {amount}")
    if not parts:
        return None
    answer = " | ".join(parts)
    return {"answer": answer, "meta": {"template": "entity_lookup", "fields": parts}}

def render_aggregation(docs: List[Dict]) -> Optional[Dict]:
    if not docs: return None
    amounts = _collect_amounts(docs)
    count = len(docs)
    if not amounts:
        return {"answer": f"Found {count} matching records.", "meta": {"template":"aggregation","count":count}}
    total = sum(amounts)
    avg = total/len(amounts)
    med = statistics.median(amounts) if amounts else None
    # Attempt simple timeframe inference (look for year or month tokens in metadata timestamps)
    timeframe = None
    ts = []
    for d in docs:
        m = _get_meta(d)
        for k in ('created_at','createdAt','last_activity_at'):
            val = m.get(k)
            if isinstance(val,str) and len(val) >= 10:
                ts.append(val[:10])
    if ts:
        ts_sorted = sorted(ts)
        timeframe = f"{ts_sorted[0]} to {ts_sorted[-1]}" if ts_sorted[0] != ts_sorted[-1] else ts_sorted[0]
    answer = (f"Records: {count}; Total Amount: {round(total,2)}; Avg: {round(avg,2)}" +
              (f"; Median: {round(med,2)}" if med is not None else "") +
              (f"; Timeframe: {timeframe}" if timeframe else ""))
    return {"answer": answer, "meta": {"template":"aggregation","count":count,"total":total,"avg":avg,"median":med,"timeframe":timeframe}}

def _group_by_entity(docs: List[Dict]) -> Dict[str, Dict]:
    groups = {}
    for d in docs:
        m = _get_meta(d)
        key = m.get('account_name') or m.get('opportunity_name') or m.get('account') or m.get('opportunity')
        if not key: continue
        g = groups.setdefault(key, {"docs":[],"amounts":[],"stages":{}})
        g["docs"].append(d)
        amt_candidates = _collect_amounts([d])
        if amt_candidates:
            g["amounts"].extend(amt_candidates)
        stage = m.get('stage') or m.get('status')
        if stage:
            g['stages'][stage] = g['stages'].get(stage,0)+1
    return groups

def _extract_compare_entities(query: str) -> Tuple[Optional[str], Optional[str]]:
    q = query.lower()
    # patterns with vs / versus
    m = re.search(r"compare\s+(.+?)\s+vs\s+(.+)$", q)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.search(r"(.+?)\s+vs\s+(.+)$", q)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, None

def render_comparison(query: str, docs: List[Dict]) -> Optional[Dict]:
    if not docs: return None
    a, b = _extract_compare_entities(query)
    groups = _group_by_entity(docs)
    if not groups or len(groups) < 2:
        return None
    # Choose two groups: match by extracted names else top by doc count
    keys = list(groups.keys())
    def _select(k): return k.lower().startswith(a) if a else False
    if a and any(_select(k) for k in keys):
        key_a = next(k for k in keys if _select(k))
    else:
        key_a = keys[0]
    if b and any(k.lower().startswith(b) for k in keys if k!=key_a):
        key_b = next(k for k in keys if k!=key_a and k.lower().startswith(b))
    else:
        key_b = next((k for k in keys if k!=key_a), None)
    if not key_b:
        return None
    ga, gb = groups[key_a], groups[key_b]
    def summarize(g):
        amt_total = sum(g['amounts']) if g['amounts'] else 0
        avg = (amt_total/len(g['amounts'])) if g['amounts'] else 0
        top_stage = None
        if g['stages']:
            top_stage = sorted(g['stages'].items(), key=lambda x:x[1], reverse=True)[0][0]
        return amt_total, avg, top_stage
    ta, aa, sa = summarize(ga)
    tb, ab, sb = summarize(gb)
    answer = (f"Comparison: {key_a} vs {key_b} | TotalAmount {round(ta,2)} vs {round(tb,2)} | "
              f"AvgAmount {round(aa,2)} vs {round(ab,2)}" +
              (f" | TopStage {sa or '-'} vs {sb or '-'}"))
    return {"answer": answer, "meta": {"template":"comparison","entities":[key_a,key_b],"totals":[ta,tb],"avgs":[aa,ab],"stages":[sa,sb]}}

def render_document_exploration(docs: List[Dict]) -> Optional[Dict]:
    if not docs: return None
    max_items = 8
    lines = []
    for d in docs[:max_items]:
        txt = (d.get('chunk') or '')[:140].replace('\n',' ')
        did = d.get('id')
        lines.append(f"- {did}: {txt}{'...' if len(txt)==140 else ''}")
    answer = "Top matching documents:\n" + "\n".join(lines)
    return {"answer": answer, "meta": {"template":"document_exploration","returned": len(lines)}}

def render_template(intent: str, query: str, docs: List[Dict]):
    if not docs: return None
    try:
        min_results = int(os.getenv('ANSWER_TEMPLATES_MIN_RESULTS','1'))
    except Exception:
        min_results = 1
    if len(docs) < min_results:
        return None
    intent = (intent or '').upper()
    if intent in ("ENTITY_LOOKUP","FACTOID"):
        return render_entity_lookup(docs)
    if intent == "AGGREGATION":
        return render_aggregation(docs)
    if intent == "COMPARISON":
        return render_comparison(query, docs)
    if intent == "DOCUMENT_EXPLORATION":
        return render_document_exploration(docs)
    return None

__all__ = ["render_template"]
