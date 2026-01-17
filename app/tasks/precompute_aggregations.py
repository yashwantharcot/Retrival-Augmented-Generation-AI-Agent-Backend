"""Precompute aggregation metrics for fast AGGREGATION intent answers.

Produces daily snapshot documents into collection `precomputed_aggregations` with shape:
  { date: ISODate, scope: 'global'|'account:<name>'|'owner:<id>', metrics: {...}, generated_at }

Metrics (initial):
  - quotes_total
  - amount_sum
  - amount_avg
  - discount_ratio_avg (averaged across normalized quote docs)
  - top_accounts (array of {account_name, amount_sum})

Environment:
  PRECOMP_SCOPE_ACCOUNTS_TOP_N=20
  PRECOMP_ACCOUNT_LIMIT=50 (limit number of per-account snapshots)

Run:
  python -m app.tasks.precompute_aggregations  (can be scheduled daily)
"""
from __future__ import annotations
import os, datetime
from typing import Dict, Any, List
from pymongo.collection import Collection
from app.db.mongo import db

NORM_COL = 'normalized_search_docs'
OUT_COL = 'precomputed_aggregations'

def _aggregate_global(col: Collection) -> Dict[str,Any]:
    pipeline = [
        { '$match': { 'doc_type': 'quote' }},
        { '$group': {
            '_id': None,
            'quotes_total': { '$sum': 1 },
            'amount_sum': { '$sum': { '$ifNull': ['$amount',0]}},
            'amount_avg': { '$avg': { '$ifNull': ['$amount',0]}},
            'discount_ratio_avg': { '$avg': { '$ifNull': ['$discount_ratio_avg',0]}},
        }}
    ]
    data = list(col.aggregate(pipeline))
    if not data:
        return {}
    doc = data[0]
    # Top accounts
    top_accounts = list(col.aggregate([
        { '$match': { 'doc_type':'quote', 'account_name': { '$exists': True, '$ne': None } } },
        { '$group': { '_id': '$account_name', 'amount_sum': { '$sum': { '$ifNull': ['$amount',0] } }, 'count': { '$sum': 1 } } },
        { '$sort': { 'amount_sum': -1 } },
        { '$limit': int(os.getenv('PRECOMP_SCOPE_ACCOUNTS_TOP_N','10')) }
    ]))
    doc['top_accounts'] = [ { 'account_name': t['_id'], 'amount_sum': t['amount_sum'], 'count': t['count'] } for t in top_accounts ]
    return doc

def _aggregate_per_account(col: Collection, name: str) -> Dict[str,Any]:
    pipeline = [
        { '$match': { 'doc_type': 'quote', 'account_name': name }},
        { '$group': {
            '_id': None,
            'quotes_total': { '$sum': 1 },
            'amount_sum': { '$sum': { '$ifNull': ['$amount',0]}},
            'amount_avg': { '$avg': { '$ifNull': ['$amount',0]}},
            'discount_ratio_avg': { '$avg': { '$ifNull': ['$discount_ratio_avg',0]}},
        }}
    ]
    data = list(col.aggregate(pipeline))
    if not data:
        return {}
    return data[0]

def run_precompute():
    norm_col: Collection = db.get_collection(NORM_COL)
    out_col: Collection = db.get_collection(OUT_COL)
    today = datetime.date.today().isoformat()
    # Global snapshot
    g = _aggregate_global(norm_col)
    if g:
        out_col.update_one({'date': today, 'scope':'global'}, { '$set': { 'metrics': g, 'generated_at': datetime.datetime.utcnow() }}, upsert=True)
    # Per-account snapshots (top N by amount today)
    accounts = g.get('top_accounts', []) if g else []
    limit = int(os.getenv('PRECOMP_ACCOUNT_LIMIT','50'))
    for acc in accounts[:limit]:
        name = acc['account_name']
        a_metrics = _aggregate_per_account(norm_col, name)
        if a_metrics:
            out_col.update_one({'date': today, 'scope': f'account:{name}'}, { '$set': { 'metrics': a_metrics, 'generated_at': datetime.datetime.utcnow() }}, upsert=True)
    print(f"[PRECOMP] Completed precompute for {today} global + {min(len(accounts),limit)} accounts")

if __name__ == '__main__':
    run_precompute()