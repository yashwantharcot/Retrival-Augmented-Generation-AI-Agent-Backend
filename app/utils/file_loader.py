# app/utils/file_loader.py
import os

def load_text_file(path: str) -> str:
    """
    Loads plain text from a given file path.
    Returns content as a string.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        raise RuntimeError(f"Failed to read {path}: {str(e)}")
