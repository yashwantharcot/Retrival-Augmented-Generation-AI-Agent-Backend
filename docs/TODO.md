# DealdoxAgent — Prioritized TODO

This TODO is a single-source prioritized task list for finishing, hardening, and productionizing the agent. Use it as a checklist for sprints and PRs.

## How to use
- Mark tasks Done/Blocked in PR descriptions linking to commits.
- Keep each PR scoped to one subtask where feasible.
- Add estimate in story points or hours when triaging.

---

## Immediate (High impact, low effort)
1. Add auth + protect sensitive endpoints
   - Why: Prevent unauthorized PDF uploads, reports, diagnostics.
   - Files: app/main.py, app/api/routes.py, app/api/feedback.py
   - Actions:
     - Add dependency injection for an auth backend (JWT or API key).
     - Protect routes: /analyze-pdf, /generate-report, /api/feedback, diagnostics.
   - Commands: run dev server, test protected routes.
   - Acceptance: Unauthenticated requests return 401; authorized requests work.

2. Pin dependencies and run full test suite
   - Why: Reproducible environment.
   - Files: requirements.txt (create or update), pyproject.toml if present
   - Actions:
     - Freeze versions, add hashes, run pip-compile or pip freeze.
     - Run: pytest -q
   - Acceptance: All existing tests pass; CI reproducible.

3. Add CI pipeline
   - Why: Automated tests + linting on PRs.
   - Files: .github/workflows/ci.yml
   - Actions:
     - Steps: checkout, setup python, install pinned deps, pytest, flake8/mypy.
   - Acceptance: PRs run CI and report status.

4. Basic structured logging + request IDs
   - Why: Debugging and observability.
   - Files: app/main.py, app/config.py, possibly a logger util.
   - Actions:
     - Add JSON logging, wire request IDs via middleware.
   - Acceptance: Requests produce structured logs with request_id.

---

## Near-term (reliability & safety)
5. Harden provider fallbacks (timeouts, retries, circuit-breaker)
   - Why: Stable provider behavior.
   - Files: app/core/embeddings_fallback.py, app/core/llm.py
   - Actions:
     - Add backoff, request timeouts, and clear error classification.
   - Acceptance: Transient failures retried with backoff; deterministic errors short-circuit to fallback.

6. Add metrics & tracing
   - Why: Performance and error telemetry.
   - Files: app/main.py, add observability module
   - Actions:
     - Add Prometheus metrics for key latencies (embedding, vector search, LLM).
     - Instrument traces (OpenTelemetry).
   - Acceptance: Metrics visible locally and in CI smoke test.

7. Add end-to-end tests for core flows
   - Why: Prevent regressions (RAG + PDF).
   - Files: tests/test_rag_e2e.py, tests/test_pdf_flow_e2e.py
   - Actions:
     - Use small fixture dataset or mocked providers.
   - Acceptance: E2E tests pass in CI.

8. Vector index maintenance tools
   - Why: Reindexing, integrity checks.
   - Files: tools/reindex.py, app/db/vector_store.py
   - Actions:
     - Add scripts for reindexing a collection and sampling checks.
   - Acceptance: Reindex script runs and validates counts/embeddings.

---

## Medium-term (quality & UX)
9. Improve grounding & citation quality
   - Why: Reduce hallucinations and improve traceability.
   - Files: app/core/retriever.py, app/core/fusion_autotune.py, app/core/llm.py
   - Actions:
     - Add semantic overlap scoring + n-gram hybrid.
     - Surface provenance links to source documents.
   - Acceptance: Citation confidence correlates with human evaluation in small sample.

10. Prompt templating & versioning harness
    - Why: Controlled prompt experiments.
    - Files: app/core/prompt_builder.py (new), docs/prompt_versions.md
    - Actions:
      - Support multiple templates, track template version used in responses.
    - Acceptance: Templates selectable via env or API param; responses annotate template id.

11. Caching layer for embeddings/results
    - Why: Cost and latency reduction.
    - Files: app/core/cache.py, integrate in embeddings and retriever
    - Actions:
      - Add Redis or local disk cache for embeddings and common queries.
    - Acceptance: Cache hit rate measurable and reduces external calls.

12. Rate limiting and cost controls
    - Why: Prevent runaway costs.
    - Files: app/main.py, middleware
    - Actions:
      - Add token/call quotas per-user and global rate limits.
    - Acceptance: Throttled requests return 429 and logs show enforcement.

---

## Long-term (scale, governance, evaluation)
13. Model/version management and A/B evaluation framework
    - Why: Experiment safely across embeddings/LLMs.
    - Files: ops/ab_test_framework, app/core/llm.py
    - Actions:
      - Implement routing rules, record model id per response, run cohort experiments.
    - Acceptance: Metrics for model variants available and analyzable.

14. Data governance: PII detection & redaction, encryption-at-rest
    - Why: Compliance.
    - Files: ingestion pipeline, app/db/mongo.py
    - Actions:
      - Run PII detector at ingestion and redact/save encrypted fields.
    - Acceptance: PII flagged and redacted; KMS used for keys.

15. Offline evaluation & automated scoring harness
    - Why: Measure QA/grounding quality.
    - Files: eval/, tests/eval_runner.py
    - Actions:
      - Create synthetic QA dataset and compute EM/F1/ROUGE across models.
    - Acceptance: Scheduled evaluation reports.

---

## Quick maintenance & cleanup (small tasks)
- Add README update to include auth setup and env examples (docs/CONFIG.md).
- Add OpenAPI examples and response models for primary endpoints.
- Move large secrets to secure vault and remove from repo.
- Add Makefile or VS Code tasks: start, test, lint, reindex.

---

## Suggested first 7-day sprint
1. Add auth to endpoints + update docs (1–2 days)
2. Pin deps and add CI (1 day)
3. Add basic structured logging + metrics scaffolding (1–2 days)
4. Add E2E tests for PDF session and /query (1–2 days)

---

## Useful commands
- Run tests:
  - pytest -q
- Run dev server:
  - uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
- Freeze deps:
  - pip freeze > requirements.txt
- Run a single test:
  - pytest tests/test_pdf_session_scoping.py -q

---

## Notes
- Triage tasks into issues with linked PRs and assign owners.
- Prioritize safety (auth, rate limits, cost control) before broad external exposure.