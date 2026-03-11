from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional
import tempfile
import os
from uuid import uuid4

from app.core.local_models import embed_texts, build_faiss_index, search_faiss, generate_answer
from pdf_synopsis.pdf_vector_pipeline import extract_pdf_text

router = APIRouter()

# Simple in-memory store for sessions: session_id -> {chunks, embeddings, index, arr}
pdf_sessions = {}


def chunk_text_simple(text: str, chunk_size_chars: int = 1200, overlap: int = 200):
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size_chars, length)
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap if end < length else end
    return [c for c in chunks if c]


class UploadResponse(BaseModel):
    session_id: str
    chunks: int


@router.post('/upload_pdf', response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...), session_id: Optional[str] = Form(None)):
    # Save uploaded file to temp and extract text
    suffix = os.path.splitext(file.filename)[1] if file.filename else '.pdf'
    sid = session_id or str(uuid4())
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        text = extract_pdf_text(tmp_path)
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(status_code=500, detail=f"PDF extraction failed: {e}")

    os.unlink(tmp_path)

    chunks = chunk_text_simple(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="No text extracted from PDF")

    # Compute embeddings and build FAISS
    embeddings = embed_texts(chunks)
    index, arr = build_faiss_index(embeddings)

    pdf_sessions[sid] = {
        'chunks': chunks,
        'embeddings': embeddings,
        'index': index,
        'arr': arr
    }

    return UploadResponse(session_id=sid, chunks=len(chunks))


class QueryRequest(BaseModel):
    session_id: str
    query: str
    top_k: Optional[int] = 5


@router.post('/query')
def query_pdf(req: QueryRequest):
    session = pdf_sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')

    q_emb = embed_texts([req.query])[0]
    ids, dists = search_faiss(session['index'], session['arr'], q_emb, top_k=req.top_k)

    # Build context from retrieved chunks
    context_blocks = []
    sources = []
    for idx in ids:
        try:
            context_blocks.append(session['chunks'][int(idx)])
            sources.append({'idx': int(idx)})
        except Exception:
            pass

    prompt = "Use the following extracted document excerpts to answer the question.\n\nContext:\n"
    for i, cb in enumerate(context_blocks):
        prompt += f"Excerpt {i+1}: {cb}\n\n"
    prompt += f"Question: {req.query}\nAnswer concisely and cite which excerpt you used (e.g., Excerpt 1)."

    answer = generate_answer(prompt)

    return {
        'answer': answer,
        'sources': sources,
        'session_id': req.session_id
    }
