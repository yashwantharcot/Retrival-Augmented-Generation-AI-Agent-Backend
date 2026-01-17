import io
import json
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from app.main import app


def make_pdf(pages=2):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    for i in range(pages):
        c.drawString(100, 700, f"This is a test PDF page {i+1}. Total: $123.45. Date: 2025-01-02")
        c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


import pytest


@pytest.mark.skip(reason="pdf analyze endpoints removed from this build")
def test_analyze_pdf_monkeypatch_llm(monkeypatch):
    # Monkeypatch llm_engine.chat to return predictable JSON
    from app.core import llm as llm_mod

    def fake_chat(prompt: str) -> str:
        # Return a small deterministic JSON
        return json.dumps({
            "title": "Test Page",
            "summary": "Summary.",
            "key_points": ["A", "B"],
            "entities": [{"type": "company", "name": "Acme"}],
            "amounts": [{"label": "Total", "value": 123.45, "currency": "USD"}],
            "dates": ["2025-01-02"],
            "risks": [],
            "actions": ["Review"]
        })

    monkeypatch.setattr(llm_mod.llm_engine, "chat", fake_chat)

    client = TestClient(app)
    pdf_bytes = make_pdf(3)
    files = {"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    r = client.post("/pdf/analyze?max_pages=2", files=files)
    assert r.status_code == 200
    data = r.json()
    assert data["processed_pages"] == 2
    assert len(data["per_page"]) == 2
    assert data["per_page"][0]["title"] == "Test Page"