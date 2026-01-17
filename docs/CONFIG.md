# Configuration and Environment

This project is configured via environment variables (see `app/config.py`, `app/core/embeddings_fallback.py`, `app/core/llm.py`, and others).

## Core
- MONGODB_URI: MongoDB connection string
- MONGODB_DB: Optional alt DB name; default `dev_db` used in many places
- OPENAI_API_KEY: OpenAI client
- GOOGLE_API_KEY: Gemini client
- HF_API_KEY: HuggingFace (optional)

## Models
- LLM_MODEL: default OpenAI chat model (e.g., gpt-4o-mini)
- EMBEDDING_MODEL: default embedding model (text-embedding-3-small)
- USE_OPENAI: true/false to select OpenAI vs Gemini path for embeddings/retrieval
- DISABLE_FREE_MODELS: true to skip Groq/Google fallbacks in LLM
- SKIP_GOOGLE_FREE / SKIP_GROQ_FREE: granular toggles for free fallbacks

## Embeddings (fallbacks)
- USE_GEMINI_EMBEDDINGS: true/false
- DISABLE_E5_SENTENCE_TRANSFORMERS: true to avoid local E5 by default
- E5_MODEL_NAME: default intfloat/e5-base
- LOCAL_E5_BASE_PATH: local disk path for an offline E5 model (if available)
- E5_SHOW_PROGRESS: show progress bar during encode
- EMBED_MAX_CHARS: max characters per text to embed (sanitizer)
- STRIP_HTML_EMBED: true to strip HTML before embedding

## Personalization & Prompting
- PROMPT_TOKEN_BUDGET: integer token budget for prompt assembly (default 6000)
- ENABLE_CONTEXT_SUMMARY: true to add overflow summary block when trimming
- PROMPT_ADD_PROVENANCE: true to annotate provenance counts in prompt

## Alignment & Telemetry
- CITATION_BASE_THRESHOLD_SCORE: default 4
- CITATION_ADVISORY_THRESHOLD_SCORE: default 3
- CITATION_MIN_BIGRAM / CITATION_MIN_TRIGRAM: default 0
- CITATION_TELEMETRY_RETURN: true to include telemetry in responses

## Retrieval
- ENABLE_PREF_RERANK: true to apply user preference re-ranking
- ENABLE_SEMANTIC_META_PREFILTER: true to prefilter categorical metadata semantically
- SEMANTIC_META_FIELDS: comma list (default: account_name,owner,industry,region)
- SEMANTIC_META_MAX_VALUES: default 120
- SEMANTIC_META_TOP_K: default 3
- SEMANTIC_META_SIM_THRESHOLD: default 0.78
- PREF_RERANK_MAX_BOOST: default 0.4
- PREF_RERANK_KEYWORD_UNIT: default 0.08
- PREF_RERANK_FIELD_UNIT: default 0.12
- PREF_RERANK_DEMOTE_UNIT: default 0.05

## PDF Session
- PDF_SESSION_BLOCK_QUERY: true to 409-block general `/query` while a PDF session has pdf_text

## Feedback
- FEEDBACK_ENABLE: enable feedback weight nudging
- FEEDBACK_NUDGE_INTERVAL: e.g., 20
- FEEDBACK_NUDGE_ALPHA: e.g., 0.08

## Reporting
- REPORT_TOP_ACCOUNTS: default 5
- REPORT_MAX_QUOTES: default 50
- REPORT_INCLUDE_RAW: false

## Logging
- LOG_PROMPT_DEBUG: enable safe prompt logging
- LOG_FULL_PROMPT: log full prompts (use with caution; default false)
- PROMPT_LOG_LIMIT: default 4000 chars

Notes:
- Some modules read multiple env names; search the code for os.getenv usages for specifics.
- Prefer pinning package versions for production stability.
