"""Index normalized search docs into vector store.

Steps:
 1. Fetch docs from normalized_search_docs missing embedding vector (or force reindex)
 2. Build concatenated text representation for embedding (account, owner, stage, summary fields)
 3. Generate embedding and upsert into target vector collections (OpenAI + Gemini if dual mode)

Env:
  INDEX_BATCH_SIZE=200
  INDEX_FORCE_REBUILD=false
  INDEX_TEXT_MAX_LEN=1200
  USE_OPENAI=true (shared with retriever)

Run:
  python -m app.scripts.index_normalized_docs
"""
from __future__ import annotations
import os, math, datetime
from typing import Dict, Any
from pymongo.collection import Collection
from app.db.mongo import db
from app.core.embeddings_fallback import get_query_embedding

NORM_COL = 'normalized_search_docs'
# For simplicity we reuse existing chunk collections (could create dedicated collection)
OPENAI_TARGET = os.getenv('NORMALIZED_VECTOR_COLLECTION_OPENAI','dd_accounts_chunks')
GEMINI_TARGET = os.getenv('NORMALIZED_VECTOR_COLLECTION_GEMINI','dd_accounts_chunks_gemini')
OPENAI_INDEX = os.getenv('NORMALIZED_VECTOR_INDEX_OPENAI','vector_index_v2')
GEMINI_INDEX = os.getenv('NORMALIZED_VECTOR_INDEX_GEMINI','vector_index_gemini_v2')


def _build_doc_text(doc: Dict[str,Any]) -> str:
    parts = []
    for k in ('doc_type','account_name','owner','stage','line_items_summary'):
        v = doc.get(k)
        if v:
            parts.append(str(v))
    # numeric/derived fields
    for k in ('amount','amount_avg','discount_ratio_avg','discount_ratio_max','cycle_duration_days','total_quote_amount','quote_count'):
        v = doc.get(k)
        if v is not None:
            parts.append(f"{k}:{v}")
    return ' | '.join(parts)[: int(os.getenv('INDEX_TEXT_MAX_LEN','1200')) ]


def index_normalized(force: bool=False):
    col: Collection = db.get_collection(NORM_COL)
    openai_col: Collection = db.get_collection(OPENAI_TARGET)
    gemini_col: Collection = db.get_collection(GEMINI_TARGET)
    batch_size = int(os.getenv('INDEX_BATCH_SIZE','200'))

    query = {} if force else { 'embedding_indexed': { '$ne': True } }
    cursor = col.find(query)
    processed = 0
    for doc in cursor:
        text = _build_doc_text(doc)
        try:
            emb = [float(x) for x in get_query_embedding(text)]
        except Exception:
            continue
        meta = {
            'normalized': True,
            'source_doc_type': doc.get('doc_type'),
            'source_id': doc.get('source_id'),
            'owner': doc.get('owner'),
            'account_name': doc.get('account_name'),
            'stage': doc.get('stage')
        }
        # Upsert into openai collection (embedding dim will decide which retriever path used)
        openai_col.update_one({'normalized_id': doc['source_id'], 'normalized_type': doc['doc_type']}, { '$set': {
            'normalized_id': doc['source_id'],
            'normalized_type': doc['doc_type'],
            'chunk': text,
            'metadata': meta,
            'embedding': emb
        }}, upsert=True)
        # Mirror to gemini if dual retrieval environment
        if os.getenv('USE_DUAL_EMBED','false').lower() == 'true':
            try:
                gemini_col.update_one({'normalized_id': doc['source_id'], 'normalized_type': doc['doc_type']}, { '$set': {
                    'normalized_id': doc['source_id'],
                    'normalized_type': doc['doc_type'],
                    'chunk': text,
                    'metadata': meta,
                    'embedding': emb  # placeholder (should call gemini embed) fallback reuse
                }}, upsert=True)
            except Exception:
                pass
        col.update_one({'_id': doc['_id']}, {'$set': {'embedding_indexed': True, 'indexed_at': datetime.datetime.utcnow() }})
        processed += 1
        if processed % 100 == 0:
            print(f"[INDEX] processed {processed} normalized docs")
    print(f"[INDEX] complete total={processed}")

if __name__ == '__main__':
    force = os.getenv('INDEX_FORCE_REBUILD','false').lower() == 'true'
    index_normalized(force)
