"""
Background job: Feedback-based learning automation for RAG agent
Periodically reviews feedback in memory_collection and flags queries for improvement.
"""

import time
from pymongo import MongoClient
from datetime import datetime

MONGO_URI = "<your-mongo-uri>"  # Replace with your actual URI or use env
client = MongoClient(MONGO_URI)
db = client["dev_db"]
memory_collection = db["dd_memory_entries_rag"]

CHECK_INTERVAL = 3600  # seconds (1 hour)
NEGATIVE_THRESHOLD = 1  # Number of negative feedbacks to flag

while True:
    print(f"[Feedback Learning] Checking feedback at {datetime.utcnow()}")
    flagged = []
    # Find all chats with negative feedback
    for doc in memory_collection.find({"chats.feedback": "down"}):
        for chat in doc.get("chats", []):
            if chat.get("feedback") == "down":
                flagged.append({
                    "user_id": doc["user_id"],
                    "session_id": doc["session_id"],
                    "query_text": chat["query_text"],
                    "timestamp": chat.get("timestamp"),
                    "llm_response": chat.get("llm_response")
                })
    # Optionally, store flagged queries in a separate collection for review
    if flagged:
        flagged_col = db["flagged_feedback"]
        flagged_col.insert_many(flagged)
    # Feedback processing completed, no print statements for debug.
    time.sleep(CHECK_INTERVAL)
