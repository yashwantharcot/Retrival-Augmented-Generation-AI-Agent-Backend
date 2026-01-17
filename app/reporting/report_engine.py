"""Reporting Engine: builds structured analytical reports from quote data.

Focus: pure text/markdown output (no graphs) so frontend can render consistently.

Provided utilities:
  aggregate_quotes(quotes) -> dict metrics
  build_report(query, report_format, instructions, prefs, metrics, quotes, history) -> markdown string
  build_structured_sections(metrics, quotes, report_format) -> list of section dicts (title, body)

Environment overrides:
  REPORT_TOP_ACCOUNTS (int, default 5)
  REPORT_MAX_QUOTES (int, default 50) limit detailed listing
  REPORT_INCLUDE_RAW (true/false)
"""
from __future__ import annotations
from typing import List, Dict, Any
import os, statistics, math

NUMERIC_FIELDS_CANDIDATES = [
    "amount", "cost", "list_price", "net_price", "discount", "average_rate"
]

def _safe_num(v):
    try:
        if v is None: return None
        if isinstance(v, (int, float)): return float(v)
        # strip commas / currency symbols
        s = str(v).replace(',', '').replace('$','').strip()
        return float(s) if s else None
    except Exception:
        return None

def aggregate_quotes(quotes: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not quotes:
        return {"total_quotes": 0, "accounts": {}, "numeric_fields": {}, "dates": []}
    accounts = {}
    numeric_field_values = {f: [] for f in NUMERIC_FIELDS_CANDIDATES}
    dates = []
    for q in quotes:
        acct = q.get('account_name') or q.get('account') or 'Unknown'
        accounts.setdefault(acct, {"count":0, "amount_sum":0.0})
        accounts[acct]["count"] += 1
        amt = _safe_num(q.get('amount') or q.get('total') or q.get('value'))
        if amt is not None:
            accounts[acct]["amount_sum"] += amt
        for f in NUMERIC_FIELDS_CANDIDATES:
            val = _safe_num(q.get(f))
            if val is not None:
                numeric_field_values[f].append(val)
        dt = q.get('date') or q.get('created_at') or q.get('createdAt')
        if dt:
            dates.append(str(dt))
    # compute aggregates
    numeric_aggs = {}
    for f, vals in numeric_field_values.items():
        if not vals:
            continue
        vals_sorted = sorted(vals)
        numeric_aggs[f] = {
            "min": min(vals),
            "max": max(vals),
            "avg": round(statistics.fmean(vals), 4),
            "median": round(statistics.median(vals), 4),
            "p90": round(vals_sorted[ int(math.ceil(0.9*len(vals_sorted)))-1 ], 4),
            "count": len(vals)
        }
    total_quotes = len(quotes)
    top_accounts_n = int(os.getenv("REPORT_TOP_ACCOUNTS", "5"))
    top_accounts = sorted(accounts.items(), key=lambda kv: kv[1]["amount_sum"], reverse=True)[:top_accounts_n]
    return {
        "total_quotes": total_quotes,
        "accounts": accounts,
        "top_accounts": top_accounts,
        "numeric_fields": numeric_aggs,
        "dates": dates
    }

def _format_accounts(metrics: Dict[str, Any]) -> str:
    if not metrics.get('accounts'):
        return "No account distribution available."
    lines = ["| Account | Quotes | Amount Sum |", "|---------|--------|------------|"]
    for acct, data in sorted(metrics['accounts'].items(), key=lambda kv: kv[1]['amount_sum'], reverse=True):
        lines.append(f"| {acct} | {data['count']} | {round(data['amount_sum'],2)} |")
    return "\n".join(lines)

def _format_top_accounts(metrics: Dict[str, Any]) -> str:
    if not metrics.get('top_accounts'):
        return "No top accounts." 
    lines = ["Top Accounts by Amount:"]
    rank = 1
    for acct, data in metrics['top_accounts']:
        lines.append(f"{rank}. {acct} – total {round(data['amount_sum'],2)} across {data['count']} quotes")
        rank += 1
    return "\n".join(lines)

def _format_numeric(metrics: Dict[str, Any]) -> str:
    nf = metrics.get('numeric_fields') or {}
    if not nf:
        return "No numeric field statistics." 
    lines = ["| Field | Count | Min | Median | Avg | P90 | Max |", "|-------|-------|-----|--------|-----|-----|-----|"]
    for f, agg in nf.items():
        lines.append(
            f"| {f} | {agg['count']} | {agg['min']:.2f} | {agg['median']:.2f} | {agg['avg']:.2f} | {agg['p90']:.2f} | {agg['max']:.2f} |"
        )
    return "\n".join(lines)

def _format_quote_samples(quotes: List[Dict[str, Any]]) -> str:
    if not quotes:
        return "No quotes available." 
    max_q = int(os.getenv("REPORT_MAX_QUOTES", "50"))
    lines = ["Sample Quotes (truncated):"]
    for i, q in enumerate(quotes[:max_q]):
        acct = q.get('account_name') or q.get('account') or 'Unknown'
        amt = q.get('amount') or q.get('total') or q.get('value')
        disc = q.get('discount')
        status = q.get('status') or q.get('state') or q.get('quote_status')
        lines.append(f"- {i+1}. Account={acct} Amount={amt} Discount={disc} Status={status}")
    if len(quotes) > max_q:
        lines.append(f"... {len(quotes)-max_q} more omitted")
    return "\n".join(lines)

def build_structured_sections(metrics: Dict[str, Any], quotes: List[Dict[str, Any]], report_format: str) -> List[Dict[str, str]]:
    sections = []
    sections.append({"title": "Summary", "body": f"Total quotes: {metrics.get('total_quotes',0)}"})
    sections.append({"title": "Top Accounts", "body": _format_top_accounts(metrics)})
    sections.append({"title": "Account Distribution", "body": _format_accounts(metrics)})
    sections.append({"title": "Numeric Field Statistics", "body": _format_numeric(metrics)})
    if os.getenv("REPORT_INCLUDE_RAW", "false").lower() == "true":
        sections.append({"title": "Quote Samples", "body": _format_quote_samples(quotes)})
    return sections

def build_report(query: str, report_format: str, instructions: str, prefs: Dict[str, Any], metrics: Dict[str, Any], quotes: List[Dict[str, Any]], history: List[str]) -> str:
    detail = prefs.get('detailLevel') or prefs.get('detaillevel') or 'medium'
    tone = prefs.get('tone','neutral')
    style = prefs.get('responseStyle') or prefs.get('responsestyle') or 'default'
    lines = []
    if history:
        lines.append("_Recent Interaction Context (last 5)_:\n" + "\n".join(history[-5:]))
    lines.append(f"# Report ({report_format or 'summary'})")
    lines.append(f"Query: {query}")
    lines.append(f"Tone: {tone}  | Detail: {detail}  | Style: {style}")
    if instructions:
        lines.append(f"Instructions: {instructions}")
    sections = build_structured_sections(metrics, quotes, report_format)
    for s in sections:
        lines.append(f"## {s['title']}")
        lines.append(s['body'])
    # Style-specific augmentations
    if report_format == 'recommendations':
        recs = []
        if metrics.get('top_accounts'):
            recs.append("Focus on top 2 accounts for upsell alignment.")
        if 'discount' in metrics.get('numeric_fields', {}):
            recs.append("Review discount policy; consider guardrails if average discount is high.")
        if not recs:
            recs.append("No actionable recommendations derived from current data.")
        lines.append("## Recommendations")
        lines.extend([f"- {r}" for r in recs])
    return "\n\n".join(lines).strip()
