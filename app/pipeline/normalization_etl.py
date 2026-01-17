"""Data Normalization & Enrichment ETL (Phase 1 -> extended)

Generates denormalized search documents for quotes & opportunities with derived fields
ready for lexical + vector indexing.

Input Collections (expected / optional):
    quotes, opportunities, line_items, activities

Output Collection:
    normalized_search_docs (one document per quote OR opportunity)

Quote Derived Fields:
    - discount_ratio_avg / discount_ratio_max ( (list_price - net_price)/list_price )
    - line_items_summary (top N product names concatenated)
    - amount_min, amount_max, amount_avg (net prices)
    - cycle_duration_days (created_at -> closed_at)
    - win_probability_bucket (0-24,25-49,50-74,75-100)
    - last_activity_at

Opportunity Derived Fields:
    - total_quote_amount (sum of related quote amounts if quotes reference opportunity_id)
    - quote_count
    - cycle_duration_days (created_at -> closed_at)
    - win_probability_bucket
    - last_activity_at (most recent activity referencing opportunity)
    - stage, amount, owner, account_name passthrough

Environment:
    NORMALIZE_BATCH_SIZE=500
    NORMALIZE_MAX_LINE_ITEMS=6
    NORMALIZE_INCLUDE_OPPORTUNITIES=true|false (default true)
"""
from __future__ import annotations
import os, math, datetime
from typing import Dict, Any, List, Iterable
from pymongo.collection import Collection
from app.db.mongo import db

OUTPUT_COLLECTION = 'normalized_search_docs'

_DEF_PROB_BUCKETS = [0,25,50,75,101]

def _bucket(prob: float) -> str:
    for i in range(len(_DEF_PROB_BUCKETS)-1):
        a,b = _DEF_PROB_BUCKETS[i], _DEF_PROB_BUCKETS[i+1]
        if a <= prob < b:
            return f"{a}-{b-1}"
    return "unknown"


def _safe_dt(val):
    if not val:
        return None
    if isinstance(val, datetime.datetime):
        return val
    try:
        return datetime.datetime.fromisoformat(str(val).replace('Z',''))
    except Exception:
        return None


def normalize_one_quote(quote: Dict[str,Any], line_items: List[Dict[str,Any]], activities: List[Dict[str,Any]]|None=None) -> Dict[str,Any]:
    qid = quote.get('id') or quote.get('_id')
    amount = float(quote.get('amount') or quote.get('total') or 0)
    list_prices = []
    net_prices = []
    product_names = []
    for li in line_items:
        lp = li.get('list_price'); np = li.get('net_price') or li.get('price')
        if lp:
            try: list_prices.append(float(lp))
            except Exception: pass
        if np:
            try: net_prices.append(float(np))
            except Exception: pass
        name = li.get('product_name') or li.get('sku')
        if name:
            product_names.append(str(name)[:40])
    discount_ratios = []
    for lp, np in zip(list_prices, net_prices):
        if lp > 0:
            discount_ratios.append((lp-np)/lp)
    max_li = int(os.getenv('NORMALIZE_MAX_LINE_ITEMS','6'))
    summary_names = list(dict.fromkeys(product_names))[:max_li]
    discount_ratio_avg = round(sum(discount_ratios)/len(discount_ratios),4) if discount_ratios else None
    discount_ratio_max = round(max(discount_ratios),4) if discount_ratios else None

    created_at = _safe_dt(quote.get('created_at') or quote.get('createdAt'))
    closed_at = _safe_dt(quote.get('closed_at') or quote.get('closedAt'))
    cycle_days = None
    if created_at and closed_at:
        cycle_days = (closed_at - created_at).days

    win_prob = None
    for key in ('win_probability','probability','winProb'):
        if key in quote:
            try:
                win_prob = float(quote[key]); break
            except Exception:
                pass
    win_bucket = _bucket(win_prob) if isinstance(win_prob,(int,float)) else None

    last_activity_at = None
    if activities:
        ts = [ _safe_dt(a.get('timestamp') or a.get('created_at')) for a in activities ]
        ts = [t for t in ts if t]
        if ts:
            last_activity_at = max(ts)

    doc = {
        'doc_type': 'quote',
        'source_id': qid,
        'account_name': quote.get('account_name') or quote.get('account'),
        'owner': quote.get('owner') or quote.get('owner_name'),
        'stage': quote.get('stage') or quote.get('status'),
        'amount': amount,
        'discount_ratio_avg': discount_ratio_avg,
        'discount_ratio_max': discount_ratio_max,
        'line_items_summary': ', '.join(summary_names),
        'amount_min': min(net_prices) if net_prices else None,
        'amount_max': max(net_prices) if net_prices else None,
        'amount_avg': round(sum(net_prices)/len(net_prices),2) if net_prices else None,
        'cycle_duration_days': cycle_days,
        'win_probability_bucket': win_bucket,
        'last_activity_at': last_activity_at,
        'raw': {
            'quote': quote,
            'line_items_count': len(line_items)
        }
    }
    return doc


