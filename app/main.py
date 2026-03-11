from fastapi import FastAPI
from app.core.coreference import resolve_coreference
from app.core.chunker import extract_numbers_from_text, filter_documents_by_metadata
from pydantic import BaseModel
from app.memory.memory_enrichment import get_enriched_memory_context
from app.prompt.token_limiter import format_structured_data
import os
import logging
import re
from typing import Union
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import Response
from fastapi import Body
from pymongo import MongoClient
from datetime import datetime
from typing import Union, Optional, Dict
import os as _os_for_budget  # local import to ensure availability before global constant init
PROMPT_TOKEN_BUDGET = int(_os_for_budget.getenv("PROMPT_TOKEN_BUDGET", "6000"))
MIN_CONTEXT_RESERVED = 800

from app.db.aggregations import (
    count_total,
    count_by_account,
    count_by_opportunity,
    count_by_owner
)
from app.core.coreference import resolve_coreference
from app.services.memory_logger import add_query_to_memory_logger
from app.core.intent_classifier import classify_intent, IntentType  # Intent integration
from app.core.field_parser import parse_query_filters
from app.core.answer_templates import render_template
from app.core.numeric_verifier import verify_numbers
from app.core.fusion_autotune import get_fusion_calibrator
from app.core.diagnostics import record_retrieval_metrics
from app.core.entity_claim_verifier import verify_entities_and_claims
from app.core.security import build_row_level_filter, redact_pii
from app.core.llm import OpenAIEngine
from app.db.memory import search_similar_memories
from app.db.user_preferences import get_user_preferences, upsert_user_preferences, preference_diff
from app.db.user_preferences import auto_tune_preferences
from app.core.embeddings import count_tokens
from app.core.embeddings_fallback import get_query_embedding
from app.core.retriever import Retriever
from app.memory.memory_utils import get_last_chats
from app.services.web_search import fetch_trusted_pages, summarize_external_blocks
from fastapi import FastAPI, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import fitz  # PyMuPDF
import openai
try:
    from pdf2image import convert_from_bytes  # optional
except Exception:
    convert_from_bytes = None  # type: ignore
try:
    import pytesseract  # optional
except Exception:
    pytesseract = None  # type: ignore
try:
    from paddleocr import PaddleOCR  # optional heavy
except Exception:
    PaddleOCR = None  # type: ignore
try:
    from PIL import Image, ImageOps, ImageFilter, ImageEnhance  # optional pre-processing
except Exception:
    Image = ImageOps = ImageFilter = ImageEnhance = None  # type: ignore

MAX_CHUNK_SIZE = 2000  # characters per chunk
TOP_K = 5               # number of relevant chunks to retrieve

import openai
import os
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")


from uuid import uuid4

from fastapi import FastAPI, UploadFile, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import openai
from uuid import uuid4

# Create FastAPI app early so middleware and routers can reference it
app = FastAPI(title="DealdoxAgent API")

@app.get("/health")
def health_check():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/")
def read_root():
    return {"message": "DealdoxAgent API is running"}

from fastapi import Body
from pydantic import BaseModel
from typing import Optional
from fastapi import FastAPI
import re  # Added for regex patterns used in provider noise sanitization


try:
    from app.api.feedback import router as feedback_router
    # Ensure FastAPI app exists before including routers/middleware
    try:
        app
    except NameError:
        # app not defined yet — nothing to do here, continue gracefully
        pass
    app.include_router(feedback_router)
except Exception:
    pass
try:
    from app.api.routes import router as api_router
    # Mount under /api to avoid path collisions with native /memory endpoints
    try:
        app
    except NameError:
        # app not defined yet — nothing to do here, continue gracefully
        pass
    # Mount under /api to avoid path collisions with native /memory endpoints
    app.include_router(api_router, prefix="/api")
except Exception:
    pass


class PDFAnalyzeResponse(BaseModel):
    user_id: str
    session_id: str
    pages: int
    ocr_engine: str
    focus: Optional[str] = None
    analysis: dict
    summary: str
    citations: Optional[list] = None
    readable: Optional[str] = None
    readable_style: Optional[str] = None
class PreferenceUpdate(BaseModel):
    user_id: str
    preferences: Dict
    mode: Optional[str] = "merge"  # or "replace"

from threading import Lock
session_pdf_data = {}
session_pdf_lock = Lock()

class CoreferenceRequest(BaseModel):
    text: str
    context: str = ""

class NumberAccurateRetrievalRequest(BaseModel):
    documents: list
    query: str
mongo_uri = os.getenv("MONGODB_URI")
client = None
db = None
try:
    if mongo_uri:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000, connectTimeoutMS=5000, socketTimeoutMS=30000)
        db = client["dev_db"]
except Exception:
    client = None
    db = None

memory_collection = db["dd_memory_entries_rag"] if db is not None else None
rag_cache_collection = db["rag_cache"] if db is not None else None
user_pref_collection = db["user_preferences"] if db is not None else None
# Simple in-memory cache for retrievals
retrieval_cache = {}  # key -> {"ts": float, "results": list}
quotes_collection = db["dd_quotes"] if db is not None else None
pdf_sessions_collection = db["pdf_sessions"] if db is not None else None
advanced_search_cache = {}  # key -> {"ts": datetime, "results": list}

# Retriever setup
retriever = None
try:
    if db is not None:
        retriever = Retriever(
            openai_collection=db["dd_accounts_chunks"],
            gemini_collection=db["dd_accounts_chunks_gemini"],
            openai_index="vector_index_v2",
            gemini_index="vector_index_gemini_v2"
        )
except Exception:
    retriever = None

# LLM engine
llm_engine = OpenAIEngine()

# FastAPI setup

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://devqa.dealdox.io",
        "https://devqa-api.dealdox.io"
    ],
    # Also allow any localhost/127.0.0.1 port for local FE (e.g., 5173, 8080, 4200)
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    query: Union[str, dict]   # required inside chat

class QueryInput(BaseModel):
    chat: ChatRequest          # 👈 now expects chat.query
    session_id: str
    user_id: str
    access_token: str
    preferences: Optional[Dict] = None  # User preferences (optional)

class QueryResponse(BaseModel):
    answer: str
    user_id: str
    session_id: str
    access_token: str
    chat: Optional[Dict[str, str]] = None  # <-- new field
    context_blocks: Optional[list] = None  # List of context blocks with metadata
    session_history: Optional[list] = None  # List of previous queries/responses for this session
    memory_usage: Optional[int] = None  # Number of memory entries for this session
    feedback: Optional[str] = None  # Thumbs up/down feedback from user
    citations: Optional[list] = None  # Sentence to context alignment annotations
    confidence: Optional[Dict] = None  # Hallucination / grounding metrics
    filters: Optional[Dict] = None  # Applied filter summary

# ===================== Advanced Search Models & Endpoint ===================== #
class AdvancedSearchInput(BaseModel):
    user_id: str
    session_id: str
    query: str
    numbers: Optional[str] = None            # comma separated numeric filters
    date_from: Optional[str] = None          # dd-mm-yyyy
    date_to: Optional[str] = None            # dd-mm-yyyy
    date_field: Optional[str] = None         # explicit single date field override
    relative_range: Optional[str] = None     # e.g. last_7d, last_30d, this_month, prev_month, this_quarter, prev_quarter
    strict_date: Optional[bool] = False      # if true, drop docs with unparsable dates instead of keeping
    tz_offset: Optional[str] = None          # timezone offset e.g. '+05:30', '-0700', or minutes integer
    preferences: Optional[Dict] = None
    access_token: Optional[str] = None

# PDF analyzer router removed

# Report generation request model
class ReportRequest(BaseModel):
    query: str
    session_id: str
    user_id: str
    preferences: Optional[dict] = None
    report_format: str = "summary"  # e.g., summary, table, bullet, recommendations
    report_instructions: Optional[str] = None
    # New optional granular filters (UI can send any subset)
    filters: Optional[dict] = None  # {"account": str, "date_from": str, "date_to": str, "min_amount": float, "max_amount": float, "keyword": str}
    # New optional field for hybrid retrieval
    hybrid_retrieval: Optional[bool] = False


class MemoryContextRequest(BaseModel):
    session_id: str
    user_id: str
    n: int = 5
    weight_recent: int = 2
    preferences: Optional[dict] = None


class StructuredPromptRequest(BaseModel):
    documents: list
    query: str
    preferences: Optional[dict] = None

class MemoryContextRequest(BaseModel):
    session_id: str
    user_id: str
    n: int = 5
    weight_recent: int = 2
    preferences: Optional[dict] = None


class StructuredPromptRequest(BaseModel):
    documents: list
    query: str
    preferences: Optional[dict] = None


def get_answer_from_rag(query_text, user_id=None, session_id=None, access_token=None):
    from app.core.coreference import resolve_coreference

    # Resolve coreference
    resolved_query = query_text
    coref_result = resolve_coreference(query_text, session_id)
    if coref_result:
        import re
        match = re.search(r'Output:\s*"?(.*)"?$', coref_result, re.DOTALL)
        if match:
            resolved_query = match.group(1).strip()
        else:
            resolved_query = coref_result.strip()

    # Retrieve from RAG (non-session / corpus search)
    results = retriever.retrieve(resolved_query, k=15) or []

    # Generate response using llm_engine (default RAG prompt path)
    response = llm_engine.chat(prompt=resolved_query)
    return response

# Utility to build report prompt
def build_report_prompt(query_text, context_blocks=None, preferences=None, report_format="summary", report_instructions=None):
    tone = preferences.get('tone', 'neutral') if preferences else 'neutral'
    detail = preferences.get('detailLevel', 'medium') if preferences else 'medium'
    style = preferences.get('responseStyle', 'default') if preferences else 'default'
    metadata_filter = preferences.get('metadataFilter', 'none') if preferences else 'none'
    prompt = f"""
You are an expert assistant. Generate a {report_format} report in a {tone} tone, with {detail} detail, and {style} formatting. Metadata filter: {metadata_filter}.
"""
    if report_instructions:
        prompt += f"\nAdditional instructions: {report_instructions}\n"
    if context_blocks:
        prompt += "\nContext/Data:\n" + "\n".join(context_blocks)
    prompt += f"\nUser Query: {query_text}\n"
    return prompt

from app.reporting.report_engine import aggregate_quotes, build_report, build_structured_sections


# ===================== Enhanced Personalization Layer ===================== #
# Stronger backend handling for tone, detail level, response style & metadata filter.

def _normalize_prefs(prefs: dict | None) -> dict:
    """Return a dict with canonical, lowercase keys & lowercase string values.

    Also generates normalized aliases so downstream lookups succeed:
      detailLevel/detail_level -> detaillevel
      responseStyle/response_style/style -> responsestyle
      metadataFilter/metadata_filter -> metadatafilter
    Original keys preserved only if they don't collide; canonical wins in lookup usage.
    """
    if not prefs:
        return {}
    norm = {}
    for k, v in prefs.items():
        val = v.strip().lower() if isinstance(v, str) else v
        # Build canonical key: lowercase alphanumerics only
        base = ''.join(ch for ch in k.lower() if ch.isalnum() or ch == '_')
        # Unify common variants
        if base in ("detaillevel", "detail_level"):
            base = "detaillevel"
        elif base in ("responsestyle", "response_style", "style"):
            base = "responsestyle"
        elif base in ("metadatafilter", "metadata_filter"):
            base = "metadatafilter"
        elif base in ("tone",):
            base = "tone"
        norm[base] = val
    return norm

TONE_MAP = {
    "neutral": "Use objective, professional language.",
    "friendly": "Use warm, approachable language while staying professional.",
    "executive": "Use concise, high-level business language focused on insights.",
    "analytical": "Use precise, data-driven language with clear reasoning.",
    "persuasive": "Use confident, benefit-oriented language without exaggeration."
}

DETAIL_MAP = {
    # blocks: max context blocks; words: target answer length guidance
    "low": {"blocks": 4, "words": 80},
    "medium": {"blocks": 8, "words": 160},
    "high": {"blocks": 12, "words": 300},
    "deep": {"blocks": 16, "words": 450}
}

STYLE_MAP = {
    "default": "Provide a clear, well-structured prose answer.",
    "bullets": "Respond ONLY as concise bullet points (one idea per bullet). No prose paragraphs.",
    "summary": "Provide a concise executive summary followed by 1-2 key insights.",
    "table": "If feasible, include a markdown table summarizing key fields before a brief explanation.",
    "steps": "Provide a numbered step-by-step list to address the request."
}

def _filter_context_by_metadata(context_blocks: list[str], metadata_filter: str) -> list[str]:
    """Advanced metadata-aware filtering.

    Supported syntax in metadata_filter string (comma or space separated):
      keyword                -> substring include (OR logic across include terms)
      key:value1|value2      -> match if any value appears in extracted key-value pairs OR raw block text
      -keyword               -> exclude blocks containing substring
      -key:value             -> exclude blocks whose key has that value
      key>10 / key>=5        -> numeric comparison against value parsed from block metadata lines ("Key: 12")
      key<100 / key<=20      -> numeric comparisons

    Extraction of metadata from blocks:
      Lines like `Field: value` or `field=value` become key/value (normalized lowercase key).

    Semantics:
      1. If only exclude tokens provided, all blocks retained except those matching any exclude.
      2. If include tokens exist, a block must satisfy at least one include AND no exclude.
      3. Fallback to original blocks if filter eliminates all.
    """
    if not context_blocks or not metadata_filter or metadata_filter.lower() in ("none", "all"):
        return context_blocks
    import re, logging

    # Split on commas or whitespace while preserving comparison operators
    raw_tokens = [t.strip() for part in metadata_filter.split(',') for t in part.split() if t.strip()]
    if not raw_tokens:
        return context_blocks

    def parse_token(tok: str):
        neg = tok.startswith('-')
        core = tok[1:] if neg else tok
        # key:value1|value2
        m_kv = re.match(r'([^:<>=]+)[:=]([^><=]+)$', core)
        if m_kv:
            key = m_kv.group(1).strip().lower()
            vals = [v.strip().lower() for v in m_kv.group(2).split('|') if v.strip()]
            return {"exclude": neg, "type": "kv", "key": key, "values": vals}
        # numeric comparisons key>=10 etc
        m_num = re.match(r'([^:<>=]+)(>=|<=|>|<|=)([-+]?\d+(?:\.\d+)?)$', core)
        if m_num:
            key = m_num.group(1).strip().lower()
            op = m_num.group(2)
            val = float(m_num.group(3))
            return {"exclude": neg, "type": "num", "key": key, "op": op, "value": val}
    # plain word
        return {"exclude": neg, "type": "substr", "value": core.lower()}

    tokens = [parse_token(t) for t in raw_tokens]
    include_tokens = [t for t in tokens if not t['exclude']]
    exclude_tokens = [t for t in tokens if t['exclude']]

    # Pre-extract key/value metadata from each block
    kv_pattern = re.compile(r'^\s*([A-Za-z0-9_\- ]{1,40})\s*[:=]\s*(.+)$', re.MULTILINE)

    def extract_meta(block: str):
        meta = {}
        for m in kv_pattern.finditer(block):
            k = m.group(1).strip().lower()
            v = m.group(2).strip().lower()
            # Stop at first sentence delimiter for value simplification
            v_simple = v.split('\n')[0]
            meta[k] = v_simple
        return meta

    def match_token(block: str, meta: dict, tok: dict) -> bool:
        b_low = block.lower()
        if tok['type'] == 'substr':
            return tok['value'] in b_low
        if tok['type'] == 'kv':
            val = meta.get(tok['key'])
            if val:
                return any(v in val for v in tok['values'])
            # fallback to substring search in block
            return any(v in b_low for v in tok['values'])
        if tok['type'] == 'num':
            val_raw = meta.get(tok['key'])
            if not val_raw:
                return False
            # extract leading number
            m = re.match(r'[-+]?\d+(?:\.\d+)?', val_raw)
            if not m:
                return False
            try:
                num = float(m.group(0))
            except ValueError:
                return False
            op = tok['op']
            target = tok['value']
            return (
                (op == '>' and num > target) or
                (op == '<' and num < target) or
                (op == '>=' and num >= target) or
                (op == '<=' and num <= target) or
                (op == '=' and num == target)
            )
        return False

    filtered = []
    for cb in context_blocks:
        meta = extract_meta(cb)
        # Exclusions first
        if exclude_tokens and any(match_token(cb, meta, t) for t in exclude_tokens):
            continue
        if include_tokens:
            if any(match_token(cb, meta, t) for t in include_tokens):
                filtered.append(cb)
        else:
            # No includes -> keep unless excluded
            filtered.append(cb)

    if not filtered:
        logging.getLogger(__name__).info("[META_FILTER] All blocks filtered out; returning original set as fallback")
        return context_blocks
    logging.getLogger(__name__).debug(
        f"[META_FILTER] Applied filter='{metadata_filter}' includes={len(include_tokens)} excludes={len(exclude_tokens)} -> kept {len(filtered)}/{len(context_blocks)}"
    )
    return filtered

