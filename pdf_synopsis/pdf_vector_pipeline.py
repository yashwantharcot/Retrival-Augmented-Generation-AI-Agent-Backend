import pdfplumber
import pytesseract
from pdf2image import convert_from_path
import tempfile
import os
from typing import List
import openai
import faiss
import numpy as np

# --- PDF to text (hybrid: selectable text + OCR fallback) ---
def extract_pdf_text(pdf_path: str) -> str:
    text_content = ""
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text()
            if page_text and page_text.strip():
                text_content += page_text + "\n"
            else:
                # OCR fallback for scanned pages
                with tempfile.TemporaryDirectory() as temp_dir:
                    images = convert_from_path(pdf_path, first_page=i+1, last_page=i+1, output_folder=temp_dir)
                    for image in images:
                        ocr_text = pytesseract.image_to_string(image)
                        text_content += ocr_text + "\n"
    return text_content

# --- Chunking for RAG ---
def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
"""Removed: legacy pdf_synopsis vector pipeline code."""
    def embed_chunks(self, chunks: List[str]):
        openai.api_key = self.openai_api_key
        self.chunks = chunks
        # Get embeddings from OpenAI
        response = openai.Embedding.create(
            input=chunks,
            model="text-embedding-ada-002"
        )
        vectors = [e['embedding'] for e in response['data']]
        self.embeddings = np.array(vectors).astype('float32')
        # Build FAISS index
        self.index = faiss.IndexFlatL2(self.embeddings.shape[1])
        self.index.add(self.embeddings)

    def query(self, query_text: str, top_k: int = 5) -> List[str]:
"""Removed: legacy pdf_synopsis vector pipeline code."""

# --- Example usage ---
if __name__ == "__main__":
    pdf_path = "TENDERDOCUMENT.pdf"  # Change to your PDF file
    openai_api_key = os.getenv("OPENAI_API_KEY")
    text = extract_pdf_text(pdf_path)
    chunks = chunk_text(text)
    store = PDFVectorStore(openai_api_key)
    store.embed_chunks(chunks)
    results = store.query("What are the payment terms?")
    for r in results:
