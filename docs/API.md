# API Reference

Base URL: default FastAPI app at root; `app.api.routes` is mounted under `/api`.

Note: Some PDF analysis upload endpoints were removed in this build; the PDF session query endpoint remains.

## Health
- GET `/` → `{ status: "RAG API is running" }`
- GET `/api/ping` → `{ ping: "pong" }`

## Reports
- POST `/generate-report`
  - Body: `{ query, session_id, user_id, preferences?, report_format?, report_instructions?, filters?, hybrid_retrieval? }`
  - Returns: `{ report (markdown), sections[], metrics, metrics_filtered?, meta, filter_summary?, user_id, session_id }`
  - Filters example: `{ account: "Acme", date_from: "2025-01-01", date_to: "2025-03-31", min_amount: 1000, keyword: "discount" }`

## Diagnostics
- GET `/diagnostics/hybrid` → dynamic fusion weights and retrieval metrics
- GET `/diagnostics/query?q=...&k=10` → retrieval diagnostics
- GET `/diagnostics/embeddings` → embedding provider status and local E5 path
- GET `/diagnostics/deep_query?q=...&k=25` → deep diagnostics with features and weights
- GET `/diagnostics/cache` → cache diagnostics
- GET `/diagnostics/ontology?sample=foo` → ontology alias map and optional demo boosts

## Querying
- POST `/query`
  - Body (QueryInput shape, see `app/main.py`): `{ session_id, user_id, access_token?, chat: { query }, preferences? }`
  - Behavior: may 409 if a PDF session is active and `PDF_SESSION_BLOCK_QUERY=true`.
  - Returns `QueryResponse` with fields like `{ answer, contextBlocks, citations, telemetry? }` (see code for full schema).
- POST `/query/advanced`
  - Similar to `/query` with additional payload fields for fine control; see implementation in `app/main.py`.

## PDF Session
- POST `/pdf-session-query`
  - Body: `QueryInput` (uses `chat.query` string)
  - Uses only stored PDF text from `pdf_sessions` for the given `user_id`/`session_id`.
  - Supports quick page extraction when user asks like "page 3".
  - Returns `{ status: "ok", answer, user_id, session_id, questions_answered }` or 404 if no pdf_text is present.
- GET `/pdf-session-status`
  - Returns current status for the session if implemented; referenced in code around PDF paths.

## Memory (mounted under /api)
- POST `/api/memory` → store a memory entry (see `MemoryEntry` in `app/api/routes.py`)
- GET `/api/memory/{session_id}?limit=50&user_id=...` → list chats for a session
- POST `/api/memory/search` → vector-like search over stored memories
- POST `/api/ask` → simple RAG wrapper
- POST `/api/rag` → pronoun resolution + RAG + persistence

## Feedback
- POST `/feedback/click` → `{ user_id, query, doc_id, source }`
- POST `/feedback/rate` → `{ user_id, query, rating(+1/-1), answer, comment? }`
  - Applies periodic scale updates to fusion dynamic weights (see `app/api/feedback.py`).

## Preferences
- GET `/preferences/{user_id}` → fetch stored user preferences
- POST `/preferences/update` → upsert preferences payload

## Models and Schemas
- QueryInput/QueryResponse and other Pydantic models are defined in `app/main.py` and `app/api/routes.py`. Refer to source for exact fields.

## Notes
- Auth and rate limiting are not included in this summary; add API gateway or FastAPI dependencies as needed.
- Do not expose deep diagnostics in production without authentication.