def _truncate_context(context_blocks: list[str], max_blocks: int) -> list[str]:
    if not context_blocks:
        return []
    return context_blocks[:max_blocks]


def get_answer_from_rag(query_text, user_id=None, session_id=None, access_token=None):
    from app.core.coreference import resolve_coreference

    # Resolve coreference
    resolved_query = query_text
    coref_result = resolve_coreference(query_text, session_id)
    if coref_result:
        import re
        match = re.search(r'Output:\s*"?(.*)"?$', coref_result, re.DOTALL)
        if match:
            resolved_query = match.group(1).strip()
        else:
            resolved_query = coref_result.strip()

    # Retrieve from RAG (non-session / corpus search)
    results = retriever.retrieve(resolved_query, k=15) or []

    # Generate response using llm_engine (default RAG prompt path)
    response = llm_engine.chat(prompt=resolved_query)
    return response

def build_llm_prompt(query_text: str, context_blocks: list[str] | None = None, preferences: dict | None = None):
    prefs = _normalize_prefs(preferences)

    tone_key = prefs.get('tone', 'neutral')
    detail_key = prefs.get('detaillevel', prefs.get('detail_level', prefs.get('detail', 'medium')))
    style_key = prefs.get('responsestyle', prefs.get('response_style', prefs.get('style', 'default')))
    metadata_filter = prefs.get('metadatafilter', prefs.get('metadata_filter', 'none'))

    tone_instruction = TONE_MAP.get(tone_key, TONE_MAP['neutral'])
    detail_profile = DETAIL_MAP.get(detail_key, DETAIL_MAP['medium'])
    style_instruction = STYLE_MAP.get(style_key, STYLE_MAP['default'])

    # Filter + truncate context blocks
    context_blocks = context_blocks or []
    pre_filter_len = len(context_blocks)
    context_blocks = _filter_context_by_metadata(context_blocks, metadata_filter)
    post_filter_len = len(context_blocks)
    context_blocks = _truncate_context(context_blocks, detail_profile['blocks'])
    final_len = len(context_blocks)

    # Build constraint section
    constraints = [
        f"Tone: {tone_instruction}",
        f"Detail: Target ~{detail_profile['words']} words (be concise if info is limited).",
        f"Style: {style_instruction}",
    ]
    if metadata_filter and metadata_filter not in ("none", "all"):
        constraints.append(f"Metadata Filter Applied: {metadata_filter} (matched {post_filter_len}/{pre_filter_len} blocks; using first {final_len})")
    else:
        constraints.append(f"Context Blocks Used: {final_len}")

    system_header = (
        "You are a domain-aware assistant. Obey all constraints. If answer not derivable, say you don't know."
    )

    base_constraints = "\nConstraints:\n" + "\n".join(f"- {c}" for c in constraints)
    # We'll add context blocks progressively to respect token budget
    chosen_blocks = []
    # Provenance / intent transparency (optional future extension: pass explicit sources)
    provenance_lines = []
    if os.getenv("PROMPT_ADD_PROVENANCE","true").lower() == "true":
        # Lightweight summary, final redaction handled earlier
        provenance_lines.append(f"Provenance: {pre_filter_len} context blocks before filtering; {post_filter_len} after filter; using top {detail_profile['blocks']} (final clipped to fit tokens).")
        if metadata_filter and metadata_filter not in ("none","all"):
            provenance_lines.append(f"Filter Applied: {metadata_filter}")
    provenance_section = ("\n" + "\n".join(provenance_lines) + "\n") if provenance_lines else "\n"
    prompt_without_context = f"{system_header}\n{base_constraints}{provenance_section}\nUser Question:\n{query_text}\n\nAnswer:"

    # Fast path if no context
    if not context_blocks:
        prompt = prompt_without_context
        logging.getLogger(__name__).debug(
            f"[PERSONALIZATION] tone={tone_key} detail={detail_key} style={style_key} metadata_filter={metadata_filter} blocks_pre={pre_filter_len} blocks_post={post_filter_len} blocks_used=0"
        )
        return prompt

    # Token-aware assembly
    def _count(text: str) -> int:
        try:
            return count_tokens(text)
        except Exception:
            # Rough fallback heuristic: ~4 chars per token
            return max(1, len(text) // 4)

    budget = PROMPT_TOKEN_BUDGET
    reserve_for_answer = min(max(200, MIN_CONTEXT_RESERVED), max(0, budget // 4))  # heuristic reserve
    # Start with base tokens
    base_tokens = _count(prompt_without_context)
    remaining = budget - reserve_for_answer - base_tokens
    if remaining <= 0:
        # No space for context, return base prompt
        logging.getLogger(__name__).warning("[PERSONALIZATION_TRIM] No token room for context; returning base prompt only")
        logging.getLogger(__name__).debug(
            f"[PERSONALIZATION] tone={tone_key} detail={detail_key} style={style_key} metadata_filter={metadata_filter} blocks_pre={pre_filter_len} blocks_post={post_filter_len} blocks_used=0"
        )
        return prompt_without_context

    accumulated = base_tokens
    for cb in context_blocks:
        block_text = f"\n\n{cb}"
        block_tokens = _count(block_text)
        if accumulated + block_tokens + reserve_for_answer > budget:
            break
        chosen_blocks.append(cb)
        accumulated += block_tokens

    blocks_used = len(chosen_blocks)
    # If nothing fit, force-truncate first block
    if not chosen_blocks and context_blocks:
        first = context_blocks[0]
        # Approx tokens -> characters scaling
        allowed_tokens = max(0, budget - base_tokens - reserve_for_answer)
        allowed_chars = allowed_tokens * 4  # heuristic
        truncated = first[:allowed_chars]
        chosen_blocks.append(truncated + ("..." if len(truncated) < len(first) else ""))
        blocks_used = 1
        logging.getLogger(__name__).warning(
            f"[PERSONALIZATION_TRIM] Forced truncate of first context block to fit budget (chars={allowed_chars})"
        )

    # Adaptive overflow summarization of remaining blocks (one-by-one feature step)
    overflow_blocks = []
    if blocks_used < final_len and final_len < len(context_blocks):
        overflow_blocks = context_blocks[blocks_used:final_len]
    elif blocks_used < len(context_blocks):
        overflow_blocks = context_blocks[blocks_used:]

    summary_block = None
    if overflow_blocks and os.getenv("ENABLE_CONTEXT_SUMMARY", "true").lower() == "true":
        # Heuristic sentence extraction
        import re
        detail_to_sentences = {"low":3, "medium":5, "high":8, "deep":12}
        summary_limit = detail_to_sentences.get(detail_key, 5)
        sentences = []
        for ob in overflow_blocks:
            # take first sentence-like fragment
            frags = re.split(r'(?<=[.!?])\s+', ob.strip())
            if frags and frags[0]:
                sentences.append(frags[0].strip())
            if len(sentences) >= summary_limit:
                break
        if sentences:
            summary_text = " ".join(sentences)[:600]
            summary_block_candidate = f"Overflow Summary (condensed {len(overflow_blocks)} trimmed blocks):\n{summary_text}"
            # Check token fit
            extra_tokens = _count("\n\n" + summary_block_candidate)
            if accumulated + extra_tokens + reserve_for_answer <= budget:
                summary_block = summary_block_candidate
                chosen_blocks.append(summary_block)
                blocks_used += 1
                logging.getLogger(__name__).info(
                    f"[PERSONALIZATION_SUMMARY] Added overflow summary for {len(overflow_blocks)} blocks as 1 block"
                )
            else:
                logging.getLogger(__name__).info(
                    "[PERSONALIZATION_SUMMARY] Not enough budget to include overflow summary"
                )

    context_section = ""
    if chosen_blocks:
        context_section = "\nContext:\n" + "\n\n".join(chosen_blocks)

    prompt = f"{system_header}\n{base_constraints}{context_section}\n\nUser Question:\n{query_text}\n\nAnswer:"
    logging.getLogger(__name__).debug(
        f"[PERSONALIZATION] tone={tone_key} detail={detail_key} style={style_key} metadata_filter={metadata_filter} blocks_pre={pre_filter_len} blocks_post={post_filter_len} blocks_used={blocks_used} tokens_total={_count(prompt)} budget={budget} reserve={reserve_for_answer}"
    )
    if blocks_used < final_len:
        logging.getLogger(__name__).info(
            f"[PERSONALIZATION_TRIM] Trimmed context blocks from {final_len} to {blocks_used} to satisfy token budget"
        )
    return prompt


def enforce_response_style(raw_answer: str, preferences: dict | None) -> str:
    if not raw_answer:
        return raw_answer
    prefs = _normalize_prefs(preferences or {})
    style = prefs.get('responsestyle', prefs.get('response_style', prefs.get('style', 'default')))
    if style == 'bullets':
        lines = [l.strip('- ') for l in raw_answer.splitlines() if l.strip()]
        return "\n".join(f"- {l}" for l in lines)
    if style == 'steps':
        lines = [l.strip() for l in raw_answer.splitlines() if l.strip()]
        out = []
        for i, l in enumerate(lines, 1):
            out.append(f"{i}. {l.lstrip(str(i)+'. ').strip()}")
        return "\n".join(out)
    if style == 'summary':
        parts = [p.strip() for p in raw_answer.split('\n\n') if p.strip()]
        if len(parts) <= 1:
            return raw_answer
        head = parts[0]
        rest = []
        for p in parts[1:]:
            rest.extend([s.strip() for s in p.split('.') if s.strip()])
        bullets = "\n".join(f"- {s}." for s in rest[:5])
        return head + "\n\nKey Points:\n" + bullets
    if style == 'table':
        if '|' in raw_answer and '---' in raw_answer:
            return raw_answer
        rows = []
        for line in raw_answer.splitlines():
            if ':' in line and len(line.split(':',1)[0]) < 40:
                k,v = line.split(':',1)
                rows.append((k.strip(), v.strip()))
        if rows:
            header = "| Field | Value |\n|---|---|"
            table = "\n".join([header] + [f"| {k} | {v} |" for k,v in rows[:12]])
            return table + "\n\n" + raw_answer
    return raw_answer

def _enforce_answer_length(answer: str, preferences: dict | None) -> str:
    if not answer:
        return answer
    prefs = _normalize_prefs(preferences or {})
    detail_key = prefs.get('detaillevel', prefs.get('detail_level', prefs.get('detail', 'medium')))
    profile = DETAIL_MAP.get(detail_key, DETAIL_MAP['medium'])
    target_words = profile['words']
    # Count words
    words = answer.split()
    if len(words) <= target_words * 1.6:  # within tolerance
        return answer
    # Strategy: keep first meaningful section + key bullets / sentences until target
    import re
    # Split into sentences (simple heuristic)
    sentences = re.split(r'(?<=[.!?])\s+', answer.strip())
    trimmed = []
    count = 0
    limit = max(int(target_words * 1.05), target_words)  # small allowance
    for s in sentences:
        w = len(s.split())
        if count + w > limit:
            break
        trimmed.append(s)
        count += w
    # Fallback if nothing captured
    if not trimmed:
        trimmed = words[:target_words]
        return " ".join(trimmed) + "..."
    concise = " ".join(trimmed).strip()
    if not concise.endswith(('.', '!', '?')):
        concise += '.'
    concise += f"\n\n[Answer shortened to ~{count} words from {len(words)} for requested detail level '{detail_key}']"
    logging.getLogger(__name__).info(
        f"[ANSWER_TRIM] detail={detail_key} target={target_words} original_words={len(words)} final_words={count}"
    )
    return concise

def finalize_answer(raw_answer: str, preferences: dict | None) -> str:
    styled = enforce_response_style(raw_answer, preferences)
    limited = _enforce_answer_length(styled, preferences)
    return limited

# ===================== Citation Alignment / Hallucination Guard ===================== #
def _split_answer_sentences(answer: str) -> list:
    import re
    lines = [l.strip() for l in answer.split('\n') if l.strip()]
    sentences = []
    for l in lines:
        if l.startswith('- ') or l[:2].isdigit():
            sentences.append(l)
        else:
            parts = re.split(r'(?<=[.!?])\s+', l)
            for p in parts:
                if p.strip():
                    sentences.append(p.strip())
    return sentences

def align_answer_with_context(answer: str, context_blocks: list[str], out_of_domain: bool = False, include_telemetry: bool | None = None):
    """Annotate answer sentences with context block references using n-gram overlap.

    If out_of_domain or overwhelming majority unverified, suppress tagging to avoid noise.
    """
    if not answer or not context_blocks:
        return answer, []
    import re

    def ngrams(tokens, n):
        return {" ".join(tokens[i:i+n]) for i in range(len(tokens)-n+1)} if len(tokens) >= n else set()

    def tokenize(text):
        return re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]+", text.lower())

    # Precompute features per context block
    block_features = []
    for cb in context_blocks:
        toks = tokenize(cb)
        block_features.append({
            "uni": set(toks),
            "bi": ngrams(toks,2),
            "tri": ngrams(toks,3)
        })

    sentences = _split_answer_sentences(answer)
    advisory_pattern = re.compile(r"(consult|authoritative sources|cdc|who|world health organization|centers for disease control)", re.IGNORECASE)
    # Threshold configuration via env
    import os as _os_thr
    # Step C: lower sensitivity (so fewer sentences become 'unverified')
    # Softer defaults: lower base/advisory thresholds and require no bi/tri match by default.
    base_threshold = int(_os_thr.getenv("CITATION_BASE_THRESHOLD_SCORE", "4"))
    advisory_threshold = int(_os_thr.getenv("CITATION_ADVISORY_THRESHOLD_SCORE", "3"))
    min_bigram = int(_os_thr.getenv("CITATION_MIN_BIGRAM", "0"))
    min_trigram = int(_os_thr.getenv("CITATION_MIN_TRIGRAM", "0"))
    annotations = []
    augmented = []
    telemetry_counts = {"high":0, "medium":0, "unverified":0}
    token_masks = []  # list of {idxs:set[int], ratio:float}
    for s in sentences:
        toks = tokenize(s)
        s_uni = set(toks)
        s_bi = ngrams(toks,2)
        s_tri = ngrams(toks,3)
        best_idx = -1
        best_score = 0
        best_detail = {"uni":0,"bi":0,"tri":0}
        for i, feats in enumerate(block_features):
            uni_ov = len(s_uni & feats["uni"])
            bi_ov = len(s_bi & feats["bi"])
            tri_ov = len(s_tri & feats["tri"])
            score = uni_ov + bi_ov*3 + tri_ov*5
            if score > best_score:
                best_score = score
                best_idx = i
                best_detail = {"uni": uni_ov, "bi": bi_ov, "tri": tri_ov}
        # Threshold logic
        threshold_score = advisory_threshold if advisory_pattern.search(s) else base_threshold
        qualifies = (
            best_idx >= 0 and (
                best_detail["bi"] >= min_bigram or
                best_detail["tri"] >= min_trigram or
                best_score >= threshold_score
            )
        )
        if qualifies:
            # Confidence tier heuristics (Step D: we output confidence label instead of block tag)
            if best_detail["tri"] > 0 or best_score >= threshold_score + 6:  # slightly easier high tier
                confidence_tier = "high"
            elif best_score >= threshold_score:
                confidence_tier = "medium"
            else:
                confidence_tier = "low"
            # Build a rough token grounding mask against the best block
            best_block_tokens = set(tokenize(context_blocks[best_idx] if 0 <= best_idx < len(context_blocks) else ''))
            grounded_token_idx = {i for i,t in enumerate(toks) if t in best_block_tokens}
            token_ratio = (len(grounded_token_idx)/max(1,len(toks))) if toks else 0.0
            token_masks.append({"idxs": sorted(list(grounded_token_idx)), "ratio": round(token_ratio,3)})
            # Include a simple citation tag like [C#] for UI/tests while keeping confidence label
            augmented.append(f"{s} (confidence: {confidence_tier}) [C{best_idx+1}]")
            annotations.append({
                "sentence": s[:160],
                "block": best_idx+1,
                "score": best_score,
                **best_detail,
                "confidence": confidence_tier
            })
            if confidence_tier in ("high","medium"):
                telemetry_counts[confidence_tier] += 1
            else:
                telemetry_counts["unverified"] += 1
        else:
            if advisory_pattern.search(s):
                augmented.append(f"{s} (confidence: info)")
                annotations.append({
                    "sentence": s[:160],
                    "block": None,
                    "score": best_score,
                    "status": "advisory",
                    "confidence": "info"
                })
            else:
                # Step A: suppress user-facing UNVERIFIED tag
                augmented.append(f"{s} (confidence: low)")
                annotations.append({
                    "sentence": s[:160],
                    "block": None,
                    "score": best_score,
                    "status": "unverified",
                    "confidence": "low"
                })
                telemetry_counts["unverified"] += 1
    # Suppression conditions
    unverified = sum(1 for a in annotations if a.get("status") == "unverified")
    if include_telemetry is None:
        include_telemetry = _os_thr.getenv("CITATION_TELEMETRY_RETURN", "false").lower() == "true"
    if out_of_domain or (annotations and unverified/len(annotations) > 0.85):
        telemetry = {
            "total_sentences": len(sentences),
            "grounded_high": telemetry_counts["high"],
            "grounded_medium": telemetry_counts["medium"],
            "unverified": telemetry_counts["unverified"],
            "threshold_score": base_threshold,
            "advisory_threshold": advisory_threshold,
            "min_bigram": min_bigram,
            "min_trigram": min_trigram,
            "suppressed": True
        }
        return (answer, [], telemetry) if include_telemetry else (answer, [])
    # Step A: hide aggregate verification line from user output (telemetry retained internally)
    # Aggregate grounded token ratio across sentences
    grounded_ratio = 0.0
    if token_masks:
        grounded_ratio = round(sum(m.get('ratio',0.0) for m in token_masks)/len(token_masks), 3)
    telemetry = {
        "total_sentences": len(sentences),
        "grounded_high": telemetry_counts["high"],
        "grounded_medium": telemetry_counts["medium"],
        "unverified": telemetry_counts["unverified"],
        "threshold_score": base_threshold,
        "advisory_threshold": advisory_threshold,
        "min_bigram": min_bigram,
        "min_trigram": min_trigram,
        "suppressed": False,
        "token_masks": token_masks,
        "grounded_token_ratio": grounded_ratio
    }
    # Step B: internal telemetry logging only (no user-facing tags)
    try:
        import logging as _logging
        _logging.getLogger(__name__).debug(
            f"[VERIFY_TELEMETRY] grounded_high={telemetry['grounded_high']} grounded_medium={telemetry['grounded_medium']} "
            f"unverified={telemetry['unverified']} suppressed={telemetry['suppressed']} threshold_score={telemetry['threshold_score']}"
        )
    except Exception:
        pass
    return ("\n".join(augmented), annotations, telemetry) if include_telemetry else ("\n".join(augmented), annotations)

# =============== Provider Noise Sanitization & Domain Handling ================= #
PROVIDER_NOISE_PATTERNS = [
    re.compile(r"gpt balance", re.IGNORECASE),
    re.compile(r"using free models", re.IGNORECASE),
    re.compile(r"accuracy will be less", re.IGNORECASE)
]

def sanitize_provider_noise(answer: str) -> str:
    if not answer:
        return answer
    cleaned_lines = []
    for line in answer.splitlines():
        if any(p.search(line) for p in PROVIDER_NOISE_PATTERNS):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()

DOMAIN_KEYWORDS = {"quote","quotes","account","accounts","opportunity","opportunities","deal","deals","revenue","price","pricing","owner","opp","opps","pipeline","quoteid","opportunityid"}

GREETING_WORDS = {"hi","hello","hey","hola","yo","hii","heyy"}

def is_greeting(query: str) -> bool:
    if not query:
        return False
    import re
    tokens = re.findall(r"[a-zA-Z0-9]+", query.lower())
    if not tokens:
        return False
    if len(tokens) <= 3 and all(t in GREETING_WORDS for t in tokens):
        return True
    return False

def build_greeting_response(query: str) -> str:
    return "Hello! How can I assist you today?"

# Identity query detection (e.g., "who are you")
IDENTITY_PATTERNS = [
    re.compile(r"who\s+are\s+you\??", re.IGNORECASE),
    re.compile(r"what\s+are\s+you\??", re.IGNORECASE),
    re.compile(r"who\s+is\s+this\??", re.IGNORECASE),
]

def is_identity_query(query: str) -> bool:
    if not query:
        return False
    for p in IDENTITY_PATTERNS:
        if p.search(query.strip()):
            return True
    return False

def detect_out_of_domain(query: str, context_blocks: list[str]) -> bool:
    if not query:
        return False
    import re
    # Short-circuit for simple greetings so they are always answered politely
    if is_greeting(query):
        return False
    q_tokens = set(re.findall(r"[a-zA-Z0-9]+", query.lower()))
    # Treat tokens ending with 'opp' (shorthand for opportunity) as domain indicators
    if q_tokens & DOMAIN_KEYWORDS or any(t.endswith('opp') for t in q_tokens):
        return False  # intersects domain
    # gather context tokens
    ctx_tokens = set()
    for cb in context_blocks[:8]:
        for tok in re.findall(r"[a-zA-Z0-9]+", cb.lower()):
            ctx_tokens.add(tok)
    # If query tokens have no overlap with context tokens (beyond stop words) treat as out-of-domain
    overlap = q_tokens & ctx_tokens
    # ignore generic stop tokens
    stop = {"the","a","an","and","or","of","to","in","for","on","with","is","are","be"}
    overlap = {o for o in overlap if o not in stop}
    return len(overlap) == 0

def build_domain_refusal(query: str) -> str:
    return (
        "I couldn't find enough internal data to answer that. "
        "Try adding more identifiers: account name, opportunity stage, approximate amount, or a date range. "
        "You can also apply filters (account, date_from/date_to, min_amount). If the entity is new, ingest or sync it first."
    )

# --- Minimal hallucination metrics stub (prevents runtime warning); can be expanded later ---
def _compute_hallucination_metrics(answer: str, annotations: list | None, context_blocks: list[str] | None):
    """Compute lightweight grounding metrics without heavy NLP.

    Returns:
      grounded_segments: int
      grounded_ratio: grounded_segments / max(1, total_sentences)
      numeric_overlaps: count of numbers in answer that also appear in any context block
      confidence_histogram: counts per confidence tier from annotations
      token_grounding_proxy: fraction of unique answer tokens that exist in any context block
      context_blocks: int
      len_answer: int
    """
    try:
        import re
        # Sentence split (simple)
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', (answer or '').strip()) if s.strip()]
        total_sentences = len(sentences)
        grounded_segments = 0
        conf_hist = {"high":0, "medium":0, "low":0, "info":0}
        if annotations:
            grounded_segments = sum(1 for a in annotations if isinstance(a, dict) and a.get('confidence') in ("high","medium","low","info"))
            for a in annotations:
                if isinstance(a, dict):
                    c = str(a.get('confidence') or '').lower()
                    if c in conf_hist:
                        conf_hist[c] += 1
        # Numeric overlaps
        nums_ans = set(re.findall(r"[-+]?\d+(?:\.\d+)?", answer or ''))
        nums_ctx = set()
        for cb in (context_blocks or [])[:20]:
            nums_ctx.update(re.findall(r"[-+]?\d+(?:\.\d+)?", cb))
        numeric_overlaps = len(nums_ans & nums_ctx)
        # Token grounding proxy
        def toks(s: str):
            return set(re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]+", s.lower()))
        ans_tokens = toks(answer or '')
        ctx_tokens = set()
        for cb in (context_blocks or [])[:20]:
            ctx_tokens |= toks(cb)
        # remove stop-ish small tokens
        ans_tokens = {t for t in ans_tokens if len(t) > 2}
        token_grounding_proxy = 0.0
        if ans_tokens:
            token_grounding_proxy = len(ans_tokens & ctx_tokens) / float(len(ans_tokens))
        grounded_ratio = (grounded_segments / float(max(1,total_sentences))) if total_sentences else 0.0
        # Simple risk level heuristic
        risk_level = "low"
        if grounded_ratio < 0.3 or (grounded_ratio < 0.5 and numeric_overlaps == 0):
            risk_level = "high"
        elif grounded_ratio < 0.6:
            risk_level = "medium"
        # Lexical novelty: 1 - token grounding proxy (bounded [0,1])
        lexical_novelty_ratio = round(1.0 - min(1.0, max(0.0, token_grounding_proxy)), 3)
        return {
            "grounded_segments": grounded_segments,
            "grounded_sentences": grounded_segments,  # backward/alias for tests
            "grounded_ratio": grounded_ratio,
            "numeric_overlaps": numeric_overlaps,
            "confidence_histogram": conf_hist,
            "token_grounding_proxy": round(token_grounding_proxy, 3),
            "lexical_novelty_ratio": lexical_novelty_ratio,
            "context_blocks": len(context_blocks or []),
            "len_answer": len(answer or ''),
            "risk_level": risk_level
        }
    except Exception:
        return {"error": "metrics_failed"}

# --- Heuristic noise detection for low-value HTML/style boilerplate chunks ---
NOISE_PATTERNS = [
    re.compile(r"font-family:\s*calibri", re.IGNORECASE),
    re.compile(r"<div|<span|</p>", re.IGNORECASE),
    re.compile(r"color:#", re.IGNORECASE),
    re.compile(r"\{\s*margin", re.IGNORECASE)
]

def _is_noise_chunk(text: str) -> bool:
    if not text:
        return True
    # If >40% of characters are markup/symbols or >3 noise patterns match -> treat as noise
    markup_chars = sum(1 for c in text if c in "<>/{};#=")
    ratio = markup_chars / max(1, len(text))
    pattern_hits = sum(1 for p in NOISE_PATTERNS if p.search(text))
    return ratio > 0.4 or pattern_hits >= 3

# ===================== Multi-pass Summarization & Adaptive Re-query =============== #
def _adaptive_requery_if_sparse(query: str, results: list, retriever, preferences: dict | None):
    """If too few results, expand query heuristically and retrieve again.
    Env:
      ADAPTIVE_REQUERY_MIN_BLOCKS (default 3)
      ADAPTIVE_REQUERY_EXPANSION_TERMS (default 'summary insights metrics performance trend')
    """
    try:
        min_blocks = int(os.getenv("ADAPTIVE_REQUERY_MIN_BLOCKS", "3"))
        if len(results) >= min_blocks:
            return results
        expansion_terms = os.getenv("ADAPTIVE_REQUERY_EXPANSION_TERMS", "summary insights metrics performance trend")
        expanded_query = f"{query} {expansion_terms}"[:1200]
        more = retriever.retrieve(expanded_query, k=20, preferences=preferences) or []
        # Deduplicate by chunk text hash
        seen = set()
        merged = []
        for r in results + more:
            txt = (r.get('chunk') or r.get('text') or '')[:400]
            h = hash(txt)
            if h in seen:
                continue
            seen.add(h)
            merged.append(r)
        logging.getLogger(__name__).info(f"[ADAPTIVE_REQUERY] Expanded query added {len(merged)-len(results)} new results")
        return merged
    except Exception as e:
        logging.getLogger(__name__).warning(f"[ADAPTIVE_REQUERY] failed: {e}")
        return results


def _get_pdf_session_text(user_id: str | None, session_id: str | None):
    """Return PDF text for a session if available, otherwise None."""
    if not session_id or not user_id:
        return None
    # Try MongoDB first (robust across processes)
    try:
        if 'pdf_sessions_collection' in globals() and pdf_sessions_collection:
            doc = pdf_sessions_collection.find_one({"session_id": session_id, "user_id": user_id})
            if doc and doc.get("pdf_text"):
                return doc.get("pdf_text")
    except Exception:
        pass
    # Fallback to in-memory session cache (same-process)
    try:
        tmp = session_pdf_data.get(session_id) if 'session_pdf_data' in globals() else None
        if tmp and tmp.get("user_id") == user_id and tmp.get("pdf_text"):
            return tmp.get("pdf_text")
    except Exception:
        pass
    return None

def _multi_pass_cluster_summarize(results: list, preferences: dict | None):
    """Cluster many context blocks and create summary blocks to reduce token use.

    Applied when number of results exceeds MULTIPASS_CLUSTER_MIN_BLOCKS.

    Env:
      ENABLE_MULTI_PASS_SUMMARY (default 'true')
      MULTIPASS_CLUSTER_MIN_BLOCKS (default 14)
      MULTIPASS_CLUSTER_SIM_THRESHOLD (default 0.82)
      MULTIPASS_CLUSTER_MAX (default 5)
    """
    if os.getenv("ENABLE_MULTI_PASS_SUMMARY", "true").lower() != "true":
        return results, None
    try:
        min_blocks = int(os.getenv("MULTIPASS_CLUSTER_MIN_BLOCKS", "14"))
        if len(results) < min_blocks:
            return results, None
        sim_threshold = float(os.getenv("MULTIPASS_CLUSTER_SIM_THRESHOLD", "0.82"))
        max_clusters = int(os.getenv("MULTIPASS_CLUSTER_MAX", "5"))
        # Prepare texts
        texts = []
        for r in results:
            txt = r.get('chunk') or r.get('text') or ''
            if not txt:
                continue
            texts.append(txt[:1500])
        if len(texts) < min_blocks:
            return results, None
        # Embed each block (reuse query embedding function for simplicity)
        from app.core.embeddings_fallback import get_query_embedding
        embeddings = []
        for t in texts:
            try:
                emb = [float(x) for x in get_query_embedding(t)]
            except Exception:
                emb = []
            embeddings.append(emb)
        # Cosine util
        import math
        def cos(a,b):
            if not a or not b:
                return 0.0
            sa = sum(x*x for x in a); sb = sum(x*x for x in b)
            if sa<=0 or sb<=0:
                return 0.0
            return sum(x*y for x,y in zip(a,b)) / math.sqrt(sa*sb)
        assigned = [-1]*len(texts)
        clusters = []  # list of lists of indices
        for i, emb in enumerate(embeddings):
            if assigned[i] != -1:
                continue
            cluster = [i]
            assigned[i] = len(clusters)
            if emb:
                for j in range(i+1, len(embeddings)):
                    if assigned[j] != -1:
                        continue
                    if cos(emb, embeddings[j]) >= sim_threshold:
                        cluster.append(j)
                        assigned[j] = len(clusters)
            clusters.append(cluster)
            if len(clusters) >= max_clusters:
                break
        # Build summarized result list
        summarized_blocks = []
        summary_meta = []
        for cid, cluster in enumerate(clusters):
            if len(cluster) == 1:
                idx = cluster[0]
                summarized_blocks.append(results[idx])
                continue
            # Build summary text
            sentences = []
            import re as _re
            for idx in cluster:
                raw = texts[idx]
                first = _re.split(r'(?<=[.!?])\s+', raw.strip())[0]
                if first:
                    sentences.append(first.strip())
                if len(sentences) >= 8:
                    break
            summary_text = " ".join(sentences)[:800]
            summarized_blocks.append({
                "chunk": f"Cluster Summary ({len(cluster)} blocks):\n{summary_text}",
                "score": sum(results[i].get('score',0) for i in cluster)/len(cluster),
                "metadata": {"cluster_size": len(cluster), "cluster_id": cid+1}
            })
            summary_meta.append({"cluster_id": cid+1, "size": len(cluster)})
        logging.getLogger(__name__).info(f"[MULTIPASS] Clustered {len(results)} blocks into {len(summarized_blocks)} (clusters={len(clusters)})")
        return summarized_blocks, {"clusters": summary_meta}
    except Exception as e:
        logging.getLogger(__name__).warning(f"[MULTIPASS] summarization failed: {e}")
        return results, None






def _adv_parse_date(d: Optional[str]):
    if not d:
        return None
    from datetime import datetime
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(d.strip(), fmt)
        except Exception:
            continue
    return None

def _adv_compute_relative_range(tag: Optional[str]):
    if not tag:
        return None, None
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    raw_tag = tag
    tag = tag.lower()
    # Normalize to day start
    def start_of_month(dt):
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    def start_of_quarter(dt):
        m = ((dt.month - 1)//3)*3 + 1
        return dt.replace(month=m, day=1, hour=0, minute=0, second=0, microsecond=0)
    if tag == 'last_7d':
        return now - timedelta(days=7), now
    if tag == 'last_30d':
        return now - timedelta(days=30), now
    if tag == 'this_month':
        return start_of_month(now), now
    if tag == 'prev_month':
        from calendar import monthrange
        first_this = start_of_month(now)
        prev_last = first_this - timedelta(days=1)
        first_prev = start_of_month(prev_last)
        # end of prev month is prev_last end of day
        return first_prev, prev_last.replace(hour=23, minute=59, second=59)
    if tag == 'this_quarter':
        return start_of_quarter(now), now
    if tag == 'prev_quarter':
        first_this_q = start_of_quarter(now)
        prev_q_end = first_this_q - timedelta(seconds=1)
        first_prev_q = start_of_quarter(prev_q_end)
        return first_prev_q, prev_q_end
    # ISO8601-like duration backward range e.g. P90D, P2W, P3M, P1Y
    import re
    m = re.match(r'^p(\d+)([dwmy])$', tag)
    if m:
        qty = int(m.group(1))
        unit = m.group(2)
        if unit == 'd':
            return now - timedelta(days=qty), now
        if unit == 'w':
            return now - timedelta(weeks=qty), now
        if unit == 'm':
            # Approximate months as 30 days for range window
            return now - timedelta(days=qty*30), now
        if unit == 'y':
            return now - timedelta(days=qty*365), now
    return None, None

def _adv_build_metadata_filter(date_from_dt, date_to_dt, explicit_field: Optional[str] = None):
    if not (date_from_dt or date_to_dt):
        return None
    # Support multiple candidate date fields (env or explicit)
    if explicit_field:
        fields = [explicit_field]
    else:
        env_fields = os.getenv("ADV_SEARCH_DATE_FIELDS", "created_at,date,createdAt,updated_at").split(',')
        fields = [f.strip() for f in env_fields if f.strip()]
    cond_template = {}
    if date_from_dt:
        cond_template["$gte"] = date_from_dt
    if date_to_dt:
        cond_template["$lte"] = date_to_dt
    if len(fields) == 1:
        return {fields[0]: cond_template}
    # Build $or for multiple fields
    return {"$or": [{f: cond_template} for f in fields]}

def _adv_filter_numbers(results, numbers_list):
    if not numbers_list:
        return results
    filtered = []
    for r in results:
        txt = (r.get('chunk') or r.get('text') or '').lower()
        if any(n in txt for n in numbers_list):
            filtered.append(r)
    return filtered or results

# --- Fallback: direct quote entity extraction (e.g., "give quotes of malatesh opportunity") ---
_QUOTE_PATTERNS = [
    re.compile(r"(?:give\s+)?quotes?\s+of\s+([a-zA-Z0-9._ -]{2,60})", re.IGNORECASE),
    re.compile(r"quotes?\s+for\s+([a-zA-Z0-9._ -]{2,60})", re.IGNORECASE)
]

def _extract_quote_target(query: str) -> Optional[str]:
    if not query:
        return None
    for pat in _QUOTE_PATTERNS:
        m = pat.search(query)
        if m:
            name = m.group(1).strip().strip('-').strip()
            # prune trailing generic words
            name = re.sub(r"\b(opportunity|deal|account|quotes?)$", "", name, flags=re.IGNORECASE).strip()
            if 1 < len(name) <= 60:
                return name
    return None

# Enhanced quote doc search & context builders
def _find_quote_docs(target: str):
    if not target:
        return []
    regex = {"$regex": target, "$options": "i"}
    direct_filter = {"$or": [
        {"account_name": regex},
        {"owner": regex},
        {"opportunity_name": regex},
        {"opportunity": regex}
    ]}
    try:
        docs = list(quotes_collection.find(direct_filter).limit(int(os.getenv("QUOTE_ENTITY_MAX_DOCS","15"))))
    except Exception:
        docs = []
    if docs:
        return docs
    # Fuzzy search fallback
    import difflib
    fields = ["account_name","owner","opportunity_name","opportunity"]
    candidates = set()
    for f in fields:
        try:
            vals = quotes_collection.distinct(f)
        except Exception:
            vals = []
        for v in vals:
            if isinstance(v, str) and 1 < len(v) <= 80:
                candidates.add(v.strip())
    from difflib import SequenceMatcher
    ratio_thresh = float(os.getenv("QUOTE_ENTITY_MIN_RATIO","0.72"))
    scored = []
    for c in candidates:
        r = SequenceMatcher(None, c.lower(), target.lower()).ratio()
        if r >= ratio_thresh:
            scored.append((r,c))
    scored.sort(reverse=True)
    top_names = [c for _,c in scored[:8]]
    if not top_names:
        return []
    try:
        or_filter = {"$or": [
            {"account_name": {"$in": top_names}},
            {"opportunity_name": {"$in": top_names}},
            {"opportunity": {"$in": top_names}},
            {"owner": {"$in": top_names}}
        ]}
        docs = list(quotes_collection.find(or_filter).limit(int(os.getenv("QUOTE_ENTITY_MAX_DOCS","15"))))
    except Exception:
        docs = []
    return docs

def _build_quote_context_blocks(docs: list) -> list[str]:
    blocks = []
    for i, q in enumerate(docs):
        acct = q.get('account_name') or q.get('account') or 'Unknown'
        amt = q.get('amount') or q.get('value') or q.get('total')
        stage = q.get('stage') or q.get('status') or q.get('state')
        owner = q.get('owner') or q.get('rep')
        opp = q.get('opportunity_name') or q.get('opportunity')
        date = q.get('date') or q.get('created_at') or q.get('createdAt')
        blocks.append(f"Context Q{i+1}: Account={acct} Opportunity={opp} Stage={stage} Owner={owner} Amount={amt} Date={date}")
    return blocks

@app.post("/query/advanced", response_model=QueryResponse)
async def advanced_query(input_data: AdvancedSearchInput):
    # Quick identity reply: handle 'who are you' style queries early
    try:
        qtext = (input_data.query or input_data.chat.query) if hasattr(input_data, 'query') or hasattr(input_data, 'chat') else None
        qstr = str(qtext) if qtext is not None else ''
        if is_identity_query(qstr):
            reply = "iam doxi ai assistant developed by dealdox"
            save_chat(getattr(input_data, 'user_id', None), getattr(input_data, 'session_id', None), getattr(input_data, 'access_token', None), qstr, qstr, reply, [])
            return QueryResponse(
                answer=reply,
                user_id=getattr(input_data, 'user_id', None),
                session_id=getattr(input_data, 'session_id', None),
                access_token=getattr(input_data, 'access_token', ''),
                chat={"query": qstr, "llm_response": reply},
                context_blocks=[],
                session_history=[],
                memory_usage=0,
                citations=[],
                confidence=None
            )
    except Exception:
        pass
    # Block advanced queries when a PDF session is active for this session/user (enforce PDF-only)
    try:
        if os.getenv("PDF_SESSION_BLOCK_QUERY", "true").lower() == "true":
            pdf_text = _get_pdf_session_text(input_data.user_id, input_data.session_id)
            if pdf_text:
                return JSONResponse({
                    "error": "PDF session active: route queries to /analyze-pdf (with query) or /pdf-session-query",
                    "user_id": input_data.user_id,
                    "session_id": input_data.session_id
                }, status_code=409)
    except Exception:
        pass
    user_id = input_data.user_id
    session_id = input_data.session_id
    query_text = input_data.query.strip()
    nums = [n.strip() for n in (input_data.numbers or '').split(',') if n.strip()]
    # Relative range has priority if supplied
    rel_from, rel_to = _adv_compute_relative_range(input_data.relative_range)
    d_from = rel_from or _adv_parse_date(input_data.date_from)
    d_to = rel_to or _adv_parse_date(input_data.date_to)
    if d_from and d_to and d_from > d_to:
        # swap to ensure order
        d_from, d_to = d_to, d_from

    # --- Timezone offset handling (assumes stored datetimes are UTC) ---
    def _parse_tz_off(val: Optional[str]):
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return int(val)
        s = val.strip()
        if not s:
            return None
        # Formats: +05:30, -0700, +5, -5.5, 330 (minutes)
        import re
        m = re.match(r'^([+-])(\d{1,2})(:?)(\d{2})?$', s)
        if m:
            sign = 1 if m.group(1) == '+' else -1
            hh = int(m.group(2))
            mm = int(m.group(4)) if m.group(4) else 0
            return sign * (hh * 60 + mm)
        # Decimal hours like -5.5
        m2 = re.match(r'^([+-]?)(\d{1,2})(\.\d+)?$', s)
        if m2:
            sign = -1 if m2.group(1) == '-' else 1
            hh = int(m2.group(2))
            frac = float(m2.group(3)) if m2.group(3) else 0.0
            total = sign * int(round((hh + frac) * 60))
            return total
        # Raw minutes integer string
        try:
            return int(s)
        except Exception:
            return None

    tz_minutes = _parse_tz_off(input_data.tz_offset)
    if tz_minutes:
        from datetime import timedelta
        # Convert user local date range -> UTC by subtracting offset
        shift = timedelta(minutes=tz_minutes)
        if d_from:
            d_from = d_from - shift
        if d_to:
            d_to = d_to - shift
    metadata_filter = _adv_build_metadata_filter(d_from, d_to, input_data.date_field)
    # --- Cache key construction (includes date + numbers + relative + tz) ---
    import hashlib, json, time
    cache_enabled = os.getenv("ADV_SEARCH_CACHE_ENABLE", "true").lower() == "true"
    cache_ttl = int(os.getenv("ADV_SEARCH_CACHE_TTL_SECS", "300"))
    pref_hash = ""
    if input_data.preferences:
        try:
            pref_hash = hashlib.md5(json.dumps(input_data.preferences, sort_keys=True).encode()).hexdigest()[:8]
        except Exception:
            pref_hash = "preferr"
    cache_key_parts = [
        input_data.user_id or "",
        input_data.session_id or "",
        query_text,
        ",".join(nums) if nums else "",
        str(d_from.timestamp()) if d_from else "*",
        str(d_to.timestamp()) if d_to else "*",
        input_data.relative_range or "",
        input_data.date_field or "auto",
        str(input_data.strict_date),
        input_data.tz_offset or "",
        pref_hash
    ]
    cache_key = "|".join(cache_key_parts)
    cache_hit = False
    if cache_enabled and cache_key in advanced_search_cache:
        entry = advanced_search_cache[cache_key]
        if time.time() - entry["ts"] <= cache_ttl:
            base_results = entry["results"]
            cache_hit = True
        else:
            advanced_search_cache.pop(cache_key, None)
    if not cache_hit:
        base_results = retriever.retrieve(query_text, k=25, metadata_filter=metadata_filter, preferences=input_data.preferences) or []
        if cache_enabled:
            advanced_search_cache[cache_key] = {"ts": time.time(), "results": base_results}

    # Post-filter by dates across multiple possible fields for accuracy
    def _parse_any_date(val):
        from datetime import datetime
        if not val:
            return None
        if isinstance(val, (int, float)):
            try:
                return datetime.fromtimestamp(float(val))
            except Exception:
                return None
        if isinstance(val, str):
            candidates = ["%Y-%m-%d","%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M:%S.%fZ","%d-%m-%Y","%d/%m/%Y","%Y/%m/%d"]
            for fmt in candidates:
                try:
                    return datetime.strptime(val[:26], fmt)
                except Exception:
                    continue
        return None
    if d_from or d_to:
        date_fields = []
        if input_data.date_field:
            date_fields = [input_data.date_field]
        else:
            date_fields = [f.strip() for f in os.getenv("ADV_SEARCH_DATE_FIELDS","created_at,date,createdAt,updated_at").split(',') if f.strip()]
        filtered_time = []
        dropped = 0
        for r in base_results:
            dt_val = None
            # check multiple locations including metadata
            for f in date_fields:
                if f in r:
                    dt_val = _parse_any_date(r.get(f))
                elif 'metadata' in r and isinstance(r['metadata'], dict) and f in r['metadata']:
                    dt_val = _parse_any_date(r['metadata'].get(f))
                if dt_val:
                    break
            if not dt_val:
                if input_data.strict_date:
                    dropped += 1
                    continue
                else:
                    filtered_time.append(r)
                    continue
            if d_from and dt_val < d_from:
                dropped += 1
                continue
            if d_to and dt_val > d_to:
                dropped += 1
                continue
            filtered_time.append(r)
        base_results = filtered_time
    results = _adv_filter_numbers(base_results, nums)
    summarized_results, summary_meta = _multi_pass_cluster_summarize(results, input_data.preferences)
    effective_results = summarized_results or results
    context_blocks = []
    for i, doc in enumerate(effective_results):
        text = doc.get('chunk') or doc.get('text') or ''
        if text:
            context_blocks.append(f"Context {i+1}:\n{text}")
    if os.getenv("ENABLE_QUOTE_ENTITY_FALLBACK", "true").lower() == "true":
        target = _extract_quote_target(query_text)
        if target:
            quote_docs = _find_quote_docs(target)
            if quote_docs:
                quote_blocks = _build_quote_context_blocks(quote_docs)
                low_signal = not context_blocks or all('[RECENT]' in cb or len(cb) < 140 for cb in context_blocks)
                if low_signal:
                    context_blocks = quote_blocks
                else:
                    remaining = max(0, 12 - len(context_blocks))
                    if remaining:
                        context_blocks.extend(quote_blocks[:remaining])
                context_blocks.append(f"Context Note: Injected {len(quote_blocks)} quote entities for target '{target}'.")
    if not context_blocks:  # final fallback to memory enrichment
        from app.memory.memory_enrichment import get_enriched_memory_context
        context_blocks = get_enriched_memory_context(
            session_id=session_id,
            n=5,
            weight_recent=2,
            preferences=input_data.preferences,
            user_id=user_id
        ).split('\n')
    # --- Date range summary injection (optional) ---
    if os.getenv("ADV_SEARCH_ADD_DATE_SUMMARY", "true").lower() == "true":
        from_dt_str = d_from.isoformat() if d_from else "*"
        to_dt_str = d_to.isoformat() if d_to else "*"
        nums_preview = ','.join(nums[:5]) if nums else 'none'
        summary_line = (
            f"Effective Date Range: {from_dt_str} -> {to_dt_str}; "
            f"relative_range={input_data.relative_range or 'none'}; date_field={input_data.date_field or 'auto'}; "
            f"tz_offset={input_data.tz_offset or 'none'}; strict_date={input_data.strict_date}; numbers={nums_preview}; "
            f"docs={len(effective_results)}"
        )
        # Prepend so LLM reliably sees it first
        context_blocks.insert(0, "Context DateRange:\n" + summary_line)
    prompt = build_llm_prompt(
        query_text,
        context_blocks=context_blocks,
        preferences=input_data.preferences
    )
    trace_header = f"[TRACE_ADV user_id={user_id} session_id={session_id} numbers={len(nums)} dates={(input_data.date_from or '')}->{(input_data.date_to or '')}]"
    prompt = trace_header + "\n" + prompt
    raw = llm_engine.chat(prompt=prompt)
    raw = sanitize_provider_noise(raw)
    out_of_domain = detect_out_of_domain(query_text, context_blocks)
    answer = finalize_answer(raw, input_data.preferences)
    if out_of_domain:
        answer = finalize_answer(build_domain_refusal(query_text), input_data.preferences)
    save_chat(user_id, session_id, input_data.access_token, query_text, query_text, answer, results)
    return QueryResponse(
        answer=answer or "No answer generated.",
        user_id=user_id,
        session_id=session_id,
        access_token=input_data.access_token or "",
        chat={"query": query_text, "llm_response": answer or "No answer generated."},
        context_blocks=context_blocks,
        session_history=[],
        memory_usage=0,
        citations=[],
        confidence={"advanced": True, "numbers_used": bool(nums), "date_filter": bool(metadata_filter)},
        filters={
            "numbers": nums or [],
            "date_from": d_from.isoformat() if d_from else None,
            "date_to": d_to.isoformat() if d_to else None,
            "relative_range": input_data.relative_range,
            "date_field": input_data.date_field,
            "strict_date": input_data.strict_date,
            "tz_offset_minutes": tz_minutes,
            "cache_hit": cache_hit
        }
    )
# Feedback endpoint for thumbs up/down



# ===================== User Preference Persistence ===================== #


@app.get("/preferences/{user_id}")
async def get_preferences(user_id: str):
    prefs = get_user_preferences(user_id)
    return {"user_id": user_id, "preferences": prefs}

@app.post("/preferences/update")
async def update_preferences(update: PreferenceUpdate):
    old = get_user_preferences(update.user_id)
    merged = upsert_user_preferences(update.user_id, update.preferences, mode=update.mode or "merge")
    diff = preference_diff(old, merged)
    return {"user_id": update.user_id, "preferences": merged, "changed": diff}

# Detect count/aggregation queries
def is_count_query(query: str) -> bool:
    # Only match queries that clearly ask for a count/aggregation
    patterns = [
        r"\btotal number of\b",
        r"\bhow many\b",
        r"\bcount of\b",
        r"\bnumber of\b",
        r"\baggregate\b",
        r"\bsum\b",
        r"\baverage\b",
        r"\bavg\b",
        r"\bmin\b",
        r"\bmax\b"
    ]
    return any(re.search(pat, query, re.IGNORECASE) for pat in patterns)

# Parse the query to determine which aggregation to run
def parse_count_query(query: str):
    query_lower = query.lower()

    # Entity: quote, account, opportunity
    entity_match = re.search(r"(?:number|count) of (\w+)", query_lower)
    entity = entity_match.group(1) if entity_match else None

    # Creator / owner
    creator_match = re.search(r"(?:created by|by this owner) ([\w\s]+)", query_lower)
    creator = creator_match.group(1).strip() if creator_match else None

    # Account or opportunity specific
    account_match = re.search(r"for this account ([\w\s]+)", query_lower)
    opportunity_match = re.search(r"for this opportunity ([\w\s]+)", query_lower)
    account_name = account_match.group(1).strip() if account_match else None
    opportunity_name = opportunity_match.group(1).strip() if opportunity_match else None

    return entity, creator, account_name, opportunity_name



def save_chat(user_id, session_id, access_token, query_text, resolved_query, llm_response, source_docs):
    chat_entry = {
        "query_text": query_text,
        "resolved_query": resolved_query,
        "llm_response": llm_response,
        "source_docs": source_docs,
        "timestamp": datetime.utcnow()
    }

    memory_collection.update_one(
        {"user_id": user_id, "session_id": session_id},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "session_id": session_id,
                "access_token": access_token
            },
            "$push": {"chats": chat_entry}
        },
        upsert=True
    )


# Memory browsing endpoints
@app.get("/memory/sessions")
async def list_memory_sessions(user_id: str | None = None, limit: int = 50):
    """List memory sessions with basic stats.

    If user_id is provided, filter by user; otherwise return recent sessions across users.
    """
    query = {"user_id": user_id} if user_id else {}
    cursor = memory_collection.find(query, {"session_id": 1, "chats": 1, "user_id": 1})
    sessions = []
    docs = list(cursor)
    for doc in docs:
        sid = doc.get("session_id")
        chats = doc.get("chats", [])
        last_ts_dt = chats[-1]["timestamp"] if chats else None
        last_ts = last_ts_dt.isoformat() if last_ts_dt else None
        # Derive a short preview from the last chat
        preview = None
        if chats:
            last = chats[-1]
            preview = last.get("llm_response") or last.get("query_text") or None
        sessions.append({
            "session_id": sid,
            "user_id": doc.get("user_id"),
            "chats_count": len(chats),
            "last_message_at": last_ts,
            "updatedAt": last_ts,
            "preview": preview
        })
    # sort by last_message_at desc and apply limit
    def _to_ts(x):
        from datetime import datetime
        try:
            return datetime.fromisoformat(x or "1970-01-01").timestamp()
        except Exception:
            return 0
    sessions.sort(key=lambda s: _to_ts(s.get("last_message_at")), reverse=True)
    if limit and limit > 0:
        sessions = sessions[:limit]
    return {"user_id": user_id, "sessions": sessions}

# Compatibility endpoint for FE expecting /api/ai/getAiResponse
@app.get("/api/ai/getAiResponse")
async def get_ai_history(user_id: str | None = None, limit: int = 50):
    """Return recent session summaries under a 'data' field for UI fallback.

    Shape matches builder expectations: include session_id, user_id, chats (last only), updatedAt, preview.
    """
    query = {"user_id": user_id} if user_id else {}
    cursor = memory_collection.find(query, {"session_id": 1, "chats": 1, "user_id": 1})
    items = []
    for doc in list(cursor):
        chats = doc.get("chats", [])
        last = chats[-1] if chats else None
        ts = (last or {}).get("timestamp")
        iso = ts.isoformat() if ts else None
        preview = (last or {}).get("llm_response") or (last or {}).get("query_text")
        # Include only the last chat to keep payload small
        items.append({
            "session_id": doc.get("session_id"),
            "user_id": doc.get("user_id"),
            "chats": [last] if last else [],
            "updatedAt": iso,
            "preview": preview,
        })
    # sort by updatedAt desc
    def _to_ts2(x):
        from datetime import datetime
        try:
            return datetime.fromisoformat(x or "1970-01-01").timestamp()
        except Exception:
            return 0
    items.sort(key=lambda d: _to_ts2(d.get("updatedAt")), reverse=True)
    if limit and limit > 0:
        items = items[:limit]
    return {"data": items}


@app.get("/memory")
async def get_memory(user_id: str | None = None, session_id: str | None = None, limit: int = 50):
    """Get chats for a session.

    Accepts either both user_id and session_id, or session_id alone.
    """
    if not session_id and not user_id:
        return JSONResponse({"error": "session_id or (user_id and session_id) required"}, status_code=400)
    doc = None
    if user_id and session_id:
        doc = memory_collection.find_one({"user_id": user_id, "session_id": session_id}, {"_id": 0})
    elif session_id:
        doc = memory_collection.find_one({"session_id": session_id}, {"_id": 0})
    if not doc:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    chats = doc.get("chats", [])
    if limit and limit > 0:
        chats = chats[-limit:]
    return {"user_id": doc.get("user_id"), "session_id": doc.get("session_id"), "chats": chats}


@app.get("/memory/{session_id}")
async def get_memory_by_session(session_id: str, user_id: str | None = None, limit: int = 50):
    """Convenience endpoint to fetch chats by session id; user_id optional."""
    return await get_memory(user_id=user_id, session_id=session_id, limit=limit)



# Main query endpoint

@app.post("/query", response_model=QueryResponse)
async def get_answer(input_data: QueryInput):
    user_id = input_data.user_id
    session_id = input_data.session_id
    query_text = str(input_data.chat.query) if not isinstance(input_data.chat.query, dict) else str(input_data.chat.query.get("query", "")).strip()
    # Quick identity reply: match before any LLM or retrieval work
    try:
        if is_identity_query(query_text):
            reply = "iam doxi ai assistant developed by dealdox"
            save_chat(user_id, session_id, input_data.access_token, query_text, query_text, reply, [])
            return QueryResponse(
                answer=reply,
                user_id=user_id,
                session_id=session_id,
                access_token=input_data.access_token,
                chat={"query": query_text, "llm_response": reply},
                context_blocks=[],
                session_history=[],
                memory_usage=0,
                citations=[],
                confidence=None
            )
    except Exception:
        pass
    # Enforce PDF-only routing: if a PDF session with text exists, block /query.
    try:
        if os.getenv("PDF_SESSION_BLOCK_QUERY", "true").lower() == "true":
            pdf_text = _get_pdf_session_text(user_id, session_id)
            if pdf_text:
                return JSONResponse({
                    "error": "PDF session active: /query is disabled for this session.",
                    "user_id": user_id,
                    "session_id": session_id
                }, status_code=409)
    except Exception:
        pass
    # Lightweight early greeting fast-path (avoid retrieval + refusal logic)
    try:
        if is_greeting(query_text):
            resp = finalize_answer(build_greeting_response(query_text), input_data.preferences)
            save_chat(user_id, session_id, input_data.access_token, query_text, query_text, resp, [])
            return QueryResponse(
                answer=resp,
                user_id=user_id,
                session_id=session_id,
                access_token=input_data.access_token,
                chat={"query": query_text, "llm_response": resp},
                context_blocks=[],
                session_history=[],
                memory_usage=0,
                citations=[],
                confidence=None
            )
    except Exception:
        pass  # fall back silently if greeting path fails
    # Legacy inline PDF-handling removed to fully decouple /query from PDF processing.
    # PDF sessions must be handled via the dedicated PDF endpoints and are not
    # processed by the RAG/embeddings path here.
    # General RAG path (hybrid retrieval + optional reranking) for /query only
    import time, hashlib, json, logging
    resolved_query = query_text
    # Optional intent classification to tune depth
    intent_result = None
    try:
        if os.getenv("INTENT_ENABLE", "true").lower() == "true":
            intent_result = classify_intent(resolved_query)
    except Exception:
        intent_result = None
    # Retrieval with lightweight cache
    try:
        cache_enable = os.getenv("RAG_RETRIEVAL_CACHE_ENABLE", "true").lower() == "true"
        cache_ttl = int(os.getenv("RAG_RETRIEVAL_CACHE_TTL_SECS", "120"))
    except Exception:
        cache_enable = True; cache_ttl = 120
    pref_hash = ""
    if input_data.preferences:
        try:
            pref_hash = hashlib.md5(json.dumps(input_data.preferences, sort_keys=True).encode()).hexdigest()[:8]
        except Exception:
            pref_hash = "preferr"
    retrieval_cache_key = f"{user_id}|{session_id}|{resolved_query}|{pref_hash}"
    results = []
    cache_hit = False
    timers_enabled = os.getenv("RAG_TIMERS", "false").lower() == "true"
    timers = {}
    t0 = time.perf_counter() if timers_enabled else None
    if cache_enable and retrieval_cache_key in retrieval_cache:
        entry = retrieval_cache[retrieval_cache_key]
        if time.time() - entry.get("ts", 0) <= cache_ttl:
            results = entry.get("results", [])
            cache_hit = True
    if not results:
        use_hybrid = os.getenv("HYBRID_RETRIEVAL_ENABLE","true").lower()=="true"
        hybrid_meta = {}
        try:
            if use_hybrid:
                from app.core.hybrid_retrieval import hybrid_retrieve
                results = hybrid_retrieve(
                    resolved_query,
                    retriever,
                    preferences=input_data.preferences,
                    k=25,
                    meta=hybrid_meta
                ) or []
            else:
                results = retriever.retrieve(resolved_query, k=25, preferences=input_data.preferences) or []
        except Exception as e:
            # Fallback to vector-only
            results = retriever.retrieve(resolved_query, k=25, preferences=input_data.preferences) or []
            hybrid_meta['fallback_vector'] = True
            hybrid_meta['error'] = str(e)
        if cache_enable:
            retrieval_cache[retrieval_cache_key] = {"ts": time.time(), "results": results}
        try:
            record_retrieval_metrics(hybrid_meta)
        except Exception:
            pass
    if timers_enabled and t0 is not None:
        timers["retrieval_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        timers["retrieval_cache_hit"] = cache_hit
    # Score threshold + simple noise filter
    try:
        min_score = float(os.getenv("RAG_MIN_SCORE", "0.35"))
    except Exception:
        min_score = 0.35
    def _is_noise_chunk(t: str) -> bool:
        if not t: return True
        s = t.strip()
        return len(s) < 20
    filtered = []
    for r in results:
        sc = r.get('score', 0)
        txt = (r.get('chunk') or r.get('text') or '')
        if sc is not None and sc < min_score:
            continue
        if _is_noise_chunk(txt):
            continue
        filtered.append(r)
    results = filtered or results[:8]
    # Diversity suppression (light)
    def _normalize_text(t: str) -> str:
        import re
        return re.sub(r"\s+"," ", (t or "").lower()).strip()
    kept = []
    seen_snippets = set()
    for r in results:
        snip = _normalize_text((r.get('chunk') or r.get('text') or '')[:300])
        if not snip or snip in seen_snippets:
            continue
        seen_snippets.add(snip)
        kept.append(r)
        if len(kept) >= 18:
            break
    results = kept or results
    # Build context blocks
    context_blocks = []
    for i, doc in enumerate(results[:12]):
        text = doc.get('chunk') or doc.get('text') or ''
        if text:
            context_blocks.append(f"Context {i+1}:\n{text}")
    if not context_blocks:
        from app.memory.memory_enrichment import get_enriched_memory_context
        context_blocks = get_enriched_memory_context(
            session_id=session_id,
            n=5,
            weight_recent=2,
            preferences=input_data.preferences,
            user_id=user_id
        ).split('\n')
    # Build prompt and call LLM
    try:
        context_blocks = redact_pii(context_blocks)
    except Exception:
        pass
    prompt = build_llm_prompt(query_text, context_blocks=context_blocks, preferences=input_data.preferences)
    raw = llm_engine.chat(prompt=prompt)
    raw = sanitize_provider_noise(raw)
    out_of_domain = detect_out_of_domain(query_text, context_blocks)
    answer = finalize_answer(raw, input_data.preferences)
    if out_of_domain:
        if is_greeting(query_text):
            answer = finalize_answer(build_greeting_response(query_text), input_data.preferences)
        else:
            answer = finalize_answer(build_domain_refusal(query_text), input_data.preferences)
    # Save chat
    try:
        save_chat(user_id, session_id, input_data.access_token, query_text, query_text, answer, results)
    except Exception:
        pass
    # Assemble confidence/meta
    def _score_of(r):
        return r.get('final_score') or r.get('hybrid_score') or r.get('rerank_score') or r.get('score')
    top_scores = [round(float(_score_of(r) or 0),4) for r in results[:5]]
    confidence = {
        "hybrid": os.getenv("HYBRID_RETRIEVAL_ENABLE","true").lower()=="true",
        "results_counts": {"initial": len(results)},
        "top_scores": top_scores,
    }
    if timers_enabled:
        confidence["timers"] = timers
    # Citations optional
    citations = None
    if os.getenv("ENABLE_CITATIONS", "true").lower() == "true" and not out_of_domain:
        try:
            alignment_result = align_answer_with_context(answer, context_blocks, out_of_domain=out_of_domain)
            if isinstance(alignment_result, (list, tuple)) and len(alignment_result) >= 2:
                aligned_answer = alignment_result[0]
                annotations = alignment_result[1]
                answer = aligned_answer or answer
                citations = annotations
        except Exception:
            pass
    # Numeric verification (lightweight) on grounded answers
    try:
        nums_meta = verify_numbers(answer, context_blocks)
        if nums_meta:
            confidence["numeric_verification"] = nums_meta
    except Exception:
        pass
    return QueryResponse(
        answer=answer or "No answer generated.",
        user_id=user_id,
        session_id=session_id,
        access_token=input_data.access_token,
        chat={"query": query_text, "llm_response": answer or "No answer generated."},
        context_blocks=context_blocks,
        session_history=[],
        memory_usage=0,
        citations=citations,
        confidence=confidence
    )


@app.post("/pdf-session-query")
async def pdf_session_query(input_data: QueryInput):
    """Answer a question using only the stored PDF text for the given session/user.

    Expected input: JSON with `chat: { query }`, `user_id`, `session_id`, `access_token`.
    """
    try:
        user_id = input_data.user_id
        session_id = input_data.session_id
        query_text = str(input_data.chat.query) if not isinstance(input_data.chat.query, dict) else str(input_data.chat.query.get("query", "")).strip()
        if not query_text:
            return JSONResponse({"status": "error", "message": "No query provided."}, status_code=400)
        pdf_text = _get_pdf_session_text(user_id, session_id)
        if not pdf_text:
            return JSONResponse({"status": "error", "message": "No PDF data found for this session/user."}, status_code=404)
        # Build strict prompt that uses only PDF content and route via shared helper
        prompt = (
            "Answer the following question using ONLY the PDF content below. "
            "If the answer is not in the PDF, reply 'Not found in PDF.'\n\n"
            "PDF Content:\n" + str(pdf_text) + "\n\n"
            "Question: " + str(query_text)
        )
        llm_response = llm_engine.chat(prompt=prompt)
        # Record Q&A into pdf_sessions_collection if available
        try:
            if 'pdf_sessions_collection' in globals() and pdf_sessions_collection:
                pdf_sessions_collection.update_one(
                    {"session_id": session_id, "user_id": user_id},
                    {"$push": {"questions": query_text, "answers": llm_response}},
                )
        except Exception:
            pass
        return {"status": "ok", "answer": llm_response, "user_id": user_id, "session_id": session_id}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    # If no PDF data, run RAG engine with vector search context
    import logging, time, hashlib, json
    logging.basicConfig(level=logging.INFO)
    resolved_query = query_text
    # Fielded query parsing (owner:, stage:, amount>, date: etc.)
    parsed_filters = {}
    if os.getenv("FIELD_PARSING_ENABLE", "true").lower() == "true":
        try:
            cleaned, parsed_filters = parse_query_filters(resolved_query)
            if cleaned and cleaned != resolved_query:
                resolved_query = cleaned
        except Exception:
            parsed_filters = {}
    resolved_query = query_text
    # Intent classification (optional)
    intent_enabled = os.getenv("INTENT_ENABLE", "true").lower() == "true"
    intent_result = None
    if intent_enabled:
        try:
            intent_result = classify_intent(resolved_query)
        except Exception:
            intent_result = None
    # Aggregation precompute fast-path
    if intent_result and intent_result.intent.value == 'AGGREGATION' and os.getenv('PRECOMP_AGG_ENABLE','true').lower() == 'true':
        try:
            from app.db.mongo import db as _db
            today = datetime.date.today().isoformat()
            pre_col = _db.get_collection('precomputed_aggregations')
            snap = pre_col.find_one({'date': today, 'scope':'global'})
            if snap and snap.get('metrics'):
                m = snap['metrics']
                # Build concise answer
                ans_parts = [f"Total Quotes: {m.get('quotes_total')}", f"Sum Amount: {round(m.get('amount_sum',0),2)}", f"Avg Amount: {round(m.get('amount_avg',0),2)}"]
                if m.get('discount_ratio_avg') is not None:
                    ans_parts.append(f"Avg Discount Ratio: {round(m.get('discount_ratio_avg'),3)}")
                if m.get('top_accounts'):
                    top_line = ', '.join(f"{ta['account_name']}({round(ta['amount_sum'],2)})" for ta in m['top_accounts'][:5])
                    ans_parts.append(f"Top Accounts: {top_line}")
                answer_text = ' | '.join(ans_parts)
                save_chat(user_id, session_id, input_data.access_token, query_text, resolved_query, answer_text, [])
                return QueryResponse(
                    answer=answer_text,
                    user_id=user_id,
                    session_id=session_id,
                    access_token=input_data.access_token,
                    chat={"query": query_text, "llm_response": answer_text},
                    context_blocks=[],
                    session_history=[],
                    memory_usage=0,
                    confidence={"precomputed_aggregation": True}
                )
        except Exception:
            pass
    timers_enabled = os.getenv("RAG_TIMERS", "false").lower() == "true"
    timers = {}
    t0 = time.perf_counter()
    # --- Retrieval caching (results only, not final answer) ---
    results = []
    try:
        cache_enable = os.getenv("RAG_RETRIEVAL_CACHE_ENABLE", "true").lower() == "true"
        cache_ttl = int(os.getenv("RAG_RETRIEVAL_CACHE_TTL_SECS", "120"))
    except Exception:
        cache_enable = True; cache_ttl = 120
    pref_hash = ""
    if input_data.preferences:
        try:
            pref_hash = hashlib.md5(json.dumps(input_data.preferences, sort_keys=True).encode()).hexdigest()[:8]
        except Exception:
            pref_hash = "preferr"
    retrieval_cache_key = f"{user_id}|{session_id}|{resolved_query}|{pref_hash}"
    cache_hit = False
    if cache_enable and retrieval_cache_key in retrieval_cache:
        entry = retrieval_cache[retrieval_cache_key]
        if time.time() - entry["ts"] <= cache_ttl:
            results = entry["results"]
            cache_hit = True
        else:
            retrieval_cache.pop(retrieval_cache_key, None)
    if not results:
        # Optionally resolve coreference here if needed
        use_hybrid = os.getenv("HYBRID_RETRIEVAL_ENABLE","true").lower()=="true"
        hybrid_meta = {}
        if use_hybrid:
            try:
                from app.core.hybrid_retrieval import hybrid_retrieve
                hybrid_results = hybrid_retrieve(
                    resolved_query,
                    retriever,
                    preferences=input_data.preferences,
                    k=25,
                    meta=hybrid_meta,
                    structured_filters=parsed_filters if parsed_filters else None
                )
                results = hybrid_results
            except Exception as e:
                # Fallback to plain vector retrieval
                results = retriever.retrieve(resolved_query, k=25, preferences=input_data.preferences) or []
                hybrid_meta['error'] = str(e)
                hybrid_meta['fallback_vector'] = True
        else:
            results = retriever.retrieve(resolved_query, k=25, preferences=input_data.preferences) or []
        if cache_enable:
            retrieval_cache[retrieval_cache_key] = {"ts": time.time(), "results": results}
        if timers_enabled:
            timers['hybrid'] = hybrid_meta
        try:
            record_retrieval_metrics(hybrid_meta)
        except Exception:
            pass
    if timers_enabled:
        timers["retrieval_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        timers["retrieval_cache_hit"] = cache_hit
    try:
        import logging as _lg
        if os.getenv("RAG_DEBUG", "false").lower() == "true":
            _lg.info(f"[RAG_DEBUG] initial_results={len(results)} top_scores={[round(r.get('score',0),4) for r in results[:5]]}")
    except Exception:
        pass
    # --- Score threshold & noise filtering ---
    try:
        min_score = float(os.getenv("RAG_MIN_SCORE", "0.35"))
    except Exception:
        min_score = 0.35
    filtered = []
    for r in results:
        sc = r.get('score', 0)
        txt = (r.get('chunk') or r.get('text') or '')
        if sc < min_score:
            continue
        if _is_noise_chunk(txt):
            continue
        filtered.append(r)
    # If filtering removed everything, relax progressively
    if not filtered:
        # First: drop noise only
        filtered = [r for r in results if not _is_noise_chunk((r.get('chunk') or r.get('text') or ''))]
    if not filtered:
        # Second: revert to original but keep top N small set
        filtered = results[:8]
    results = filtered
    # --- Diversity / duplicate suppression ---
    def _normalize_text_for_sim(t: str) -> str:
        import re
        t = t.lower()
        t = re.sub(r"\s+", " ", t)
        return t.strip()

    def _shingles(s: str, k: int = 12):
        s = s.replace(" ", "")
        if len(s) <= k:
            return {s}
        return {s[i:i+k] for i in range(0, len(s)-k+1, max(1, k//3))}

    def _jaccard(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        if inter == 0:
            return 0.0
        return inter / float(len(a | b))

    def diversify(cands: list, max_per_parent: int = 2, sim_thresh: float = 0.92):
        kept = []
        seen_parent: dict[str,int] = {}
        shingle_cache = {}
        for r in cands:
            meta = r.get('metadata') or {}
            parent = str(meta.get('document_id') or meta.get('doc_id') or meta.get('source_id') or meta.get('account_name') or '')
            if parent:
                cnt = seen_parent.get(parent, 0)
                if cnt >= max_per_parent:
                    continue
            txt = _normalize_text_for_sim((r.get('chunk') or r.get('text') or '')[:800])
            sh = shingle_cache.get(txt)
            if sh is None:
                sh = _shingles(txt)
                shingle_cache[txt] = sh
            dup = False
            for k in kept:
                kt = _normalize_text_for_sim((k.get('chunk') or k.get('text') or '')[:800])
                sh_k = shingle_cache.get(kt)
                if sh_k is None:
                    sh_k = _shingles(kt)
                    shingle_cache[kt] = sh_k
                if _jaccard(sh, sh_k) >= sim_thresh:
                    dup = True
                    break
            if dup:
                continue
            kept.append(r)
            if parent:
                seen_parent[parent] = seen_parent.get(parent, 0) + 1
        return kept, {"kept": len(kept), "dropped": len(cands) - len(kept)}

    max_per_parent = int(os.getenv("DIVERSITY_MAX_PER_PARENT","2"))
    sim_thresh = float(os.getenv("DIVERSITY_SIM_THRESHOLD","0.92"))
    diversified, div_stats = diversify(results, max_per_parent=max_per_parent, sim_thresh=sim_thresh)
    if timers_enabled:
        timers['diversity'] = {"max_per_parent": max_per_parent, "sim_threshold": sim_thresh, **div_stats}
    results = diversified
    # Adaptive re-query when sparse
    # Apply field filters (post initial filtering) prior to adaptive logic
    if parsed_filters:
        pf = parsed_filters
        filtered2 = []
        for r in results:
            meta = r.get('metadata') or {}
            text_join = (r.get('chunk') or r.get('text') or '').lower()
            keep = True
            # owner / stage regex partial (case-insensitive)
            if pf.get('owner_regex'):
                val = (meta.get('owner') or meta.get('owner_name') or '').lower()
                if pf['owner_regex'].lower() not in val:
                    keep = False
            if keep and pf.get('stage_regex'):
                val = (meta.get('stage') or meta.get('status') or '').lower()
                if pf['stage_regex'].lower() not in val:
                    keep = False
            # amount filters
            if keep and (pf.get('amount_min') is not None or pf.get('amount_max') is not None):
                amt = meta.get('amount') or meta.get('total') or meta.get('value')
                try:
                    if amt is not None:
                        amt_f = float(amt)
                        if pf.get('amount_min') is not None and amt_f < pf['amount_min']:
                            keep = False
                        if pf.get('amount_max') is not None and amt_f > pf['amount_max']:
                            keep = False
                except Exception:
                    pass
            # date filters
            if keep and (pf.get('date_from') or pf.get('date_to')):
                dt_val = None
                for cand in ('date','created_at','createdAt','updated_at'):
                    if cand in meta:
                        dt_val = meta.get(cand)
                        break
                # parse
                if dt_val:
                    from datetime import datetime
                    if isinstance(dt_val, str):
                        for fmt in ("%Y-%m-%d","%Y-%m-%dT%H:%M:%S","%Y-%m-%dT%H:%M:%S.%fZ"):
                            try:
                                dt_parsed = datetime.strptime(dt_val[:26], fmt)
                                dt_val = dt_parsed
                                break
                            except Exception:
                                continue
                    if isinstance(dt_val, (int,float)):
                        try:
                            from datetime import datetime as _dt
                            dt_val = _dt.fromtimestamp(float(dt_val))
                        except Exception:
                            dt_val = None
                if dt_val:
                    if pf.get('date_from') and dt_val < pf['date_from']:
                        keep = False
                    if pf.get('date_to') and dt_val > pf['date_to']:
                        keep = False
                else:
                    # If strict date filtering desired later: optionally drop
                    pass
            if keep:
                filtered2.append(r)
        results = filtered2 or results

    # Adaptive retrieval depth tuning based on intent (pre re-query adjustment)
    try:
        if intent_result:
            base_len = len(results)
            if intent_result.intent in (IntentType.AGGREGATION, IntentType.ANALYTIC_INSIGHT):
                # Expand context if insufficient
                if base_len < 20:
                    extra = retriever.retrieve(resolved_query, k=15, preferences=input_data.preferences) or []
                    # simple extend unique
                    seen_ids = {id(r) for r in results}
                    for r in extra:
                        if id(r) not in seen_ids:
                            results.append(r)
            elif intent_result.intent in (IntentType.ENTITY_LOOKUP, IntentType.FACTOID):
                # Narrow early for speed
                results = results[:12]
    except Exception:
        pass

    # Adaptive re-query when sparse
    t_requery = time.perf_counter() if timers_enabled else None
    results = _adaptive_requery_if_sparse(resolved_query, results, retriever, input_data.preferences)
    if timers_enabled and t_requery is not None:
        timers["adaptive_requery_ms"] = round((time.perf_counter() - t_requery) * 1000, 2)
    # Optional pruning before summarization
    try:
        prune_k = int(os.getenv("RAG_PRUNE_TOP_K", "0"))
    except Exception:
        prune_k = 0
    if prune_k > 0 and len(results) > prune_k:
        results = results[:prune_k]
    # Skip summarization if below threshold or disabled
    summarize_enabled = os.getenv("RAG_ENABLE_MULTIPASS", "true").lower() == "true"
    try:
        summarize_min = int(os.getenv("RAG_MULTIPASS_MIN_RESULTS", "10"))
    except Exception:
        summarize_min = 10
    summarized_results = None; summary_meta = None
    # Row-level security filtering (post adaptive retrieval, pre summarization)
    try:
        if os.getenv('SECURITY_ENABLE','true').lower() == 'true':
            from app.db.mongo import get_user_profile as _gup
            profile = _gup(user_id) or {'user_id': user_id}
            rl = build_row_level_filter(profile)
            if rl:
                def _sec_clause_match(md, clause):
                    for k,v in clause.items():
                        if k.startswith('metadata.'):
                            key = k.split('.',1)[1]
                            if isinstance(v, dict):
                                if md.get(key) != v:
                                    return False
                            else:
                                if md.get(key) != v:
                                    return False
                        elif k == 'metadata.shared':
                            if not md.get('shared'):
                                return False
                        else:
                            if md.get(k) != v:
                                return False
                    return True
                def _sec_match(doc):
                    md = doc.get('metadata') or {}
                    if '$or' in rl:
                        return any(_sec_clause_match(md, c) for c in rl['$or'])
                    return _sec_clause_match(md, rl)
                sec_filtered = [d for d in results if _sec_match(d)]
                if sec_filtered:
                    results = sec_filtered
    except Exception:
        pass
    # Skip summarization for direct lookup/factoid intents to reduce latency
    if summarize_enabled and len(results) >= summarize_min and not (intent_result and intent_result.intent in (IntentType.ENTITY_LOOKUP, IntentType.FACTOID)):
        t_sum = time.perf_counter() if timers_enabled else None
        summarized_results, summary_meta = _multi_pass_cluster_summarize(results, input_data.preferences)
        if timers_enabled and t_sum is not None:
            timers["summarization_ms"] = round((time.perf_counter() - t_sum) * 1000, 2)
    effective_results = summarized_results or results
    try:
        if os.getenv("RAG_DEBUG", "false").lower() == "true":
            import logging as _lg
            _lg.info(f"[RAG_DEBUG] post_summarization_blocks={len(effective_results)} clustered={bool(summarized_results)} summary_meta={summary_meta}")
    except Exception:
        pass
    context_blocks = []
    for i, doc in enumerate(effective_results):
        text = doc.get('chunk') or doc.get('text') or doc.get('query', '') if doc else ''
        if text:
            context_blocks.append(f"Context {i+1}:\n{text}")
    # Optional debug context injection
    if os.getenv("RAG_DEBUG_CONTEXT", "false").lower() == "true" and results:
        debug_lines = []
        for r in results[:8]:
            score = r.get('score')
            snippet = (r.get('chunk') or r.get('text') or '')[:140].replace('\n',' ')
            debug_lines.append(f"score={round(score,4) if score is not None else 'NA'} | {snippet}")
        context_blocks.insert(0, "Context Debug:\n" + "\n".join(debug_lines))
    if not context_blocks:
        # Fallback to memory enrichment if vector search returns nothing
        from app.memory.memory_enrichment import get_enriched_memory_context
        context_blocks = get_enriched_memory_context(
            session_id=session_id,
            n=5,
            weight_recent=2,
            preferences=input_data.preferences,
            user_id=user_id
        ).split('\n')

    # --- Fetch conversation history for user/session ---
    history_cursor = memory_collection.find({"user_id": user_id, "session_id": session_id})
    session_history = []
    for entry in history_cursor:
        chats = entry.get("chats", [])
        for chat in chats:
            q = chat.get("query_text")
            a = chat.get("llm_response")
            if q and a:
                session_history.append(f"User: {q}\nAgent: {a}")

    # --- Build prompt with history ---
    prompt = ""
    if session_history:
        prompt += "Previous conversation history:\n" + "\n".join(session_history[-10:]) + "\n"  # last 10 exchanges
    # PII redaction pass on context blocks prior to prompt build
    try:
        if os.getenv('SECURITY_ENABLE','true').lower() == 'true':
            context_blocks = redact_pii(context_blocks)
    except Exception:
        pass
    prompt += build_llm_prompt(
        query_text,
        context_blocks=context_blocks,
        preferences=input_data.preferences
    )
    # Add a lightweight trace header (not user-visible in normal UI) so we can verify scoping
    trace_header = f"[TRACE user_id={user_id} session_id={session_id} history_len={len(session_history)} context_blocks={len(context_blocks)}]"
    prompt = trace_header + "\n" + prompt
    logging.debug(f"[PROMPT TRACE] {trace_header}")
    # Optionally dump first 500 chars for verification (guarded to avoid log noise)
    if os.getenv("LOG_HISTORY_SNIPPET", "false").lower() == "true":
        logging.debug(f"[PROMPT SNIPPET] {prompt[:500]}{'...' if len(prompt)>500 else ''}")
    # Structured answer template fast-path
    template_used = False
    if os.getenv("ANSWER_TEMPLATES_ENABLE","true").lower() == "true" and intent_result:
        tpl = render_template(intent_result.intent.value, query_text, effective_results)
        if tpl and os.getenv("ANSWER_TEMPLATES_LLM_AUGMENT","false").lower() != "true":
            raw_rag_response = tpl['answer']
            template_used = True
        elif tpl:  # augment mode
            augment_preamble = f"Structured Context Summary (Template={tpl['meta']['template']}):\n{tpl['answer']}\n\nUse above summary + context to answer precisely."
            prompt = augment_preamble + "\n\n" + prompt
    if not template_used:
        t_llm = time.perf_counter() if timers_enabled else None
        raw_rag_response = llm_engine.chat(prompt=prompt)
        if timers_enabled and t_llm is not None:
            timers["llm_ms"] = round((time.perf_counter() - t_llm) * 1000, 2)
    raw_rag_response = sanitize_provider_noise(raw_rag_response)
    # Out-of-domain detection
    out_of_domain = detect_out_of_domain(query_text, context_blocks)
    rag_response = finalize_answer(raw_rag_response, input_data.preferences)
    if out_of_domain:
        # Friendly greeting bypass instead of refusal
        if is_greeting(query_text):
            rag_response = finalize_answer(build_greeting_response(query_text), input_data.preferences)
            save_chat(user_id, session_id, input_data.access_token, query_text, query_text, rag_response, results)
            return QueryResponse(
                answer=rag_response or "Hello!",
                user_id=user_id,
                session_id=session_id,
                access_token=input_data.access_token,
                chat={"query": query_text, "llm_response": rag_response or "Hello!"},
                context_blocks=context_blocks,
                session_history=session_history,
                memory_usage=len(session_history),
                citations=[],
                confidence=None
            )
        if os.getenv("ALLOW_EXTERNAL_MODE", "false").lower() != "true":
            refusal = build_domain_refusal(query_text)
            rag_response = finalize_answer(refusal, input_data.preferences)
            save_chat(user_id, session_id, input_data.access_token, query_text, query_text, rag_response, results)
            return QueryResponse(
                answer=rag_response or "No answer generated.",
                user_id=user_id,
                session_id=session_id,
                access_token=input_data.access_token,
                chat={"query": query_text, "llm_response": rag_response or "No answer generated."},
                context_blocks=context_blocks,
                session_history=session_history,
                memory_usage=len(session_history),
                citations=[],
                confidence=None
            )
        else:
            # External trusted mode
            try:
                external_blocks = await fetch_trusted_pages(query_text, limit=3)
                if external_blocks:
                    ext_summary = summarize_external_blocks(external_blocks)
                    context_blocks = ["Trusted External Sources:\n" + ext_summary]
                    prompt = build_llm_prompt(query_text, context_blocks=context_blocks, preferences=input_data.preferences)
                    raw_ext = llm_engine.chat(prompt=prompt)
                    rag_response = finalize_answer(raw_ext, input_data.preferences)
                    save_chat(user_id, session_id, input_data.access_token, query_text, query_text, rag_response, external_blocks)
                    return QueryResponse(
                        answer=rag_response or "No answer generated.",
                        user_id=user_id,
                        session_id=session_id,
                        access_token=input_data.access_token,
                        chat={"query": query_text, "llm_response": rag_response or "No answer generated."},
                        context_blocks=context_blocks,
                        session_history=session_history,
                        memory_usage=len(session_history),
                        citations=[],
                        confidence={"mode":"external_trusted","sources": [b['url'] for b in external_blocks]}
                    )
            except Exception as e:
                logging.warning(f"[EXTERNAL_MODE] fetch failed: {e}")
                # Fall back to refusal
                refusal = build_domain_refusal(query_text)
                rag_response = finalize_answer(refusal, input_data.preferences)
                return QueryResponse(
                    answer=rag_response or "No answer generated.",
                    user_id=user_id,
                    session_id=session_id,
                    access_token=input_data.access_token,
                    chat={"query": query_text, "llm_response": rag_response or "No answer generated."},
                    context_blocks=context_blocks,
                    session_history=session_history,
                    memory_usage=len(session_history),
                    citations=[],
                    confidence={"mode":"external_error"}
                )
    logging.info(f"RAG response for user_id={user_id}, session_id={session_id}, query='{query_text}': {rag_response}")
    save_chat(user_id, session_id, input_data.access_token, query_text, query_text, rag_response, results)
    citations = None
    confidence_metrics = None
    if os.getenv("ENABLE_CITATIONS", "true").lower() == "true" and not out_of_domain:
        try:
            alignment_result = align_answer_with_context(rag_response, context_blocks, out_of_domain=out_of_domain)
            if len(alignment_result) == 3:
                aligned_answer, annotations, telemetry = alignment_result
            else:  # backward safety
                aligned_answer, annotations = alignment_result
                telemetry = None
            rag_response = aligned_answer
            citations = annotations
            confidence_metrics = _compute_hallucination_metrics(rag_response, annotations, context_blocks) or {}
            if telemetry:
                confidence_metrics["citation_telemetry"] = telemetry
        except Exception as e:
            logging.warning(f"[CITATIONS] alignment failed: {e}")
    # Attach timing/intent/template metrics if enabled or available
    if timers_enabled or intent_result or template_used:
        if confidence_metrics is None:
            confidence_metrics = {}
        if timers_enabled:
            confidence_metrics["timers"] = timers
            confidence_metrics["results_counts"] = {
                "initial": len(results),
                "effective": len(effective_results),
                "summarized": bool(summarized_results)
            }
        if intent_result:
            confidence_metrics["intent"] = {
                "type": intent_result.intent.value,
                "confidence": intent_result.confidence,
                "reasons": intent_result.reasons,
                "features": intent_result.features
            }
        if template_used:
            confidence_metrics["template_used"] = True
        # Fusion dynamic weights (if enabled)
        try:
            dyn_w = get_fusion_calibrator().get_dynamic_weights()
            if dyn_w:
                confidence_metrics['fusion_dynamic_weights'] = dyn_w
        except Exception:
            pass
        # Cross-encoder metrics if any doc has cross_score
        if any('cross_score' in (r.get('metadata') or {}) for r in effective_results):
            ce_meta = {}
            for r in effective_results:
                md = r.get('metadata') or {}
                if 'cross_encoder_model' in md:
                    ce_meta['model'] = md.get('cross_encoder_model')
                    ce_meta['ms'] = md.get('cross_encoder_ms')
                    break
            ce_meta['re_ranked_docs'] = sum(1 for r in effective_results if 'cross_score' in (r.get('metadata') or {}))
            confidence_metrics['cross_encoder'] = ce_meta
        # Entity & claim verification (basic heuristic)
        if os.getenv('ENTITY_CLAIM_VERIFY','true').lower() == 'true':
            try:
                ec = verify_entities_and_claims(answer_text, effective_context_blocks)
                if ec:
                    confidence_metrics['entity_claim_verification'] = ec
            except Exception:
                pass
    # Numeric verification (post-answer)
    try:
        numeric_metrics = verify_numbers(rag_response, context_blocks)
        if numeric_metrics:
            if confidence_metrics is None:
                confidence_metrics = {}
            confidence_metrics['numeric_verification'] = numeric_metrics
    except Exception:
        pass

    return QueryResponse(
        answer=rag_response or "No answer generated.",
        user_id=user_id,
        session_id=session_id,
        access_token=input_data.access_token,
        chat={"query": query_text, "llm_response": rag_response or "No answer generated."},
        context_blocks=context_blocks,
        session_history=session_history,
        memory_usage=len(session_history),
        citations=citations,
        confidence=confidence_metrics
    )





from threading import Lock
from fastapi import BackgroundTasks
import logging
session_pdf_data = {}
session_pdf_lock = Lock()


import httpx
try:
    import pdfplumber
except Exception:
    pdfplumber = None  # type: ignore

async def process_pdf_ocr(session_id, user_id, access_token, pdf_bytes, user_focus=None):

    # File size limit (20MB)
    if len(pdf_bytes) > 20 * 1024 * 1024:
        msg = "PDF file too large (>20MB)."
        with session_pdf_lock:
            session_pdf_data[session_id] = {"status": "error", "error": msg}
        pdf_sessions_collection.update_one(
            {"session_id": session_id, "user_id": user_id},
            {"$set": {"status": "error", "error": msg}}, upsert=True)
        return


    extracted_text = ""
    # Check if PDF is text-only
    is_text_only = False
    if pdfplumber is not None:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    if page.extract_text():
                        is_text_only = True
                    else:
                        is_text_only = False
                        break
        except Exception as e:
            logging.warning(f"pdfplumber failed to open PDF: {e}")

    pdfco_api_key = os.getenv("PDFCO_API_KEY")
    if is_text_only and pdfco_api_key:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                files = {"file": ("input.pdf", pdf_bytes, "application/pdf")}
                data = {"async": True, "inline": True}
                headers = {"x-api-key": pdfco_api_key}
                r = await client.post("https://api.pdf.co/v1/pdf/convert/to/text", files=files, data=data, headers=headers)
                if r.status_code == 200 and r.json().get("jobId"):
                    job_id = r.json()["jobId"]
                    # Poll for result
                    for _ in range(60):
                        job_status = await client.get(f"https://api.pdf.co/v1/job/check?jobid={job_id}", headers=headers)
                        status = job_status.json().get("status")
                        if status == "success":
                            result_url = job_status.json().get("resultUrl")
                            result_resp = await client.get(result_url)
                            extracted_text = result_resp.text
                            break
                        elif status == "failed":
                            break
                        await httpx.AsyncClient()._sleep(5)
            # If after polling, no text was extracted, set error status
            if not extracted_text:
                status = "error"
                with session_pdf_lock:
                    session_pdf_data[session_id] = {
                        "user_id": user_id,
                        "access_token": access_token,
                        "pdf_text": "",
                        "questions": [],
                        "answers": [],
                        "status": status,
                        "error": "PDF.co API did not return text."
                    }
                pdf_sessions_collection.update_one(
                    {"session_id": session_id, "user_id": user_id},
                    {"$set": {
                        "session_id": session_id,
                        "user_id": user_id,
                        "access_token": access_token,
                        "pdf_text": "",
                        "questions": [],
                        "answers": [],
                        "status": status,
                        "error": "PDF.co API did not return text."
                    }},
                    upsert=True
                )
        except Exception as e:
            logging.warning(f"PDF.co API failed: {e}")
    else:
        # OCR fallback logic
        # 1. Try OCR.Space API first
        try:
            text = ocr_space_image(pdf_bytes)
            if text:
                extracted_text = text
        except Exception as e:
            logging.warning(f"OCR.Space failed: {e}")

        # 2. Tesseract fallback (only if optional deps are available)
        if not extracted_text and (pytesseract is not None and convert_from_bytes is not None):
            try:
                if os.name == "nt":
                    pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
                else:
                    pytesseract.pytesseract_cmd = "/usr/bin/tesseract"
                for i, page_img in enumerate(convert_from_bytes(pdf_bytes), 1):
                    page_text = pytesseract.image_to_string(page_img, lang="eng")
                    extracted_text += f"\n--- Page {i} (Tesseract) ---\n{page_text}\n"
            except Exception as e2:
                logging.warning(f"Tesseract OCR failed: {e2}")

        # 3. EasyOCR fallback
        if not extracted_text:
            try:
                import easyocr
                reader = easyocr.Reader(['en'])
                for i, page_img in enumerate(convert_from_bytes(pdf_bytes), 1):
                    page_img.save(f"temp_page_{i}.png")
                    result = reader.readtext(f"temp_page_{i}.png")
                    page_text = "\n".join([item[1] for item in result])
                    extracted_text += f"\n--- Page {i} (EasyOCR) ---\n{page_text}\n"
            except Exception as e3:
                logging.warning(f"EasyOCR failed: {e3}")

    # Save partial or final result
    status = "done" if extracted_text else "error"
    with session_pdf_lock:
        session_pdf_data[session_id] = {
            "user_id": user_id,
            "access_token": access_token,
            "pdf_text": extracted_text,
            "questions": [],
            "answers": [],
            "status": status,
            "error": "" if extracted_text else "Extraction failed."
        }
    if pdf_sessions_collection:
        pdf_sessions_collection.update_one(
            {"session_id": session_id, "user_id": user_id},
            {"$set": {
                "session_id": session_id,
                "user_id": user_id,
                "access_token": access_token,
                "pdf_text": extracted_text,
                "questions": [],
                "answers": [],
                "status": status,
                "error": "" if extracted_text else "Extraction failed."
            }},
            upsert=True
        )
    if extracted_text and user_focus:
        prompt = f"""
        You are an intelligent assistant.
        Analyze the following PDF content with focus on: {user_focus}

        PDF Content:
        {extracted_text}
        """
        llm_response = llm_engine.chat(prompt=prompt)
        save_chat(
            user_id=user_id,
            session_id=session_id,
            access_token=access_token,
            query_text=f"PDF Analysis Focus: {user_focus}",
            resolved_query=f"PDF Analysis: {user_focus}",
            llm_response=llm_response,
            source_docs=[{"chunk": extracted_text[:500]}]
        )
        with session_pdf_lock:
            session_pdf_data[session_id]["summary"] = llm_response
    logging.info(f"PDF extraction completed for session {session_id}, status: {status}")






 


# ===================== Standalone PDF Analyser (no RAG changes) ===================== #
class PDFAnalyzeResponse(BaseModel):
    user_id: str
    session_id: str
    pages: int
    ocr_engine: str
    focus: Optional[str] = None
    analysis: dict
    summary: str
    citations: Optional[list] = None
    readable: Optional[str] = None
    readable_style: Optional[str] = None


from threading import Lock
session_pdf_data = {}
session_pdf_lock = Lock()

@app.post("/analyze-pdf")
async def analyze_pdf(
    pdf_file: UploadFile = None,
    user_focus: str = Form(None),
    user_id: str = Form(...),
    session_id: str = Form(None),
    access_token: str = Form(None),
    query: str = Form(None)
):
    try:
        # Quick identity reply: if user asked who/what this is
        try:
            if is_identity_query(query):
                reply = "iam doxi ai assistant developed by dealdox"
                # attempt to record chat if session provided
                try:
                    save_chat(user_id, session_id, access_token, query, query, reply, [])
                except Exception:
                    pass
                return {"status": "ok", "answer": reply, "user_id": user_id, "session_id": session_id}
        except Exception:
            pass
        # If query is provided and session_id exists, always answer ONLY from pdf_sessions collection
        if query and session_id:
            # Always answer PDF queries from Mongo-stored PDF text (no embeddings/RAG).
            pdf_session_doc = None
            try:
                pdf_session_doc = pdf_sessions_collection.find_one({"session_id": session_id, "user_id": user_id}) if pdf_sessions_collection else None
            except Exception:
                pdf_session_doc = None
            if not pdf_session_doc or not pdf_session_doc.get("pdf_text"):
                return JSONResponse({"status": "error", "message": "No PDF data found for this session/user."}, status_code=404)
            pdf_text = pdf_session_doc["pdf_text"]
            # Build a strict prompt that uses only the PDF content. No embeddings or calls to /query.
            prompt = (
                "Answer the following question using ONLY the PDF content below. "
                "If the answer is not in the PDF, reply 'Not found in PDF.'\n\n"
                "PDF Content:\n" + str(pdf_text) + "\n\n"
                "Question: " + str(query)
            )
            llm_response = llm_engine.chat(prompt=prompt)
            try:
                if pdf_sessions_collection:
                    pdf_sessions_collection.update_one(
                        {"session_id": session_id, "user_id": user_id},
                        {"$push": {"questions": query, "answers": llm_response}},
                    )
            except Exception:
                pass
            return {
                "status": "ok",
                "answer": llm_response,
                "user_id": user_id,
                "session_id": session_id,
                "questions_answered(exception)": len(pdf_session_doc.get("questions", [])) + 1
            }
        # Otherwise, handle PDF upload and store (or fetch existing PDF text from Mongo if no file)
        if pdf_file is None:
            # If no file uploaded, try to fetch stored PDF text for this session from Mongo
            if session_id and user_id:
                pdf_session_doc = None
                try:
                    pdf_session_doc = pdf_sessions_collection.find_one({"session_id": session_id, "user_id": user_id}) if pdf_sessions_collection else None
                except Exception:
                    pdf_session_doc = None
                # If Mongo doesn't have it, check in-memory session cache created by prior uploads in this process
                if (not pdf_session_doc or not pdf_session_doc.get("pdf_text")) and session_id in session_pdf_data:
                    pdf_session_doc = session_pdf_data.get(session_id)
                if not pdf_session_doc or not pdf_session_doc.get("pdf_text"):
                    return JSONResponse({"status": "error", "message": "No PDF data found for this session/user."}, status_code=404)
                # Use stored PDF text
                extracted_text = pdf_session_doc["pdf_text"]
                # Build prompt for LLM using only stored PDF content
                prompt = f"""
        You are an intelligent assistant.
        Analyze the following PDF content with focus on: {user_focus}

        PDF Content:
        {extracted_text}
        """
                prompt_text = f"Analyze the following PDF content with focus: {user_focus}\n\n{extracted_text}"
                llm_response = llm_engine.chat(prompt=prompt_text)
                # Optionally push question/answer history into the session doc
                try:
                    if pdf_sessions_collection:
                        pdf_sessions_collection.update_one(
                            {"session_id": session_id, "user_id": user_id},
                            {"$push": {"questions": query or "analyze", "answers": llm_response}},
                        )
                except Exception:
                    pass
                # Save chat for memory/history
                try:
                    save_chat(
                        user_id=user_id,
                        session_id=session_id,
                        access_token=access_token,
                        query_text=f"PDF Analysis Focus: {user_focus}" if user_focus else "PDF Analysis",
                        resolved_query=f"PDF Analysis: {user_focus}" if user_focus else "PDF Analysis",
                        llm_response=llm_response,
                        source_docs=[{"chunk": extracted_text[:500]}]
                    )
                except Exception:
                    pass
                return {
                    "status": "ok",
                    "user_id": user_id,
                    "session_id": session_id,
                    "summary": {"text": llm_response},
                    "chat": {
                        "query": f"PDF Analysis Focus: {user_focus}" if user_focus else "PDF Analysis",
                        "llm_response": llm_response
                    },
                    "extracted_by": "mongo"
                }
            # No file and no session context to fetch from
            return JSONResponse({"status": "error", "message": "No PDF file uploaded and no session_id provided to fetch stored PDF."}, status_code=400)
        # Use robust extractor: save upload to temp file and call extractor
        import tempfile
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            pdf_bytes = await pdf_file.read()
            tmp.write(pdf_bytes)
            tmp.flush()
            tmp.close()
            from pdf_synopsis.pdf_robust_extractor import extract_pdf_text_robust
            extracted_text = extract_pdf_text_robust(tmp.name)
        finally:
            try:
                if tmp and os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except Exception:
                pass
        if not extracted_text or not extracted_text.strip():
            return JSONResponse({"status": "error", "message": "No text found in PDF (extraction failed)."}, status_code=400)
        # Auto-generate session_id if not provided
        if not session_id:
            session_id = str(uuid4())
        # Store PDF data in session (thread-safe)
        with session_pdf_lock:
            session_pdf_data[session_id] = {
                "user_id": user_id,
                "access_token": access_token,
                "pdf_text": extracted_text,
                "questions": [],
                "answers": []
            }
        # Store PDF data in MongoDB
        pdf_sessions_collection.update_one(
            {"session_id": session_id, "user_id": user_id},
            {"$set": {
                "session_id": session_id,
                "user_id": user_id,
                "access_token": access_token,
                "pdf_text": extracted_text,
                "questions": [],
                "answers": []
            }},
            upsert=True
        )
        # Build prompt for LLM and use shared RAG helper
        prompt_text = f"Analyze the following PDF content with focus: {user_focus}\n\n{extracted_text}"
        llm_response = llm_engine.chat(prompt=prompt_text)
        # Save conversation to DB (make sure save_chat exists)
        try:
            save_chat(
                user_id=user_id,
                session_id=session_id,
                access_token=access_token,
                query_text=f"PDF Analysis Focus: {user_focus}",
                resolved_query=f"PDF Analysis: {user_focus}",
                llm_response=llm_response,
                source_docs=[{"chunk": extracted_text[:500]}]
            )
        except Exception:
            pass
        return {
            "status": "ok",
            "user_id": user_id,
            "session_id": session_id,
            "access_token": access_token,
            "summary": {"text": llm_response},
            "chat": {
                "query": f"PDF Analysis Focus: {user_focus}",
                "llm_response": llm_response
            },
            "extracted_by": "ocr"
        }
    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )





@app.post("/generate-report")
async def generate_report(request: ReportRequest):  # type: ignore
    """Generate a structured analytical report (no graphs).

    Returns:
      report: markdown body
      sections: structured sections
      metrics: aggregated numeric/account metrics
      meta: echo of preferences & format
    """
    from app.db.mongo import get_user_profile
    # Merge preferences
    user_profile = get_user_profile(request.user_id) if hasattr(request, 'user_id') else {}
    effective_preferences = user_profile.get('preferences', {})
    if request.preferences:
        effective_preferences.update(request.preferences)

    # Build Mongo filter from request.filters (if any)
    mongo_filter = {}
    filter_summary_parts = []
    if request.filters:
        f = request.filters
        # Account filter
        acct = f.get('account') or f.get('account_name') if isinstance(f, dict) else None
        if acct:
                snippets = []
                for ev in _ev[:4]:
                    quoted = ev["snippet"].replace("\n", " ")
                    if len(quoted) > 420:
                        quoted = quoted[:420].rstrip() + "…"
                    snippets.append(quoted)
                llm_response = "\n\n".join(snippets).strip()
        def _parse_dt(val):
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except Exception:
                return None
        if date_from:
            dtf = _parse_dt(date_from)
            if dtf:
                date_range['$gte'] = dtf
        if date_to:
            dtt = _parse_dt(date_to)
            if dtt:
                date_range['$lte'] = dtt
        if date_range:
            # Try 'date' field first; fallback to created_at
            mongo_filter['$or'] = [
                {"date": date_range},
                {"created_at": date_range},
                {"createdAt": date_range}
            ]
            filter_summary_parts.append(f"date:{date_from or '*'}→{date_to or '*'}")
        # Amount range
        amt_range = {}
        min_amount = f.get('min_amount') or f.get('min')
        max_amount = f.get('max_amount') or f.get('max')
        def _num(val):
            try:
                if val is None:
                    return None
                return float(val)
            except Exception:
                return None
        if (m := _num(min_amount)) is not None:
            amt_range['$gte'] = m
        if (m := _num(max_amount)) is not None:
            amt_range['$lte'] = m
        if amt_range:
            mongo_filter['amount'] = amt_range
            filter_summary_parts.append(f"amount:{amt_range}")
        # Keyword simple match across description/notes fields
        kw = f.get('keyword') or f.get('q')
        if kw:
            # We'll post-filter in Python if no text index
            filter_summary_parts.append(f"kw:{kw}")
    # Pull global quotes for baseline metrics
    all_quotes = list(quotes_collection.find({}))
    global_metrics = aggregate_quotes(all_quotes)
    if global_metrics.get('total_quotes', 0) == 0:
        return {
            "report": "No quote data available to generate report.",
            "sections": [],
            "metrics": global_metrics,
            "meta": {"report_format": request.report_format, "instructions": request.report_instructions},
            "filter_summary": None
        }

    # Apply mongo filter (except keyword) then optional keyword pass
    if mongo_filter:
        filtered_quotes = list(quotes_collection.find(mongo_filter))
    else:
        filtered_quotes = all_quotes
    # Keyword filter (case-insensitive contains on a few fields)
    if request.filters and (kw := (request.filters.get('keyword') or request.filters.get('q'))):
        kw_lower = kw.lower()
        candidate_fields = ['description', 'notes', 'comment', 'product_name']
        filtered_quotes = [q for q in filtered_quotes if any(
            isinstance(q.get(cf), str) and kw_lower in q.get(cf).lower() for cf in candidate_fields
        )]
    filtered_metrics = aggregate_quotes(filtered_quotes)
    filter_summary = ", ".join(filter_summary_parts) if filter_summary_parts else None
    # Choose which set to feed into report body (focus on filtered subset if it is smaller or a filter applied)
    quotes_for_report = filtered_quotes if filter_summary or (filtered_metrics.get('total_quotes') < global_metrics.get('total_quotes')) else all_quotes
    active_metrics = filtered_metrics if quotes_for_report is filtered_quotes else global_metrics

    # Conversation history (last 5)
    history_cursor = memory_collection.find({"user_id": request.user_id, "session_id": request.session_id})
    session_history = []
    for entry in history_cursor:
        chats = entry.get("chats", [])
        for chat in chats:
            q = chat.get("query_text")
            a = chat.get("llm_response")
            if q and a:
                session_history.append(f"User: {q}\nAgent: {a}")

    report_body = build_report(
        query=request.query,
        report_format=request.report_format,
        instructions=request.report_instructions or "",
        prefs=effective_preferences,
        metrics=active_metrics,
        quotes=quotes_for_report,
        history=session_history
    )
    # Append comparison section if filtered subset differs
    if filter_summary and filtered_metrics.get('total_quotes') != global_metrics.get('total_quotes'):
        diff_lines = ["## Filter Focus",
                      f"Filters Applied: {filter_summary}",
                      f"Filtered Quotes: {filtered_metrics.get('total_quotes')} / Global: {global_metrics.get('total_quotes')}" ]
        if filtered_metrics.get('top_accounts'):
            topf = ", ".join([f"{a}({round(d['amount_sum'],2)})" for a,d in filtered_metrics.get('top_accounts', [])])
            diff_lines.append(f"Top Accounts (Filtered): {topf}")
        report_body += "\n\n" + "\n".join(diff_lines)
    sections = build_structured_sections(active_metrics, quotes_for_report, request.report_format)
    if filter_summary:
        sections.insert(1, {"title": "Filter Focus", "body": f"Filters Applied: {filter_summary}\nFiltered Quotes: {filtered_metrics.get('total_quotes')} out of {global_metrics.get('total_quotes')} total"})
    return {
        "report": report_body,
        "sections": sections,
        "metrics": global_metrics,
        "metrics_filtered": filtered_metrics if filter_summary else None,
        "meta": {
            "report_format": request.report_format,
            "instructions": request.report_instructions,
            "preferences": effective_preferences
        },
        "filter_summary": filter_summary,
        "user_id": request.user_id,
        "session_id": request.session_id
    }

# Diagnostics endpoint
@app.get("/diagnostics/hybrid")
async def diagnostics_hybrid():
    """Return recent hybrid retrieval timing metrics and current fusion weights."""
    from app.core.diagnostics import get_retrieval_metrics
    calib = get_fusion_calibrator()
    dyn = {}
    try:
        dyn = calib.get_dynamic_weights()
    except Exception:
        dyn = {}
    return {
        "dynamic_weights": dyn,
        "auto_calibration_enabled": calib.enabled,
        "retrieval_metrics": get_retrieval_metrics()
    }

@app.get("/diagnostics/query")
async def diagnostics_query(q: str, k: int = 10):
    """Return detailed retrieval diagnostics for a single ad-hoc query.

    Includes vector/lexical raw lists (truncated to k), fused candidates, feature vectors.
    """
    try:
        from app.core.hybrid_retrieval import hybrid_diagnostics
        diag = hybrid_diagnostics(q, retriever, k=k)
        return {"query": q, **diag}
    except Exception as e:
        return {"query": q, "error": str(e)}

@app.get("/diagnostics/embeddings")
async def diagnostics_embeddings():
    """Report embedding provider configuration and local E5 path status.

    Lightweight check only; does not load large models.
    """
    try:
        import os
        from app.core.embeddings_fallback import (
            list_active_embedding_providers,
            E5_LOCAL_PATH,
            DISABLE_E5_SENTENCE_TRANSFORMERS,
            E5_EFFECTIVE_DISABLED,
            E5_DISABLED_REASON,
        )
        providers = []
        try:
            providers = list_active_embedding_providers()
        except Exception:
            providers = []
        e5_path = E5_LOCAL_PATH
        e5_exists = False
        try:
            e5_exists = bool(e5_path and os.path.exists(e5_path))
        except Exception:
            e5_exists = False
        return {
            "active_providers": providers,
            "e5": {
                "disabled_env": bool(DISABLE_E5_SENTENCE_TRANSFORMERS),
                "disabled_effective": bool(E5_EFFECTIVE_DISABLED),
                "disabled_reason": E5_DISABLED_REASON,
                "local_path": e5_path,
                "local_path_exists": e5_exists,
            },
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/diagnostics/deep_query")
async def diagnostics_deep_query(q: str, k: int = 25):
    """Deep diagnostics: expose raw candidates (vector + lexical), fused feature vectors,
    dynamic fusion weights, and cross-encoder metadata. Intended for offline analysis.

    WARNING: Do not expose in production without auth; can leak internal feature scores.
    """
    try:
        from app.core.hybrid_retrieval import hybrid_diagnostics
        from app.core.fusion_autotune import get_fusion_calibrator
        diag = hybrid_diagnostics(q, retriever, k=k)
        calib = get_fusion_calibrator()
        weights = {}
        try:
            weights = calib.get_dynamic_weights() or {}
        except Exception:
            weights = {}
        return {"query": q, "k": k, "dynamic_weights": weights, **diag}
    except Exception as e:
        return {"query": q, "error": str(e)}

@app.get("/diagnostics/cache")
async def diagnostics_cache():
    try:
        from app.core.caching import cache_diagnostics
        return cache_diagnostics()
    except Exception as e:
        return {"error": str(e)}

@app.get('/diagnostics/ontology')
async def diagnostics_ontology(sample: str | None = None):
    try:
        from app.core.ontology import load_alias_map, ontology_boost
        omap = load_alias_map()
        demo = None
        if sample:
            demo = []
            for canon, aliases in list(omap.items())[:5]:
                b = ontology_boost(sample, ' '.join([canon]+aliases))
                demo.append({'canonical': canon, 'aliases': aliases, 'demo_boost': b})
        return {'aliases': omap, 'demo': demo}
    except Exception as e:
        return {'error': str(e)}


# Endpoint: Coreference resolution (SpanBERT-based)
@app.post("/coreference/resolve")
async def resolve_coref(request: CoreferenceRequest):
    resolved = resolve_coreference(request.text, request.context)
    return {
        "resolved_text": resolved,
        "user_id": getattr(request, 'user_id', None),
        "session_id": getattr(request, 'session_id', None)
    }

# Endpoint: Number-accurate retrieval (regex extraction, hybrid search)
@app.post("/retrieval/number_accurate")
async def number_accurate_retrieval(request: NumberAccurateRetrievalRequest):
    numbers = extract_numbers_from_text(request.query)
    # Example: parse date range from query (stub, expand as needed)
    date_range = None
    # If you want to support date filtering, parse dates from query here
    filtered_docs = filter_documents_by_metadata(request.documents, number_list=numbers, date_range=date_range)
    return {
        "filtered_documents": filtered_docs,
        "numbers": numbers,
        "user_id": getattr(request, 'user_id', None),
        "session_id": getattr(request, 'session_id', None)
    }



# Endpoint: Get enriched memory context for a session

# Endpoint: Get enriched memory context for a session (with personalization)
@app.post("/memory/context")
async def get_memory_context(request: MemoryContextRequest):
    # Pass preferences to enrichment (expand logic in enrichment module as needed)
    context = get_enriched_memory_context(
        session_id=request.session_id,
        n=request.n,
        weight_recent=request.weight_recent,
        preferences=request.preferences,
        user_id=request.user_id
    )
    return {
        "context": context,
        "user_id": request.user_id,
        "session_id": request.session_id
    }

# Endpoint: Format structured prompt with token limiting and weighted history

# Endpoint: Format structured prompt with token limiting, weighted history, and personalization
@app.post("/prompt/structured")
async def get_structured_prompt(request: StructuredPromptRequest):
    # Pass preferences to prompt construction (expand logic in module as needed)
    response = format_structured_data(request.documents, request.query)
    # Add user_id and session_id if present in preferences
    user_id = request.preferences.get('user_id') if request.preferences else None
    session_id = request.preferences.get('session_id') if request.preferences else None
    response["user_id"] = user_id
    response["session_id"] = session_id
    return response

@app.post("/feedback")
async def submit_feedback(
    user_id: str = Body(...),
    session_id: str = Body(...),
    query_text: str = Body(...),
    feedback: str = Body(...)
):
    # Store feedback in memory_collection for learning
    memory_collection.update_one(
        {"user_id": user_id, "session_id": session_id, "chats.query_text": query_text},
        {"$set": {"chats.$.feedback": feedback}}
    )
    tuned = auto_tune_preferences(user_id, feedback, recent_query=query_text)
    return {"status": "success", "feedback": feedback, "updated_preferences": tuned}