def normalize_one_opportunity(opp: Dict[str,Any], related_quotes: List[Dict[str,Any]], activities: List[Dict[str,Any]]|None=None) -> Dict[str,Any]:
    oid = opp.get('id') or opp.get('_id')
    amount = float(opp.get('amount') or opp.get('value') or 0)
    created_at = _safe_dt(opp.get('created_at') or opp.get('createdAt'))
    closed_at = _safe_dt(opp.get('closed_at') or opp.get('closedAt'))
    cycle_days = (closed_at - created_at).days if created_at and closed_at else None
    win_prob = None
    for key in ('win_probability','probability','winProb'):
        if key in opp:
            try:
                win_prob = float(opp[key]); break
            except Exception:
                pass
    win_bucket = _bucket(win_prob) if isinstance(win_prob,(int,float)) else None
    total_quote_amount = 0.0
    for q in related_quotes:
        try:
            total_quote_amount += float(q.get('amount') or q.get('total') or 0)
        except Exception:
            pass
    last_activity_at = None
    if activities:
        ts = [_safe_dt(a.get('timestamp') or a.get('created_at')) for a in activities]
        ts = [t for t in ts if t]
        if ts:
            last_activity_at = max(ts)
    return {
        'doc_type': 'opportunity',
        'source_id': oid,
        'account_name': opp.get('account_name') or opp.get('account'),
        'owner': opp.get('owner') or opp.get('owner_name'),
        'stage': opp.get('stage') or opp.get('status'),
        'amount': amount,
        'total_quote_amount': round(total_quote_amount,2),
        'quote_count': len(related_quotes),
        'cycle_duration_days': cycle_days,
        'win_probability_bucket': win_bucket,
        'last_activity_at': last_activity_at,
        'raw': {
            'opportunity': opp,
            'related_quotes_count': len(related_quotes)
        }
    }


def _batched(iterable: Iterable, size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def run_normalization():
    """Execute normalization for quotes (always) and opportunities (optional)."""
    quotes: Collection = db.get_collection('quotes')
    line_items_col: Collection = db.get_collection('line_items')
    activities_col: Collection = db.get_collection('activities') if 'activities' in db.list_collection_names() else None
    out_col: Collection = db.get_collection(OUTPUT_COLLECTION)
    include_opps = os.getenv('NORMALIZE_INCLUDE_OPPORTUNITIES','true').lower() == 'true'
    batch_size = int(os.getenv('NORMALIZE_BATCH_SIZE','500'))

    # --- QUOTES ---
    processed_quotes = 0
    for q in quotes.find({}):
        qid = q.get('id') or q.get('_id')
        line_items = list(line_items_col.find({'quote_id': qid})) if line_items_col else []
        acts = list(activities_col.find({'quote_id': qid})) if activities_col else []
        doc = normalize_one_quote(q, line_items, acts)
        out_col.update_one({'doc_type':'quote','source_id':doc['source_id']}, {'$set': doc, '$setOnInsert': {'created_at': datetime.datetime.utcnow()}}, upsert=True)
        processed_quotes += 1
        if processed_quotes % 200 == 0:
            print(f"[NORMALIZE] quotes processed={processed_quotes}")
    print(f"[NORMALIZE] quotes complete total={processed_quotes}")

    # --- OPPORTUNITIES ---
    if include_opps and 'opportunities' in db.list_collection_names():
        opp_col: Collection = db.get_collection('opportunities')
        processed_opps = 0
        # Build mapping quote -> opportunity_id for aggregation (lightweight)
        quote_to_opp = {}
        try:
            for q in quotes.find({}, {'id':1,'_id':1,'opportunity_id':1,'opportunityId':1}):
                qid = q.get('id') or q.get('_id')
                oid = q.get('opportunity_id') or q.get('opportunityId')
                if oid:
                    quote_to_opp.setdefault(str(oid), []).append(qid)
        except Exception:
            pass
        for opp in opp_col.find({}):
            oid = opp.get('id') or opp.get('_id')
            # fetch related quotes (subset fields for performance)
            related_quotes = list(quotes.find({'opportunity_id': oid})) if oid else []
            acts = list(activities_col.find({'opportunity_id': oid})) if activities_col and oid else []
            doc = normalize_one_opportunity(opp, related_quotes, acts)
            out_col.update_one({'doc_type':'opportunity','source_id':doc['source_id']}, {'$set': doc, '$setOnInsert': {'created_at': datetime.datetime.utcnow()}}, upsert=True)
            processed_opps += 1
            if processed_opps % 200 == 0:
                print(f"[NORMALIZE] opportunities processed={processed_opps}")
        print(f"[NORMALIZE] opportunities complete total={processed_opps}")
    else:
        if include_opps:
            print("[NORMALIZE] opportunities collection not found - skipping")

    print("[NORMALIZE] all normalization passes complete")

if __name__ == '__main__':
    run_normalization()
