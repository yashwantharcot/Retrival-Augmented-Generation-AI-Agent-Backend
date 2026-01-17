# Testing Notes

## Focused Tests
- tests/test_pdf_session_scoping.py
  - Validates that `/query` is blocked when a PDF session is active (env PDF_SESSION_BLOCK_QUERY=true)
  - Validates `/pdf-session-query` uses stored PDF text and records Q&A

- tests/test_pdf_analyze_endpoint.py (skipped)
  - Kept as reference for an older PDF analyze endpoint now removed

- tests/test_advanced_features.py
  - Covers preference re-ranking, auto-tune preferences, alignment metrics, adaptive requery, clustering, and hallucination risk levels

- tests/test_personalization.py
  - Validates detail scaling in prompt building, final answer trimming, and citation alignment behavior

## Running
- Use the provided VS Code task: "pytest focused tests"
- Or run `pytest -q` locally

## Tips
- If Mongo is not available, many retrieval tests may need stubbing or env overrides
- For deterministic LLM behavior in tests, monkeypatch `llm_engine.chat`
- Control thresholds with env vars to assert boundary conditions
