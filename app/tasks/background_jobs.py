from datetime import datetime, timedelta
from app.core.embeddings import get_embedding_for_text
from app.db.mongo import get_documents_modified_since, update_document_embedding

import traceback

def update_embeddings(since_minutes: int = 60):
    print("[+] Starting embedding update...")

    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=since_minutes)
        docs_to_update = get_documents_modified_since(cutoff_time)

        for doc in docs_to_update:
            doc_id = str(doc["_id"])
            content = doc.get("content", "")

            if not content:
                continue

            # Generate embedding
            embedding = get_embedding_for_text(content)

            # Update in DB
            update_document_embedding(doc_id, embedding)

           
    except Exception as e:
        traceback.print_exc()

        # ...existing code...
