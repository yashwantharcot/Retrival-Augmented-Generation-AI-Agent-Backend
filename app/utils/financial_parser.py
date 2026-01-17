# app/utils/financial_parser.py

import re
from typing import Optional, Dict


def parse_number(text: str) -> Optional[float]:
    """
    Converts strings like '$117.2B', '20M', etc., to float values.
    Supports optional $ sign and multipliers like K, M, B.
    """
    multipliers = {
        "b": 1_000_000_000,
        "bn": 1_000_000_000,
        "m": 1_000_000,
        "mn": 1_000_000,
        "k": 1_000,
    }

    # Match numbers with optional dollar sign and suffix
    match = re.search(r"\$?\s*([\d,.]+)\s*([kKmMbBnN]*)", text)
    if not match:
        return None

    number = match.group(1).replace(",", "")
    unit = match.group(2).lower()

    try:
        base = float(number)
        return base * multipliers.get(unit, 1)
    except ValueError:
        return None


def extract_structured_data(text: str) -> Dict[str, Optional[float]]:
    """
    Extracts revenue, net income, and EPS from unstructured text.
    Returns structured financial data as a dictionary.
    """

    structured = {}

    # === Revenue Extraction ===
    revenue_match = re.search(
        r"revenue\s+(?:was|is|of|stood at|amounted to)?\s*\$?[0-9.,]+\s*[kKmMbBnN]*",
        text,
        re.IGNORECASE,
    )
    if revenue_match:
        revenue_value = parse_number(revenue_match.group(0))
        if revenue_value is not None:
            structured["revenue"] = revenue_value

    # === Net Income Extraction ===
    income_match = re.search(
        r"net income\s+(?:was|is|of|stood at|amounted to)?\s*\$?[0-9.,]+\s*[kKmMbBnN]*",
        text,
        re.IGNORECASE,
    )
    if income_match:
        income_value = parse_number(income_match.group(0))
        if income_value is not None:
            structured["net_income"] = income_value

    # === EPS Extraction ===
    eps_match = re.search(
        r"(?:EPS|earnings per share)\s+(?:was|is|of|stood at|amounted to)?\s*\$?[0-9.]+",
        text,
        re.IGNORECASE,
    )
    if eps_match:
        try:
            eps = float(re.search(r"[0-9.]+", eps_match.group(0)).group(0))
            structured["eps"] = eps
        except (AttributeError, ValueError):
            pass

    return structured
import re
from typing import List, Dict, Any

# You can later add more entities like "Revenue", "Net Income", etc.
FINANCIAL_TERMS = [
    "Revenue", "Net Profit", "Net Loss", "EBITDA", "Earnings", "Expenses",
    "Income", "Operating Income", "Cash Flow", "Debt", "Assets", "Liabilities",
    "Quarter", "Q1", "Q2", "Q3", "Q4", "FY", "YOY", "Growth"
]

# Precompile patterns for efficiency
AMOUNT_PATTERN = re.compile(r"(\₹|\$|Rs\.?)?\s?[\d,]+(\.\d+)?\s?(crore|million|billion|lakhs|thousand)?", re.IGNORECASE)
PERCENTAGE_PATTERN = re.compile(r"[-+]?\d+(\.\d+)?\s?%", re.IGNORECASE)
QUARTER_PATTERN = re.compile(r"(Q[1-4])\s*(FY|FY\d{2,4}|\d{4})?", re.IGNORECASE)

def extract_financial_entities(text: str) -> Dict[str, Any]:
    """
    Extracts common financial figures and terms from a string.
    Useful for enriching context or metadata filtering.
    """
    entities = {
        "amounts": [],
        "percentages": [],
        "quarters": [],
        "terms_found": []
    }

    # Extract numerical/financial patterns
    entities["amounts"] = AMOUNT_PATTERN.findall(text)
    entities["percentages"] = PERCENTAGE_PATTERN.findall(text)
    entities["quarters"] = [match[0] for match in QUARTER_PATTERN.findall(text)]

    # Extract financial terms
    found_terms = []
    for term in FINANCIAL_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
            found_terms.append(term)

    entities["terms_found"] = found_terms
    return entities


# Optional: Normalize the amounts for further processing
def normalize_amount(raw_amount: str) -> float:
    """
    Converts financial strings like '₹5 crore' into a float value.
    Returns value in INR (crores) if applicable.
    """
    try:
        # Clean and split parts
        raw = raw_amount.lower().replace(",", "").strip()
        match = re.search(r"([\d\.]+)\s?(crore|million|billion|lakhs|thousand)?", raw)
        if not match:
            return 0.0
        value = float(match.group(1))
        unit = match.group(2)

        if not unit:
            return value
        if "crore" in unit:
            return value * 1e7
        if "million" in unit:
            return value * 1e6
        if "billion" in unit:
            return value * 1e9
        if "lakhs" in unit:
            return value * 1e5
        if "thousand" in unit:
            return value * 1e3
        return value
    except Exception as e:
        print("Error in normalize_amount:", e)
        return 0.0


# Optional: Pretty print extracted data
def format_extracted_data(data: Dict[str, Any]) -> str:
    lines = []
    if data["terms_found"]:
        lines.append(f"Financial Terms: {', '.join(data['terms_found'])}")
    if data["quarters"]:
        lines.append(f"Quarters Mentioned: {', '.join(data['quarters'])}")
    if data["amounts"]:
        amounts = [' '.join(t).strip() for t in data["amounts"]]
        lines.append(f"Amounts: {', '.join(amounts)}")
    if data["percentages"]:
        percents = [''.join(p).strip() + "%" for p in data["percentages"]]
        lines.append(f"Percentages: {', '.join(percents)}")
    return "\n".join(lines)
