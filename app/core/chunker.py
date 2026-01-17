import re
from datetime import datetime
def extract_numbers_from_text(text):
    """
    Extracts all numbers (int, float) from text using regex.
    Returns a list of numbers as strings.
    """
    number_pattern = r"\b\d+(?:\.\d+)?\b"
    return re.findall(number_pattern, text)

def filter_documents_by_metadata(documents, number_list=None, date_range=None):
    """
    Filters documents by numbers in chunk or metadata, and by date range in metadata.
    Args:
        documents (list): List of document dicts.
        number_list (list): List of numbers (as strings) to filter by.
        date_range (tuple): (start_date, end_date) as datetime objects.
    Returns:
        list: Filtered documents.
    """
    filtered = []
    for doc in documents:
        chunk = doc.get("chunk", "")
        metadata = doc.get("metadata", {})
        # Number filtering
        if number_list:
            if not any(num in chunk or num in str(metadata) for num in number_list):
                continue
        # Date filtering
        if date_range and "date" in metadata:
            try:
                doc_date = datetime.fromisoformat(metadata["date"])
                if not (date_range[0] <= doc_date <= date_range[1]):
                    continue
            except Exception:
                pass
        filtered.append(doc)
    return filtered
import json
from app.core.embeddings import count_tokens

def split_large_value(key, value, max_tokens=7500):
    text = str(value)
    tokens = encoding.encode(text)
    chunks = []
    for i in range(0, len(tokens), max_tokens):
        sub_tokens = tokens[i:i + max_tokens]
        sub_text = encoding.decode(sub_tokens)
        chunks.append(f"{key.capitalize()} (part): {sub_text.strip()}")
    return chunks

def record_to_chunks(record, max_tokens=7500):
    chunks = []
    current_chunk = ""
    for key, value in record.items():
        if value in [None, "", [], {}]:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        else:
            value = str(value)
        line = f"{key.capitalize()}: {value}\n"
        line_tokens = count_tokens(line)
        current_tokens = count_tokens(current_chunk)
        if line_tokens > max_tokens:
            chunks.extend(split_large_value(key, value, max_tokens))
            continue
        if current_tokens + line_tokens > max_tokens:
            chunks.append(current_chunk.strip())
            current_chunk = line
        else:
            current_chunk += line
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    return chunks
