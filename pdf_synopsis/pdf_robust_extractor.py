
import fitz  # PyMuPDF
import pdfplumber
import pytesseract
from pdf2image import convert_from_path
import tempfile
import os
from typing import List
import requests

def extract_pdf_text_robust(pdf_path: str) -> str:
    text_content = ""
    api_key = os.getenv("PDFCO_API_KEY")
    print(f"[DEBUG] PDFCO_API_KEY loaded: {'YES' if api_key else 'NO'}")
    pdfco_success = False
    if api_key:
        print("[DEBUG] Using PDF.co API for OCR extraction...")
        # Step 1: Upload file to PDF.co
        with open(pdf_path, "rb") as f:
            files = {"file": f}
            headers = {"x-api-key": api_key}
            upload_response = requests.post(
                "https://api.pdf.co/v1/file/upload",
                files=files,
                headers=headers
            )
        print(f"[DEBUG] PDF.co upload response status: {upload_response.status_code}")
        file_url = None
        if upload_response.status_code == 200:
            upload_result = upload_response.json()
            file_url = upload_result.get("url")
            print(f"[DEBUG] PDF.co uploaded file URL: {file_url}")
        else:
            print(f"[DEBUG] PDF.co upload failed: {upload_response.text}")
        # Step 2: Extract text using file URL
        if file_url:
            data = {
                "url": file_url,
                "async": True,
                "pages": "",
                "lang": "eng",
                "profile": "ocr"
            }
            extract_response = requests.post(
                "https://api.pdf.co/v1/pdf/convert/to/text",
                data=data,
                headers=headers
            )
            print(f"[DEBUG] PDF.co extract response status: {extract_response.status_code}")
            if extract_response.status_code == 200:
                extract_result = extract_response.json()
                if extract_result.get("jobId"):
                    # Async job started, poll for result
                    job_id = extract_result["jobId"]
                    print(f"[DEBUG] PDF.co async job started: {job_id}")
                    import time
                    for _ in range(60):  # Poll for up to ~5 minutes
                        job_check = requests.get(
                            f"https://api.pdf.co/v1/job/check?jobid={job_id}",
                            headers=headers
                        )
                        job_result = job_check.json()
                        print(f"[DEBUG] PDF.co job status: {job_result.get('status')}" )
                        if job_result.get("status") == "success":
                            text_content = job_result.get("result", "")
                            pdfco_success = len(text_content.strip()) >= 100
                            break
                        elif job_result.get("status") == "failed":
                            print(f"[DEBUG] PDF.co async job failed: {job_result}")
                            break
                        time.sleep(5)
                else:
                    text_content = extract_result.get("body", "")
                    pdfco_success = len(text_content.strip()) >= 100
            else:
                print(f"[DEBUG] PDF.co extract failed: {extract_response.text}")
    # Fallback to local extraction if PDF.co fails or returns insufficient text
    if not pdfco_success:
        # Try PyMuPDF first
        try:
            doc = fitz.open(pdf_path)
            for page in doc:
                page_text = page.get_text()
                if page_text and page_text.strip():
                    text_content += page_text + "\n"
        except Exception:
            pass
        # If not enough text, try pdfplumber
        if len(text_content.strip()) < 100:
            try:
                with pdfplumber.open(pdf_path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text and page_text.strip():
                            text_content += page_text + "\n"
            except Exception:
                pass
        # If still not enough, OCR all pages
        if len(text_content.strip()) < 100:
            with tempfile.TemporaryDirectory() as temp_dir:
                images = convert_from_path(pdf_path, output_folder=temp_dir)
                for image in images:
                    ocr_text = pytesseract.image_to_string(image, lang="eng", config="--psm 6")
                    text_content += ocr_text + "\n"
    return text_content

# Extract price/BOQ sections using keyword search
def extract_price_sections(text: str) -> str:
    keywords = ["price", "schedule of rates", "BOQ", "financial bid", "unit price", "amount", "rate", "cost"]
    lines = text.splitlines()
    relevant = []
    for i, line in enumerate(lines):
        if any(kw.lower() in line.lower() for kw in keywords):
            # Grab a window of lines around the keyword
            start = max(0, i-5)
            end = min(len(lines), i+15)
            relevant.extend(lines[start:end])
    # Remove duplicates and join
    return '\n'.join(list(dict.fromkeys(relevant)))