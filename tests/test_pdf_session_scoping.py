import json
from fastapi.testclient import TestClient

from app.main import app


class FakePdfSessions:
    def __init__(self):
        self.docs = {}

    def find_one(self, filt, *args, **kwargs):
        key = (filt.get("user_id"), filt.get("session_id"))
        return self.docs.get(key)

    def update_one(self, filt, update, upsert=False):
        key = (filt.get("user_id"), filt.get("session_id"))
        doc = self.docs.get(key) or {"user_id": key[0], "session_id": key[1], "questions": [], "answers": []}
        if "$set" in update:
            doc.update(update["$set"])
        if "$push" in update:
            for k, v in update["$push"].items():
                if isinstance(doc.get(k), list):
                    doc[k].append(v)
                else:
                    doc[k] = [v]
        self.docs[key] = doc
        return {"ok": 1}


def test_query_blocked_when_pdf_session(monkeypatch):
    # Arrange
    from app import main as main_mod
    fake = FakePdfSessions()
    fake.update_one(
        {"user_id": "u1", "session_id": "s1"},
        {"$set": {"user_id": "u1", "session_id": "s1", "pdf_text": "Hello from PDF."}},
        upsert=True,
    )
    monkeypatch.setattr(main_mod, "pdf_sessions_collection", fake)
    # Ensure blocking is enabled
    monkeypatch.setenv("PDF_SESSION_BLOCK_QUERY", "true")

    client = TestClient(app)
    payload = {
        "chat": {"query": "What does it say?"},
        "session_id": "s1",
        "user_id": "u1",
        "access_token": "t"
    }
    # Act
    r = client.post("/query", json=payload)
    # Assert
    assert r.status_code == 409
    data = r.json()
    assert "PDF session active" in data.get("error", "")


def test_pdf_session_query_uses_pdf_text(monkeypatch):
    # Arrange
    from app import main as main_mod
    fake = FakePdfSessions()
    fake.update_one(
        {"user_id": "u2", "session_id": "s2"},
        {"$set": {"user_id": "u2", "session_id": "s2", "pdf_text": "This PDF contains number 12345."}},
        upsert=True,
    )
    monkeypatch.setattr(main_mod, "pdf_sessions_collection", fake)

    # Stub LLM to return a deterministic string
    class StubLLM:
        def chat(self, prompt: str) -> str:
            # Echo trimmed prompt tail to signal it used the PDF path; keep short
            return "PDF ANSWER"

    monkeypatch.setattr(main_mod, "llm_engine", StubLLM())

    client = TestClient(app)
    payload = {
        "chat": {"query": "What number is in the PDF?"},
        "session_id": "s2",
        "user_id": "u2",
        "access_token": "t"
    }
    # Act
    r = client.post("/pdf-session-query", json=payload)
    # Assert
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("answer") == "PDF ANSWER"
    # Should have recorded the Q&A
    doc = fake.find_one({"user_id": "u2", "session_id": "s2"})
    assert doc
    assert "What number is in the PDF?" in doc.get("questions", [])
    assert "PDF ANSWER" in doc.get("answers", [])
