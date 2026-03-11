import pdfplumber
try:
    import pytesseract
except Exception:
    pytesseract = None
try:
    from pdf2image import convert_from_path
except Exception:
    convert_from_path = None
import tempfile
import os
from typing import List


# --- PDF to text (hybrid: selectable text + OCR fallback) ---
def extract_pdf_text(pdf_path: str) -> str:
    text_content = ""
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                page_text = page.extract_text()
            except Exception:
                page_text = None
            if page_text and page_text.strip():
                text_content += page_text + "\n"
            else:
                # OCR fallback for scanned pages
                if convert_from_path and pytesseract:
                    with tempfile.TemporaryDirectory() as temp_dir:
                        images = convert_from_path(pdf_path, first_page=i+1, last_page=i+1, output_folder=temp_dir)
                        for image in images:
                            try:
                                ocr_text = pytesseract.image_to_string(image)
                            except Exception:
                                ocr_text = ""
                            text_content += ocr_text + "\n"
                else:
                    # If OCR tools not available, skip page
                    continue
    return text_content


# --- Chunking for RAG ---
def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    """Split text into character-based chunks with overlap.

    Args:
        text: full document text
        chunk_size: approx characters per chunk
        overlap: overlap in characters between chunks

    Returns:
        list of text chunks
    """
    if not text:
        return []
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == text_len:
            break
        start = end - overlap
    return chunks


if __name__ == "__main__":
    pdf_path = "TENDERDOCUMENT.pdf"  # Change to your PDF file
    if not os.path.exists(pdf_path):
        print("Place a PDF named TENDERDOCUMENT.pdf in this folder or change the path in the script.")
    else:
        text = extract_pdf_text(pdf_path)
        chunks = chunk_text(text)
        print(f"Extracted {len(chunks)} chunks")
