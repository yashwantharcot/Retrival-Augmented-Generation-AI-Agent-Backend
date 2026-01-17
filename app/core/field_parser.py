"""Fielded query parsing for lightweight structured filters.

Supports inline filters embedded in the natural language query:
  owner:alice       (owner partial match, case‑insensitive)
  stage:Negotiation (stage partial match)
  amount>5000       (min amount)
  amount>=7500
  amount<12000      (max amount)
  date:2025-09      (month; interpreted as first->last day)
  date:2025-09-10   (specific day; from=to)
  date:2025-Q3      (quarter expansion)
  date>=2025-07-01  (explicit from)
  date<=2025-09-30  (explicit to)

Returns (clean_query, filters_dict)
filters_dict keys (present only if parsed):
  owner_regex, stage_regex, amount_min, amount_max, date_from, date_to, raw_filters(list)

Environment Flags:
  FIELD_PARSING_ENABLE=true|false
  FIELD_PARSING_MAX_TOKENS=40   (# tokens to scan to avoid huge queries cost)

The parser is intentionally conservative: it only strips recognized filter tokens; everything else remains.
"""
from __future__ import annotations
from typing import Tuple, Dict, List, Optional
import re
from datetime import datetime, timedelta

_AMOUNT_CMP_RE = re.compile(r"^(amount)(>=|<=|>|<|=)(\d+(?:\.\d+)?)$", re.IGNORECASE)
_KEY_VALUE_RE = re.compile(r"^(owner|stage|date):(\S+)$", re.IGNORECASE)
_DATE_CMP_RE = re.compile(r"^(date)(>=|<=|=)(\d{4}-\d{2}-\d{2})$", re.IGNORECASE)
_QUARTER_RE = re.compile(r"^(\d{4})-q([1-4])$", re.IGNORECASE)
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")

def _end_of_month(year: int, month: int):
    if month == 12:
        return datetime(year, 12, 31)
    first_next = datetime(year, month+1, 1)
    return first_next - timedelta(days=1)

def _expand_quarter(year: int, q: int):
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    start = datetime(year, start_month, 1)
    end = _end_of_month(year, end_month)
    return start, end

def parse_query_filters(query: str) -> Tuple[str, Dict]:
    if not query:
        return query, {}
    tokens = query.split()
    max_tokens = 0
    try:
        from os import getenv
        max_tokens = int(getenv("FIELD_PARSING_MAX_TOKENS", "40"))
    except Exception:
        max_tokens = 40
    filters: Dict[str, Optional[str]] = {}
    raw_filters: List[str] = []
    kept_tokens: List[str] = []
    amount_min = None
    amount_max = None
    date_from = None
    date_to = None
    for idx, tok in enumerate(tokens):
        if idx >= max_tokens:
            kept_tokens.extend(tokens[idx:])
            break
        m_amt = _AMOUNT_CMP_RE.match(tok)
        if m_amt:
            op = m_amt.group(2)
            val = float(m_amt.group(3))
            if op in (">", ">="):
                amount_min = val if amount_min is None else max(amount_min, val)
            elif op in ("<", "<="):
                amount_max = val if amount_max is None else min(amount_max, val)
            elif op == "=":
                amount_min = amount_max = val
            raw_filters.append(tok)
            continue
        m_kv = _KEY_VALUE_RE.match(tok)
        if m_kv:
            key = m_kv.group(1).lower()
            val = m_kv.group(2)
            if key == "owner":
                filters["owner_regex"] = val
            elif key == "stage":
                filters["stage_regex"] = val
            elif key == "date":
                dv = val.lower()
                # Quarter?
                mq = _QUARTER_RE.match(dv)
                if mq:
                    y = int(mq.group(1)); q = int(mq.group(2))
                    start, end = _expand_quarter(y, q)
                    date_from = start if date_from is None else max(date_from, start)
                    date_to = end if date_to is None else min(date_to, end)
                else:
                    mm = _MONTH_RE.match(dv)
                    if mm:
                        y = int(mm.group(1)); m = int(mm.group(2))
                        start = datetime(y, m, 1); end = _end_of_month(y, m)
                        date_from = start if date_from is None else max(date_from, start)
                        date_to = end if date_to is None else min(date_to, end)
                    else:
                        # Day
                        try:
                            dt = datetime.strptime(val[:10], "%Y-%m-%d")
                            date_from = dt if date_from is None else max(date_from, dt)
                            date_to = dt if date_to is None else min(date_to, dt)
                        except Exception:
                            pass
            raw_filters.append(tok)
            continue
        m_dc = _DATE_CMP_RE.match(tok)
        if m_dc:
            op = m_dc.group(2)
            try:
                dt = datetime.strptime(m_dc.group(3), "%Y-%m-%d")
                if op in (">=", ">"):
                    date_from = dt if date_from is None else max(date_from, dt)
                elif op in ("<=", "<"):
                    date_to = dt if date_to is None else min(date_to, dt)
                else:  # =
                    date_from = date_to = dt
                raw_filters.append(tok)
                continue
            except Exception:
                pass
        # Not a filter token
        kept_tokens.append(tok)

    if amount_min is not None:
        filters["amount_min"] = amount_min
    if amount_max is not None:
        filters["amount_max"] = amount_max
    if date_from is not None:
        filters["date_from"] = date_from
    if date_to is not None:
        filters["date_to"] = date_to
    if raw_filters:
        filters["raw_filters"] = raw_filters
    clean_query = " ".join(kept_tokens).strip() or query
    return clean_query, filters

__all__ = ["parse_query_filters"]
