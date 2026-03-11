import streamlit as st
import tempfile
import os
import requests
import json

st.set_page_config(page_title="PDF Q&A — Hosted Backend", layout="wide")

st.title("PDF Q&A — Hosted Backend")
st.markdown("Upload a PDF and have the backend (FastAPI) process it. Configure `BACKEND_URL` via environment variable if needed.")

# Backend URL (default to localhost for local dev)
BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:8000')

uploaded_file = st.file_uploader("Upload a PDF", type=["pdf"])
if uploaded_file is not None:
    if st.button("Process PDF"):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
        try:
            resp = requests.post(f"{BACKEND_URL}/upload_pdf", files=files)
        except Exception as e:
            st.error(f"Upload failed: {e}")
            raise

        if resp.status_code != 200:
            st.error(f"Backend error: {resp.status_code} — {resp.text}")
        else:
            data = resp.json()
            sid = data.get('session_id')
            chunks = data.get('chunks')
            st.success(f"PDF processed. Session id: {sid}")
            st.write(f"Chunks: {chunks}")

st.sidebar.header("Session")
selected = st.sidebar.text_input("Session id (paste from upload result)")
if selected:
    st.sidebar.write("Using session: ", selected)

st.sidebar.markdown("---")
st.sidebar.markdown("Tip: after uploading, choose the session here to ask questions.")

st.header("Ask a question")
query = st.text_input("Question")
top_k = st.slider("Top K excerpts to use", min_value=1, max_value=8, value=5)
if st.button("Get Answer"):
    if not query:
        st.warning("Enter a question first")
    elif not selected:
        st.warning("Provide a session id (from upload step)")
    else:
        payload = {
            "session_id": selected,
            "query": query,
            "top_k": top_k
        }
        try:
            resp = requests.post(f"{BACKEND_URL}/query", json=payload)
        except Exception as e:
            st.error(f"Query failed: {e}")
            raise

        if resp.status_code != 200:
            st.error(f"Backend error: {resp.status_code} — {resp.text}")
        else:
            data = resp.json()
            st.subheader("Answer")
            st.write(data.get('answer'))
            st.subheader("Sources")
            for s in data.get('sources', []):
                st.write(s)
