import streamlit as st
import tempfile
import os
from uuid import uuid4

from app.api import pdf_qa
from app.core import local_models
from pdf_synopsis.pdf_vector_pipeline import extract_pdf_text

st.set_page_config(page_title="PDF Q&A (Local Models)", layout="wide")

st.title("PDF Q&A — Local Models (CPU)")
st.markdown("Upload a PDF, it will be processed locally (sentence-transformers + flan-t5-small). CPU-only supported.")

uploaded_file = st.file_uploader("Upload a PDF", type=["pdf"])
if uploaded_file is not None:
    if st.button("Process PDF"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name

        try:
            text = extract_pdf_text(tmp_path)
        except Exception as e:
            st.error(f"Failed to extract PDF text: {e}")
            os.unlink(tmp_path)
        else:
            os.unlink(tmp_path)
            chunks = pdf_qa.chunk_text_simple(text)
            if not chunks:
                st.error("No text extracted from PDF")
            else:
                embeddings = local_models.embed_texts(chunks)
                index, arr = local_models.build_faiss_index(embeddings)
                sid = str(uuid4())
                pdf_qa.pdf_sessions[sid] = {
                    'chunks': chunks,
                    'embeddings': embeddings,
                    'index': index,
                    'arr': arr
                }
                st.success(f"PDF processed. Session id: {sid}")
                st.write(f"Chunks: {len(chunks)}")

st.sidebar.header("Sessions")
session_keys = list(pdf_qa.pdf_sessions.keys())
selected = None
if session_keys:
    selected = st.sidebar.selectbox("Choose session", session_keys)
    if selected:
        sess = pdf_qa.pdf_sessions[selected]
        st.sidebar.write(f"Chunks: {len(sess['chunks'])}")

st.sidebar.markdown("---")
st.sidebar.markdown("Tip: after uploading, choose the session here to ask questions.")

st.header("Ask a question")
query = st.text_input("Question")
top_k = st.slider("Top K excerpts to use", min_value=1, max_value=8, value=5)
if st.button("Get Answer"):
    if not query:
        st.warning("Enter a question first")
    elif not selected:
        st.warning("Select a session (upload a PDF first)")
    else:
        sess = pdf_qa.pdf_sessions[selected]
        q_emb = local_models.embed_texts([query])[0]
        ids, dists = local_models.search_faiss(sess['index'], sess['arr'], q_emb, top_k=top_k)

        context_blocks = []
        for idx in ids:
            try:
                context_blocks.append(sess['chunks'][int(idx)])
            except Exception:
                pass

        prompt = "Use the following extracted document excerpts to answer the question.\n\nContext:\n"
        for i, cb in enumerate(context_blocks):
            prompt += f"Excerpt {i+1}: {cb}\n\n"
        prompt += f"Question: {query}\nAnswer concisely and cite which excerpt you used (e.g., Excerpt 1)."

        with st.spinner("Generating answer (may be slow on CPU)..."):
            answer = local_models.generate_answer(prompt)

        st.subheader("Answer")
        st.write(answer)

        st.subheader("Excerpts used")
        for i, cb in enumerate(context_blocks):
            st.write(f"Excerpt {i+1}:")
            st.write(cb)
