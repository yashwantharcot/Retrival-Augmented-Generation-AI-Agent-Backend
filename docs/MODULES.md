# Module Guide

This is a concise map of key modules and their responsibilities.

## app/main.py
- FastAPI app setup and router inclusion.
- Report generation (`/generate-report`).
- Diagnostics endpoints.
- Personalization: `_normalize_prefs`, `build_llm_prompt`, `finalize_answer`.
- Grounding: `align_answer_with_context`, hallucination metrics `_compute_hallucination_metrics`.
- Query endpoints: `/query`, `/query/advanced` plus PDF-related handling and `/pdf-session-query`.
- PDF session storage access via `pdf_sessions_collection` (Mongo).

## app/api/routes.py
- `/api/ping` sanity endpoint.
- Memory endpoints:
  - POST `/api/memory`: insert memory
  - GET `/api/memory/{session_id}`: fetch session memory chats
  - POST `/api/memory/search`: search by embedding vector
- RAG helpers: `/api/ask` and `/api/rag` (pronoun substitution and conversation save).

## app/api/feedback.py
- Feedback ingestion: `/feedback/click` and `/feedback/rate`.
- Maintains in-memory positive/negative counters and emits scale factors.
- Monkey-patches fusion calibrator dynamic weight getter to apply scales.

## app/core/retriever.py
- Vector retrieval from MongoDB with optional semantic metadata prefilter and preference re-ranking.
- Embedding caching and collection/index selection (via env USE_OPENAI).
- Helper parsers for metadata filters.

## app/core/embeddings_fallback.py
- Provider-abstracted embeddings with retries and sanitize controls.
- OpenAI, Gemini, and Intfloat E5 support; runtime checks and local path preference.
- Mongo watcher threads (optional) to update embeddings on source collection changes.
- `retrieve_hybrid` helper for simple hybrid path over two collections.

## app/core/llm.py
- `OpenAIEngine` for text generation and chat.
- Paid-first with optional free model fallbacks (Groq/Google) and controlled prompt logging.
- Provides a global `llm_engine` used by `app/main.py` and PDF session flow.

## app/reporting/report_engine.py
- Quote aggregation across accounts, numeric field summaries, and basic reporting sections.
- `build_report` outputs markdown with optional recommendations.

## app/db/vector_store.py
- `$vectorSearch` pipelines based on detected embedding dimension.
- Returns projected fields for chunk text, metadata, structured_data, and score.

## app/db/mongo.py
- Multiple utility sections: client initialization, conversation history helpers, and generic CRUD.
- Exposes `db`, `memory_collection`, and helpers such as `save_conversation`.
- Note: file contains multiple definitions (legacy + new); prefer consolidated interfaces used by current imports.

## app/memory/*
- `memory_manager.py`: session-scoped memory storage and entity/query helpers.
- `memory_pipeline.py`: enrich query with memory (see file).
- `memory_entry.py`: dataclass/model for memory items.

## Other core modules
- `app/core/*` includes: caching, hybrid retrieval, fusion ranking, intent classification, ontology boosting, NER, entity verification, numeric verification, audit utilities. Consult function docstrings and names for extension points.

## pdf_synopsis/* (scoped)
- Standalone PDF analysis pipelines used during earlier iterations; current build keeps PDF session endpoints in `app/main.py`.

---

For environment and operations, see `docs/OPERATIONS.md` and `docs/CONFIG.md`.
