import streamlit as st
import os
import requests
import json

# --- Page Configuration ---
st.set_page_config(
    page_title="PDF AI Agent | RAG Explorer",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom Styling ---
st.markdown("""
<style>
    /* Main container styling */
    .main {
        background-color: #0e1117;
        color: #ffffff;
    }
    
    /* Custom button styling */
    .stButton>button {
        border-radius: 8px;
        background: linear-gradient(90deg, #4b6cb7 0%, #182848 100%);
        color: white;
        border: none;
        padding: 0.6rem 1.2rem;
        transition: all 0.3s ease;
        font-weight: 600;
        width: 100%;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(75, 108, 183, 0.4);
        border: none;
        color: white;
    }
    
    /* Header styling */
    h1 {
        font-family: 'Inter', sans-serif;
        background: -webkit-linear-gradient(#4b6cb7, #182848);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800 !important;
        margin-bottom: 2rem !important;
    }
    
    h2, h3 {
        font-family: 'Inter', sans-serif;
        font-weight: 600 !important;
    }

    /* Sidebar improvements */
    [data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }
    
    /* Chat message card styling */
    .chat-card {
        background-color: #21262d;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border: 1px solid #30363d;
    }
    
    /* Sources section styling */
    .source-box {
        background-color: #0d1117;
        border-radius: 6px;
        padding: 0.8rem;
        margin-top: 0.5rem;
        border-left: 3px solid #58a6ff;
        font-size: 0.9rem;
        color: #8b949e;
    }

    /* Glassmorphism effect for sidebar components */
    .sidebar-section {
        background: rgba(255, 255, 255, 0.03);
        padding: 1rem;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        margin-bottom: 1rem;
    }

    /* Small code style for session ID */
    .session-id-text {
        font-family: monospace;
        background: #0d1117;
        padding: 2px 6px;
        border-radius: 4px;
        color: #58a6ff;
    }
</style>
""", unsafe_allow_html=True)

# --- State Management ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    # Check query params for existing session
    params = st.query_params
    st.session_state.session_id = params.get("sid")
if "recent_sessions" not in st.session_state:
    st.session_state.recent_sessions = []
if "processed_chunks" not in st.session_state:
    st.session_state.processed_chunks = 0

# --- Helper Functions ---
BACKEND_URL = os.environ.get('BACKEND_URL', 'http://localhost:8000')

def add_recent_session(sid, name="New PDF"):
    if sid not in [s['id'] for s in st.session_state.recent_sessions]:
        st.session_state.recent_sessions.insert(0, {"id": sid, "name": name})
        # Keep only last 10
        st.session_state.recent_sessions = st.session_state.recent_sessions[:10]

def update_url_session(sid):
    st.query_params["sid"] = sid

def process_pdf(uploaded_file):
    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
    try:
        with st.spinner("🧠 Processing PDF and generating embeddings..."):
            resp = requests.post(f"{BACKEND_URL}/api/pdf-qa/upload_pdf", files=files)
            if resp.status_code == 200:
                data = resp.json()
                sid = data.get('session_id')
                st.session_state.session_id = sid
                st.session_state.processed_chunks = data.get('chunks', 0)
                add_recent_session(sid, uploaded_file.name)
                update_url_session(sid)
                return True, data
            else:
                return False, f"Backend error: {resp.status_code} — {resp.text}"
    except Exception as e:
        return False, f"Upload failed: {e}"

def ask_question(query, session_id, top_k):
    payload = {
        "session_id": session_id,
        "query": query,
        "top_k": top_k
    }
    try:
        resp = requests.post(f"{BACKEND_URL}/api/pdf-qa/query", json=payload)
        if resp.status_code == 200:
            return True, resp.json()
        else:
            return False, f"Backend error: {resp.status_code} — {resp.text}"
    except Exception as e:
        return False, f"Query failed: {e}"

# --- Sidebar ---
with st.sidebar:
    st.title("⚙️ System")
    
    with st.container():
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.subheader("Configuration")
        api_url = st.text_input("Backend URL", value=BACKEND_URL)
        top_k = st.slider("Context Window (Chunks)", 1, 10, 5)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
    st.subheader("Current Session")
    if st.session_state.session_id:
        st.success(f"Connected to: `{st.session_state.session_id[:8]}...`")
        st.markdown(f"**Session ID (click to copy):**")
        st.code(st.session_state.session_id, language=None)
        
        if st.button("🗑️ Clear History"):
            st.session_state.messages = []
            st.rerun()
    else:
        st.warning("No active session.")
    st.markdown('</div>', unsafe_allow_html=True)

    # Recent Sessions
    if st.session_state.recent_sessions:
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.subheader("Recent Sessions")
        for s in st.session_state.recent_sessions:
            if st.button(f"🔗 {s['name'][:20]}...", key=f"session_{s['id']}"):
                st.session_state.session_id = s['id']
                update_url_session(s['id'])
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.sidebar.markdown("---")
    st.sidebar.caption("🚀 Powered by FastAPI & Streamlit")

# --- Main UI ---
st.title("🤖 PDF AI Agent (RAG)")
st.markdown("##### Upload your documents and interact with them using context-aware AI.")

# Tab 1: Knowledge Ingestion
tab_upload, tab_chat = st.tabs(["📁 Knowledge Base", "💬 AI Chat"])

with tab_upload:
    st.subheader("Knowledge Ingestion")
    col1, col2 = st.columns([2, 1])
    
    with col1:
        uploaded_file = st.file_uploader("Upload PDF Document", type=["pdf"])
        if uploaded_file:
            if st.button("🚀 Ingest Document"):
                success, result = process_pdf(uploaded_file)
                if success:
                    st.success(f"✅ Document processed! Session ID: `{st.session_state.session_id}`")
                    st.info("💡 Switch to the **AI Chat** tab to start asking questions.")
                else:
                    st.error(result)
    
    with col2:
        st.info("""
        **How it works:**
        1. PDF is uploaded and context is extracted.
        2. Embeddings are generated and indexed.
        3. The Session ID is stored in the URL for persistence.
        """)

# Tab 2: Chat Interface
with tab_chat:
    if not st.session_state.session_id:
        st.warning("⚠️ Please upload a document in the 'Knowledge Base' tab before chatting.")
        # Manual ID Override
        st.markdown("---")
        manual_id = st.text_input("Or enter a Session ID manually:")
        if manual_id:
            if st.button("Connect"):
                st.session_state.session_id = manual_id
                update_url_session(manual_id)
                st.rerun()
    else:
        # Display chat history
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if "sources" in message and message["sources"]:
                    with st.expander("📚 View Sources"):
                        for source in message["sources"]:
                            st.markdown(f'<div class="source-box">{source}</div>', unsafe_allow_html=True)

        # Chat Input
        if prompt := st.chat_input("Ask a question about your document..."):
            # Add user message to history
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # Generate AI response
            with st.chat_message("assistant"):
                with st.spinner("🤖 Searching knowledge base..."):
                    success, data = ask_question(prompt, st.session_state.session_id, top_k)
                    if success:
                        answer = data.get('answer', "I couldn't find an answer.")
                        sources = data.get('sources', [])
                        
                        st.markdown(answer)
                        if sources:
                            with st.expander("📚 View Sources"):
                                for source in sources:
                                    st.markdown(f'<div class="source-box">{source}</div>', unsafe_allow_html=True)
                        
                        # Add assistant response to history
                        st.session_state.messages.append({
                            "role": "assistant", 
                            "content": answer,
                            "sources": sources
                        })
                    else:
                        st.error(data)
