# DealdoxAgent RAG Architecture Overview

This document summarizes the current system design as implemented in this repository (branch: agent_improvement_branch). It reflects the code as of September 16, 2025.

## High-level Components

- FastAPI app (`app/main.py`)
  - Mounts routers from `app.api.feedback` (feedback events) and `app.api.routes` (session memory + RAG helpers mounted under `/api`).
  - Core endpoints for queries, diagnostics, PDF session handling, reporting, preferences, and memory.
  - Personalization layer: prompt shaping, metadata-aware context filtering, and response style enforcement.
  - Citation alignment / hallucination guard for answer-context grounding.
- Retrieval & fusion
  - Retriever (`app/core/retriever.py`): MongoDB Atlas Vector Search against OpenAI/Gemini collections, optional semantic metadata prefilter, user preference re-ranking.
  - Fusion/calibration hooks exist in `app/core/fusion_autotune.py` and are integrated via diagnostics and feedback nudge (`app/api/feedback.py` patches dynamic weights accessor).
- Embeddings (`app/core/embeddings_fallback.py`)
  - Tiered provider fallback: OpenAI → Gemini → Intfloat E5 (local/remote) with robust error handling and environment gating.
  - Text sanitation, tokenizer-based token counting, and provider-disable flags with diagnostics endpoint.
- LLM layer (`app/core/llm.py`)
  - Primary: OpenAI Chat Completions; fallback to Groq/Google “free” models (optionally disabled via env).
  - Central `llm_engine` instance used across the app.
- Data layer (MongoDB)
  - Config in `app/config.py`; vector store utilities in `app/db/vector_store.py` (dimension-based collection switch, `$vectorSearch`).
  - Memory collections: `dd_memory_entries_rag`, `pdf_sessions`, plus `conversation_history` and preference storage.
- Reporting (`app/reporting/report_engine.py`)
  - Aggregates quote data, builds structured markdown reports and sections.
- PDF session pipeline (in `app/main.py`)
  - PDF ingestion and OCR (pdf2image + pytesseract), stores per-session text into `pdf_sessions`.
  - Dedicated `/pdf-session-query` routes questions strictly to PDF content.
  - Optionally blocks general `/query` while a PDF session is active.

## Data Flow

1) Query path
- Client → POST `/query` (or `/query/advanced`)
- Optional block if PDF session is active (env: PDF_SESSION_BLOCK_QUERY)
- Retriever fetches context (vector search) and applies preference re-ranking
- Personalization builds LLM prompt with metadata-filtered, token-budgeted context
- LLM generates draft → alignment adds confidence tags/citations → final style and length normalization
- Memory/prefs updated, response returned

2) PDF session path
- Client → POST `/analyze-pdf` (not documented here; see code) to upload/extract, or writes directly via `pdf_sessions`
- Client → POST `/pdf-session-query` uses only stored PDF text; also supports simple “page N” extraction
- Q&A appended to `pdf_sessions.questions/answers`

3) Reporting path
- Client → POST `/generate-report` with filters/preferences
- Pulls quotes dataset from Mongo, aggregates metrics, builds markdown + structured sections

## Personalization and Guardrails

- Prompt builder: tone/detail/style and metadataFilter options with token-budget enforcement and optional overflow summary inclusion.
- Alignment: sentence-level n-gram overlap against context blocks to assign confidence (high/medium/low) and citations `[C#]`, with optional telemetry.
- Provider noise sanitizer: removes boilerplate warnings from fallback providers.

## Embeddings and Retrieval

- Embeddings
  - OpenAI `text-embedding-3-small` (1536-dim)
  - Gemini `models/embedding-001` (1024-dim)
  - Intfloat E5 (via sentence-transformers), optionally local path; disabled by default unless runtime supports Torch≥2.1 or float8 types and env allows.
- Vector store
  - MongoDB collections: `dd_accounts_chunks` (OpenAI) and `dd_accounts_chunks_gemini` (Gemini)
  - `$vectorSearch` pipelines with projection and optional metadata `$match`
  - Semantic metadata prefilter embeds candidate categorical values and builds `$or` filters for narrowing

## Feedback & Adaptive Behavior

- Clicks/ratings endpoints scale fusion dynamic weights (bounded multiplicative nudge) without overwriting auto-calibration.
- User preferences influence re-ranking and can be updated via endpoints.

## Key Trade-offs

- Robust fallbacks and shims (pyarrow, torch.compiler) allow broader environment compatibility.
- Token-aware context assembly prevents overflows but may omit lower-ranked blocks; overflow summary heuristics mitigate.
- Simpler citation heuristics prioritize speed over semantic precision; telemetry supports offline analysis.

---

See `docs/API.md` for endpoints and `docs/MODULES.md` for module summaries.
