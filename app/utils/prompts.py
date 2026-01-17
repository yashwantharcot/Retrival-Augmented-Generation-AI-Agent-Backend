# app/utils/prompts.py
"""
System prompts and prompt templates used in RAG generation.
"""

# === System Role ===
SYSTEM_PROMPT = (
    "You are a helpful AI assistant specialized in answering business, financial, and analytical questions based "
    "on the provided documents and past context. Always answer clearly and concisely."
)

# === User Prompt Templates ===

# For basic queries
USER_PROMPT_TEMPLATE = "Answer the following user question using the given context:\n\n{question}"

# For RAG generation with document chunks
RAG_PROMPT_TEMPLATE = """
You are given the following extracted context from documents:

{context}

Based on this context, answer the user's question below. If the answer is not in the context, say "I don't know."

Question: {question}
"""

# Prompt when including past memory or conversation
MEMORY_AWARE_PROMPT_TEMPLATE = """
You are given past interactions and memory to help answer this question more contextually.

Memory:
{memory}

Context:
{context}

Now answer the following user question:
{question}
"""

# Prompt for structured financial extraction
FINANCIAL_EXTRACTION_PROMPT = """
Extract the structured financial data (revenue, net income, EPS) from the following text:

{text}

Output in JSON format: {{ "revenue": ..., "net_income": ..., "eps": ... }}
"""

