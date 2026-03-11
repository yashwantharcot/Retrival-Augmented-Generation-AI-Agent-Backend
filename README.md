# 🤖 RAG AI Agent - Modular Backend & PDF Q&A

[![Live Demo](https://img.shields.io/badge/Live-Demo-brightgreen?style=for-the-badge&logo=streamlit)](https://retrival-augmented-generation-ai-agent-backend-smew7kqwqkcxvgs.streamlit.app/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python)](https://www.python.org/)

A high-performance, modular **Retrieval-Augmented Generation (RAG)** backend designed to power document-centric AI assistants. This repo handles the heavy lifting of document processing, vector embeddings, and conversational AI.

---

## 🚀 Experience the App
**Stop reading and start chatting!** You can try the live PDF Q&A interface hosted on Streamlit Cloud:

### ✨ [**Launch Live Demo**](https://retrival-augmented-generation-ai-agent-backend-smew7kqwqkcxvgs.streamlit.app/)

---

## 🛠️ Core Features

- **📄 Smart PDF Processing**: Automatic text extraction and intelligent chunking using `PyMuPDF` and `pdfplumber`.
- **🔍 Hybrid Vector Search**: Fast retrieval using cloud-based embeddings (OpenAI/Gemini) with a local FAISS or simple similarity fallback.
- **🧠 Collaborative RAG Pipeline**: Seamless orchestration of retrieval, conversational memory, and LLM generation.
- **⚡ High Performance**: Built on FastAPI with asynchronous endpoints for low-latency responses.
- **🌐 Cloud-Ready**: Fully migrated to the latest `google-genai` SDK for reliable cloud embeddings and generation.

---

## 🏗️ Technical Stack

- **Framework**: FastAPI (Backend), Streamlit (UI)
- **AI/LLM**: Google GenAI (Gemini), OpenAI, Groq
- **Vector DB**: FAISS (Local) / Simple similarity
- **Parsing**: PyMuPDF, pdfplumber
- **Deployment**: Railway (Backend), Streamlit Cloud (Frontend)

---

## 💻 Local Development

### Windows Setup
1. Clone the repository.
2. Run the automated setup script:
   ```powershell
   .\scripts\setup_windows.ps1
   ```
3. Start the Streamlit UI:
   ```powershell
   streamlit run streamlit_app.py
   ```

### Unix / macOS Setup
1. Run the setup script:
   ```bash
   chmod +x ./scripts/setup_unix.sh
   ./scripts/setup_unix.sh
   ```
2. Activate and Run:
   ```bash
   source .venv/bin/activate
   streamlit run streamlit_app.py
   ```

---

## 🔌 API Endpoints

The backend is accessible via FastAPI. To run the API server locally:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `POST /api/pdf-qa/upload_pdf`: Upload and process a PDF for querying.
- `GET /docs`: Interactive Swagger documentation.

---

## �️ Future Roadmap: The "Domain Search" Initiative
While this repository started as a general-purpose RAG backend, the next phase of this project is a specialized initiative:
- **Domain-Specific Datasets**: We are planning to integrate high-value datasets from specific industries (e.g., Medical, Legal, or Technical docs).
- **Pre-computed Embeddings**: The core search logic is already built and tested. The next step is simply processing these datasets into a vector database to provide a "Turn-key" search experience for specialized knowledge.

---

## �📝 Current Project Status
- **Active Migration Complete**: Transitioned from `google-generativeai` to the modern `google-genai` SDK.
- **Robustness**: Implemented fallback chains for embeddings to ensure high availability across environments (Local vs Railway).
- **Optimization**: Removed heavy local torch/transformers dependencies for lightweight cloud-native operation on Railway.

---

Built with ❤️ by [Arcot Yashwanth](https://github.com/yashwantharcot)