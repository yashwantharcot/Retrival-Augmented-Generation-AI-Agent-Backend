# Operations: Setup, Run, and Maintenance

## Prerequisites
- Python 3.10+
- MongoDB Atlas or accessible MongoDB instance with vector search enabled and indexes configured
- Optional: Tesseract OCR installed for PDF OCR path

## Install
- Create and activate a virtual environment
- Install requirements: see `requirements.txt`

## Run (local)
- Set env variables (OPENAI_API_KEY, MONGODB_URI, etc.)
- Start API server:
  - Task: run api (uvicorn 8001): uvicorn app.main:app --host 127.0.0.1 --port 8001
  - Or: uvicorn app.main:app --host 0.0.0.0 --port 8000

## Tests
- Focused tests: Task "pytest focused tests" runs `pytest -q tests/test_pdf_session_scoping.py`
- Full tests: run `pytest` (may require additional setup data)

## Mongo Vector Indexes
- Collections:
  - dd_accounts_chunks (OpenAI, 1536-d)
  - dd_accounts_chunks_gemini (Gemini, 1024-d)
- Index names:
  - vector_index_v2
  - vector_index_gemini_v2
- Ensure `$vectorSearch` indexes exist; see `app/core/embeddings_fallback.py::verify_vector_indexes()` for checks.

## PDF Session Workflow
- Upload/extract PDF to populate `pdf_sessions.pdf_text` (OCR path available in `app/main.py`)
- Ask questions via POST `/pdf-session-query` with `{ user_id, session_id, chat: { query } }`
- If `PDF_SESSION_BLOCK_QUERY=true`, general `/query` will return 409 while pdf_text exists

## Observability
- Diagnostics endpoints under `/diagnostics/*` for retrieval, embeddings, cache, and ontology
- LOG_PROMPT_DEBUG to log prompting details (truncated unless LOG_FULL_PROMPT=true)

## Production Notes
- Protect diagnostics and PDF endpoints with authentication
- Pin versions for `pyarrow`, `datasets`, `torch`, `transformers`, and `sentence-transformers`
- Consider disabling free model fallbacks in production
- Scale feedback impact conservatively (see FEEDBACK_NUDGE_ALPHA)
