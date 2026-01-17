# app/core/retriever.py

import os
import math
import logging
from typing import List, Optional, Dict
from app.core.embeddings_fallback import get_query_embedding


class Retriever:
    def __init__(self, openai_collection, gemini_collection, openai_index, gemini_index):
        self.openai_collection = openai_collection
        self.gemini_collection = gemini_collection
        self.openai_index = openai_index
        self.gemini_index = gemini_index
        # In-memory cache for embeddings
        self.embedding_cache = {}

    def _build_pipeline(self, vector: List[float], index_name: str, k: int, metadata_filter: Optional[Dict]):
    # metadata_filter already expected as Mongo match dict if provided
        pipeline = [
            {
                "$vectorSearch": {
                    "index": index_name,
                    "path": "embedding",
                    "queryVector": vector,
                    "numCandidates": 100,
                    "limit": k
                }
            }
        ]
        if metadata_filter:
            pipeline.append({"$match": metadata_filter})
        pipeline.append({
            "$project": {
                "_id": 0,
                "chunk": 1,  # Project the actual context field
                "text": 1,   # Also project text if present
                "score": {"$meta": "vectorSearchScore"},
                "metadata": 1,
                "structured_data": 1
            }
        })
        
        return pipeline

    def retrieve(self, query: str, k: int = 20, metadata_filter: Optional[Dict] = None, preferences: Optional[Dict] = None) -> List[Dict]:
        # Allow string style filter (same syntax as personalization layer) and convert to Mongo match
        if isinstance(metadata_filter, str):
            metadata_filter = self._parse_metadata_filter(metadata_filter)
        use_openai = os.getenv("USE_OPENAI", "true").lower() == "true"
        # Embedding cache key
        emb_key = query.strip()
        if emb_key in self.embedding_cache:
            vector = self.embedding_cache[emb_key]
        else:
            try:
                vector = [float(x) for x in get_query_embedding(query)]
                self.embedding_cache[emb_key] = vector
            except Exception as e:
                logging.getLogger(__name__).error(f"[Retriever] embedding failed: {e}")
                return []

        # Semantic metadata pre-filter (optional)
        if metadata_filter is None and os.getenv("ENABLE_SEMANTIC_META_PREFILTER", "true").lower() == "true":
            try:
                sem_filter = self._semantic_metadata_prefilter(vector, use_openai)
                if sem_filter:
                    metadata_filter = sem_filter
                    logging.getLogger(__name__).info(f"[SEM_META] Applied semantic prefilter {sem_filter}")
            except Exception as e:
                logging.getLogger(__name__).warning(f"[SEM_META] prefilter failed: {e}")

        results = []
        if use_openai:
            pipeline = self._build_pipeline(vector, self.openai_index, k, metadata_filter)
            openai_results = list(self.openai_collection.aggregate(pipeline))
            for r in openai_results:
                r["provider"] = "openai"
            results.extend(openai_results)
        else:
            pipeline = self._build_pipeline(vector, self.gemini_index, k, metadata_filter)
            gemini_results = list(self.gemini_collection.aggregate(pipeline))
            for r in gemini_results:
                r["provider"] = "gemini"
            results.extend(gemini_results)
        # At this point `score` is the raw vectorSearchScore. We'll compute a hybrid
        # score that mixes vector similarity with a lightweight lexical overlap
        # (Jaccard of token sets) to favor docs that match both semantically and lexically.
        # This behavior is env-gated; default keeps vector-heavy behavior.
        try:
            vec_weight = float(os.getenv("RETRIEVER_VECTOR_WEIGHT", "0.8"))
            vec_weight = max(0.0, min(1.0, vec_weight))
        except Exception:
            vec_weight = 0.8

        # Collect raw vector scores
        raw_scores = [float(r.get("score", 0.0) or 0.0) for r in results]
        min_s = min(raw_scores) if raw_scores else 0.0
        max_s = max(raw_scores) if raw_scores else 0.0

        def _norm(v):
            try:
                if max_s - min_s <= 1e-9:
                    return 1.0 if v > 0 else 0.0
                return (v - min_s) / (max_s - min_s)
            except Exception:
                return 0.0

        import re
        q_toks = set(re.findall(r"[A-Za-z0-9_]+", query.lower()))

        for r in results:
            vraw = float(r.get("score", 0.0) or 0.0)
            vnorm = _norm(vraw)
            # lexical tokens from chunk or text
            text = (r.get('chunk') or r.get('text') or '')
            dtoks = set(re.findall(r"[A-Za-z0-9_]+", str(text).lower()))
            if not q_toks and not dtoks:
                lex = 0.0
            else:
                inter = len(q_toks & dtoks)
                union = len(q_toks | dtoks)
                lex = (inter / union) if union > 0 else 0.0
            # combined score
            hybrid = vec_weight * vnorm + (1.0 - vec_weight) * lex
            # store diagnostics
            r['score_raw_vector'] = vraw
            r['score_vector_norm'] = round(vnorm, 6)
            r['score_lexical'] = round(lex, 6)
            r['score'] = hybrid  # replace base score so pref rerank uses hybrid

        # Sort by hybrid score now
        results.sort(key=lambda x: x.get('score', 0.0), reverse=True)

        # Preference-weighted re-ranking
        if preferences and os.getenv("ENABLE_PREF_RERANK", "true").lower() == "true":
            try:
                results = self._apply_preference_rerank(results, preferences)
            except Exception as e:
                logging.getLogger(__name__).warning(f"[PREF_RERANK] failed: {e}")

        return results[:k]

    # --- Semantic Metadata Prefilter ----------------------------------------
    def _semantic_metadata_prefilter(self, query_vector: List[float], use_openai: bool) -> Optional[Dict]:
        """Build a lightweight semantic pre-filter over categorical metadata values.

        Strategy:
          1. For a small set of configured metadata fields, pull distinct values (capped).
          2. Embed each value (cached) and compute cosine similarity to query.
          3. Keep top N per field above similarity threshold.
          4. Return an $or filter to narrow vector search candidate set.

        Env Vars:
          SEMANTIC_META_FIELDS (comma list) default: account_name,owner,industry,region
          SEMANTIC_META_MAX_VALUES (int, per field) default: 120
          SEMANTIC_META_TOP_K (int, per field) default: 3
          SEMANTIC_META_SIM_THRESHOLD (float) default: 0.78

        Returns Mongo match dict or None.
        """
        fields_env = os.getenv("SEMANTIC_META_FIELDS", "account_name,owner,industry,region")
        fields = [f.strip() for f in fields_env.split(',') if f.strip()]
        if not fields:
            return None
        max_values = int(os.getenv("SEMANTIC_META_MAX_VALUES", "120"))
        top_k = int(os.getenv("SEMANTIC_META_TOP_K", "3"))
        sim_threshold = float(os.getenv("SEMANTIC_META_SIM_THRESHOLD", "0.78"))

        collection = self.openai_collection if use_openai else self.gemini_collection

        def cosine(a, b):
            if not a or not b:
                return 0.0
            s = sum(x*y for x,y in zip(a,b))
            na = math.sqrt(sum(x*x for x in a))
            nb = math.sqrt(sum(x*x for x in b))
            if na == 0 or nb == 0:
                return 0.0
            return s / (na * nb)

        or_clauses = []
        for field in fields:
            # Try metadata.field then root field
            candidates = []
            try:
                candidates = collection.distinct(f"metadata.{field}")
            except Exception:
                pass
            if not candidates:
                try:
                    candidates = collection.distinct(field)
                except Exception:
                    candidates = []
            # Normalize & prune
            norm_vals = []
            for v in candidates:
                if not isinstance(v, str):
                    continue
                val = v.strip()
                if not val or len(val) > 60:
                    continue
                norm_vals.append(val)
                if len(norm_vals) >= max_values:
                    break
            if not norm_vals:
                continue
            scored = []
            for val in norm_vals:
                cache_key = f"meta:{field}:{val.lower()}"
                if cache_key in self.embedding_cache:
                    emb = self.embedding_cache[cache_key]
                else:
                    try:
                        emb = [float(x) for x in get_query_embedding(val)]
                        self.embedding_cache[cache_key] = emb
                    except Exception as e:
                        logging.getLogger(__name__).debug(f"[SEM_META] embed fail {val}: {e}")
                        continue
                sim = cosine(query_vector, emb)
                scored.append((sim, val))
            scored.sort(reverse=True, key=lambda x: x[0])
            selected = [v for sim,v in scored if sim >= sim_threshold][:top_k]
            if selected:
                # Prefer metadata.field path if available
                path = f"metadata.{field}"
                or_clauses.append({path: {"$in": selected}})
        if not or_clauses:
            return None
        if len(or_clauses) == 1:
            return or_clauses[0]
        return {"$or": or_clauses}

    # --- Preference Re-ranking ----------------------------------------------
    def _apply_preference_rerank(self, results: List[Dict], preferences: Dict) -> List[Dict]:
        """Adjust scores based on user preference signals.

        Supported preference keys (case-insensitive):
          boostKeywords / focusKeywords: comma or list of important tokens
          focus<FieldPlural>: e.g. focusAccounts, focusOwners, focusIndustries -> list/CSV of values to boost if present in metadata or chunk text
          demoteKeywords: tokens to slightly demote when present

        Env:
          PREF_RERANK_MAX_BOOST (default 0.4) maximum multiplicative boost factor
          PREF_RERANK_KEYWORD_UNIT (default 0.08) per matched keyword partial boost
          PREF_RERANK_FIELD_UNIT (default 0.12) per matched focus field value boost
          PREF_RERANK_DEMOTE_UNIT (default 0.05) per demote keyword penalty
        """
        import re
        norm_prefs = {}
        for k,v in preferences.items():
            norm_prefs[k.lower()] = v
        max_boost = float(os.getenv("PREF_RERANK_MAX_BOOST", "0.4"))
        kw_unit = float(os.getenv("PREF_RERANK_KEYWORD_UNIT", "0.08"))
        field_unit = float(os.getenv("PREF_RERANK_FIELD_UNIT", "0.12"))
        demote_unit = float(os.getenv("PREF_RERANK_DEMOTE_UNIT", "0.05"))

        def _to_list(val):
            if val is None:
                return []
            if isinstance(val, (list, tuple, set)):
                return [str(x).strip() for x in val if str(x).strip()]
            return [s.strip() for s in str(val).split(',') if s.strip()]

        boost_keywords = set(k.lower() for k in _to_list(norm_prefs.get('boostkeywords') or norm_prefs.get('focuskeywords')))
        demote_keywords = set(k.lower() for k in _to_list(norm_prefs.get('demotekeywords')))

        # Collect focus fields (keys starting with focus and more than just 'keywords')
        focus_field_values = {}
        for k,v in norm_prefs.items():
            if k.startswith('focus') and k not in ('focuskeywords',):
                # derive field name: focusAccounts -> accounts
                field = k[5:].lstrip('_').lower()
                focus_field_values[field] = set(x.lower() for x in _to_list(v))

        for r in results:
            base = float(r.get('score', 0))
            text = (r.get('chunk') or r.get('text') or '').lower()
            meta = r.get('metadata') or {}
            boost = 0.0
            # Keyword boosts
            if boost_keywords:
                matches = sum(1 for kw in boost_keywords if kw in text)
                if matches:
                    boost += matches * kw_unit
            # Field value boosts
            for field, vals in focus_field_values.items():
                # look in metadata[field] or metadata[field_singular] or text
                mv = ''
                if isinstance(meta, dict):
                    mv = str(meta.get(field) or '')
                    if not mv and field.endswith('s'):
                        mv = str(meta.get(field[:-1]) or '')
                mv_low = mv.lower()
                matched = [v for v in vals if v in mv_low or v in text]
                if matched:
                    boost += field_unit * len(matched)
            # Demotions
            if demote_keywords:
                demotes = sum(1 for kw in demote_keywords if kw in text)
                if demotes:
                    boost -= demote_unit * demotes
            boost = max(-0.5, min(max_boost, boost))
            adj_score = base * (1 + boost)
            r['score_raw'] = base
            r['score_adjusted'] = adj_score
            r['score_boost'] = boost
        results.sort(key=lambda x: x.get('score_adjusted', x.get('score',0)), reverse=True)
        return results

    # --- Structured metadata filter parser ---
    def _parse_metadata_filter(self, expr: str) -> Optional[Dict]:
        if not expr or expr.lower() in ("none", "all"):
            return None
        import re
        clauses = []
        # Split by commas
        for raw in expr.split(','):
            tok = raw.strip()
            if not tok:
                continue
            neg = tok.startswith('-')
            if neg:
                tok = tok[1:].strip()
            # key:value1|value2
            m_kv = re.match(r'([^:<>=]+)[:=]([^><=]+)$', tok)
            if m_kv:
                field = m_kv.group(1).strip()
                values = [v.strip() for v in m_kv.group(2).split('|') if v.strip()]
                if not values:
                    continue
                if neg:
                    clauses.append({field: {"$nin": values}})
                else:
                    clauses.append({field: {"$in": values}})
                continue
            m_num = re.match(r'([^:<>=]+)(>=|<=|>|<|=)([-+]?\d+(?:\.\d+)?)$', tok)
            if m_num:
                field, op, val = m_num.group(1).strip(), m_num.group(2), float(m_num.group(3))
                mongo_op_map = {">":"$gt","<":"$lt",">=":"$gte","<=":"$lte","=":"$eq"}
                cond = {field: {mongo_op_map[op]: val}}
                if neg:
                    # Negate numeric by wrapping in $not (Mongo $not expects a regex or operator doc)
                    cond = {field: {"$not": {mongo_op_map[op]: val}}}
                clauses.append(cond)
                continue
            # plain substring -> use case-insensitive regex on 'chunk'
            if neg:
                clauses.append({"chunk": {"$not": {"$regex": tok, "$options":"i"}}})
            else:
                clauses.append({"chunk": {"$regex": tok, "$options":"i"}})
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        # Combine with $and (intersection). Adjust if OR desired later.
        return {"$and": clauses}
