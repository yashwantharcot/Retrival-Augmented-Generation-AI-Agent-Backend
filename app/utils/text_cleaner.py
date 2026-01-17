# app/utils/text_cleaner.py
# Text cleaner utility

import re
import unicodedata
from bs4 import BeautifulSoup

def clean_text(text: str, lowercase: bool = True) -> str:
    """
    Clean and normalize input text.

    Steps:
    1. Remove HTML tags
    2. Normalize unicode characters
    3. Remove non-printable characters
    4. Remove extra spaces
    5. Optionally lowercase

    Args:
        text (str): Input text to clean.
        lowercase (bool): Whether to lowercase the text (default: True).

    Returns:
        str: Cleaned text.
    """
    # Remove HTML tags
    text = BeautifulSoup(text, "html.parser").get_text()

    # Normalize unicode
    text = unicodedata.normalize("NFKC", text)

    # Remove non-printable characters
    text = ''.join(c for c in text if c.isprintable())

    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    if lowercase:
        text = text.lower()

    return text
