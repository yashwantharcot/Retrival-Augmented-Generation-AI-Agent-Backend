````markdown
# RAG Agent

A modular Retrieval-Augmented Generation (RAG).

## Purpose

This repository is a modular Retrieval-Augmented Generation (RAG) backend designed to
power document-centric assistants. It provides components for:

- Extracting and chunking text from PDFs and other documents.
- Building and querying vector indexes (embeddings + FAISS).
- A RAG pipeline that composes retrieval, memory, and LLM generation.
- FastAPI endpoints and a simple Streamlit prototype for local PDF Q&A.

Primary use-cases:
- Ask questions over uploaded PDFs and receive grounded answers with citations.
- Build a personal knowledge-base (KB) that can be queried conversationally.

This project includes an optional local prototype that uses free models:
`sentence-transformers/all-MiniLM-L6-v2` for embeddings and `google/flan-t5-small`
for generation (CPU-friendly). See the `streamlit_app.py` and `app/core/local_models.py`
for the prototype implementation.

## Quick Start (Windows)

1. Clone the repo and open PowerShell in the project folder.
2. Run the setup script to create a virtualenv and install dependencies (this installs
    a CPU build of PyTorch):

```powershell
.\scripts\setup_windows.ps1
```

3. Activate the virtualenv and run the Streamlit UI:

```powershell
. .\.venv\Scripts\Activate.ps1
streamlit run streamlit_app.py
```

## Quick Start (Unix / macOS)

```bash
./scripts/setup_unix.sh
source .venv/bin/activate
streamlit run streamlit_app.py
```

If you prefer not to install PyTorch via the scripts, you can manually install the
CPU wheel using the PyTorch CPU index shown in the scripts. If any command fails,
copy the terminal output and open an issue; I will help diagnose.

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

## Current status (work paused)

- Stopped active implementation work on the prototype at the user's request.
- Current activity: resolving local environment dependency issues so the Streamlit UI
    and local models can run. Key actions in progress or recently performed:
    - Installing and pinning compatible packages (`torch` CPU build, `numpy<2`,
        `transformers`, `sentence-transformers`).
    - Fixing a malformed legacy module in `pdf_synopsis/pdf_vector_pipeline.py`.
    - Adding a Streamlit UI (`streamlit_app.py`) and a local models helper
        (`app/core/local_models.py`) to run embeddings and generation with free models.

If you want to resume development now, run the environment setup commands in the
project root (activate your virtualenv first):

```bash
python -m pip install --upgrade pip setuptools wheel
pip uninstall -y torch torchvision torchaudio
pip install --upgrade "torch==2.2.1+cpu" --index-url https://download.pytorch.org/whl/cpu
pip install --upgrade "torchvision==0.17.1+cpu" --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt --upgrade
streamlit run streamlit_app.py
```

Open an issue or message me here with the output if any command fails and I'll help
diagnose the error.



https://retrival-augmented-generation-ai-agent-backend-smew7kqwqkcxvgs.streamlit.app/