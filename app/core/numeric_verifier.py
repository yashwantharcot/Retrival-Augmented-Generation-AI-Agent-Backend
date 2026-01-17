"""Numeric verification pass: validates numbers in model answer are grounded in context.

Environment Flags:
  NUMERIC_VERIFY_ENABLE=true|false (default true)
  NUMERIC_VERIFY_TOLERANCE=0.02      # relative tolerance for matching (e.g. 0.02 = 2%)
  NUMERIC_VERIFY_MIN_ABS=0           # minimum absolute value to consider (filter noise like list numbering)
  NUMERIC_VERIFY_MAX_COUNT=40        # cap processed numbers for speed

Output schema (dict):
  {
    'numbers_total': int,
    'numbers_checked': int,
    'grounded': int,
    'ungrounded': int,
    'ungrounded_examples': [str,...],
    'tolerance': float
  }
"""
from __future__ import annotations
import re, os
from typing import List

NUMBER_RE = re.compile(r"(?<![\w/])(-?\d{1,3}(?:[,\d]{3})*(?:\.\d+)?%?)")

def _to_float(raw: str):
    pct = raw.endswith('%')
    s = raw[:-1] if pct else raw
    s = s.replace(',', '')
    try:
        val = float(s)
        if pct:
            val = val / 100.0
        return val, pct
    except Exception:
        return None, pct

def extract_numbers(text: str):
    if not text:
        return []
    return NUMBER_RE.findall(text)

def verify_numbers(answer: str, context_blocks: List[str]):
    try:
        if os.getenv("NUMERIC_VERIFY_ENABLE", "true").lower() != "true":
            return None
        tol = float(os.getenv("NUMERIC_VERIFY_TOLERANCE", "0.02"))
        min_abs = float(os.getenv("NUMERIC_VERIFY_MIN_ABS", "0"))
        max_count = int(os.getenv("NUMERIC_VERIFY_MAX_COUNT", "40"))
    except Exception:
        tol, min_abs, max_count = 0.02, 0.0, 40

    ans_nums_raw = extract_numbers(answer)
    # De-duplicate preserving order
    seen = set(); ans_nums = []
    for n in ans_nums_raw:
        if n not in seen:
            ans_nums.append(n); seen.add(n)
    # Build context numeric pool
    ctx_nums_raw = []
    for cb in context_blocks or []:
        ctx_nums_raw.extend(extract_numbers(cb))
    ctx_values = []
    for cn in ctx_nums_raw:
        v, pct = _to_float(cn)
        if v is not None:
            ctx_values.append((v, pct))
    grounded = 0; ungrounded_list = []
    checked = 0
    for raw in ans_nums:
        if checked >= max_count:
            break
        val, pct = _to_float(raw)
        if val is None or abs(val) < min_abs:
            continue
        checked += 1
        # direct string match OR numeric approximate match
        if raw in ctx_nums_raw:
            grounded += 1
            continue
        # approximate search
        matched = False
        for cv, cpct in ctx_values:
            if cpct != pct:  # don't mix percent vs absolute
                continue
            base = max(1e-9, abs(cv), abs(val))
            if abs(cv - val) / base <= tol:
                matched = True
                break
        if matched:
            grounded += 1
        else:
            ungrounded_list.append(raw)
    return {
        'numbers_total': len(ans_nums),
        'numbers_checked': checked,
        'grounded': grounded,
        'ungrounded': len(ungrounded_list),
        'ungrounded_examples': ungrounded_list[:5],
        'tolerance': tol
    }

__all__ = ["verify_numbers"]
