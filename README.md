````markdown
# RAG Agent

A modular Retrieval-Augmented Generation (RAG).

# RAG AI Agent (FastAPI)

## Run Locally
```bash
[on ddagent_env]
uvicorn app.main:app --host 0.0.0.0 --port 8000

uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning

uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level error
```

## PDF Analysis (New)

Upload a PDF and request analysis via available API endpoints (pdf analysis endpoints removed from this build).

A modular Retrieval-Augmented Generation (RAG).

# RAG AI Agent (FastAPI)

## Run Locally
```bash
[on ddagent_env]
uvicorn app.main:app --host 0.0.0.0 --port 8000



uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning
 


uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level error
````

## Troubleshooting

If you see an error like "module 'pyarrow' has no attribute 'PyExtensionType'" when starting the server
or importing `sentence-transformers` / `datasets`, this repository ships a small compatibility shim in
`app/__init__.py` that aliases `pyarrow.PyExtensionType` to `pyarrow.ExtensionType` when possible. This
prevents an ImportError caused by mismatched `pyarrow` and `datasets` versions.

Recommended long-term fixes:
- Pin `pyarrow` and `datasets` to compatible versions in your environment (for example: `pyarrow==12.0.1`,
  `datasets==2.21.0`) or follow the `datasets` project guidance.
- Upgrade/downgrade `sentence-transformers` to a version compatible with your stack.

The shim is a low-risk workaround. Prefer fixing dependency versions for production deployments.

Additionally, some environments may have an older `torch` (PyTorch) that doesn't expose
the `torch.compiler.disable` API used by `transformers`. A small no-op shim has been added
in `app/__init__.py` to make `@torch.compiler.disable` a safe no-op when missing. For a
long-term fix, pin PyTorch to a version that includes the `compiler` API (PyTorch >= 2.1
is typically required by newer `transformers` / `sentence-transformers`).