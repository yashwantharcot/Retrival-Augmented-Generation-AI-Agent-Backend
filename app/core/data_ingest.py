# app/core/data_ingest.py

from app.db.mongo import db
from app.core.embeddings import get_embedding_for_text
from app.utils.financial_parser import extract_structured_data  # ✅ New import
from datetime import datetime

collection = db["dd_chunks"]

quarter_to_month = {
    "Q1": 1,
    "Q2": 4,
    "Q3": 7,
    "Q4": 10
}

def insert_structured_document(
    text: str,
    account: str,
    year: int,
    quarter: str,
    session_id: str = None
):
    
    embedding = get_embedding_for_text(text)
    
    structured = extract_structured_data(text)
    

    doc = {
        "text": text,
        "embedding": embedding,
        "metadata": {
            "account": account,
            "entity": account,
            "year": year,
            "quarter": quarter,
            "session_id": session_id
        },
        "structured_data": {
            **structured,
            "currency": "USD",
            "date": f"{year}-{quarter_to_month[quarter]:02d}-01"
        }
    }

    
    result = collection.insert_one(doc)
    

