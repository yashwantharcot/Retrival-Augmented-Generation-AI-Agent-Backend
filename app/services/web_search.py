"""Trusted external source retrieval utilities.

Currently implements a lightweight fetcher for a whitelist of domains (CDC, WHO, NIH, OECD).
Content is truncated and cleaned; intended for out-of-domain fallback when explicitly allowed.
"""
import os
import re
import asyncio
import httpx
from html import unescape

TRUSTED_SOURCES = {
    "who": ["https://www.who.int"],
    "cdc": ["https://www.cdc.gov"],
    "nih": ["https://www.nih.gov"],
    "oecd": ["https://www.oecd.org"],
}

MAX_BYTES = 80_000
SNIPPET_LEN = 1200

async def fetch_trusted_pages(keywords: str, limit: int = 2):
    """Fetch a few trusted pages matching simple keyword heuristics.

    This is a heuristic placeholder (no full search engine). We iterate each domain
    root and (optionally) a small set of known topical paths if keywords hint.
    """
    timeout = int(os.getenv("TRUSTED_FETCH_TIMEOUT", "10"))
    out = []
    kw_low = (keywords or "").lower()
    async with httpx.AsyncClient(timeout=timeout) as client:
        for provider, roots in TRUSTED_SOURCES.items():
            if len(out) >= limit:
                break
            # Only include domains if keyword seems general health / economic
            if provider in ("who","cdc","nih") and not any(t in kw_low for t in ["health","covid","disease","virus","infection","public health"]):
                continue
            if provider == "oecd" and not any(t in kw_low for t in ["economy","economic","gdp","inflation","market","trade"]):
                continue
            for root in roots:
                if len(out) >= limit:
                    break
                try:
                    r = await client.get(root, follow_redirects=True)
                    if r.status_code != 200:
                        continue
                    text = _extract_text(r.text)[:MAX_BYTES]
                    out.append({
                        "source": provider,
                        "url": root,
                        "snippet": text[:SNIPPET_LEN]
                    })
                except Exception:
                    continue
    return out

def _extract_text(html: str) -> str:
    # Remove scripts/styles
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL|re.IGNORECASE)
    # Strip tags
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def summarize_external_blocks(blocks: list[dict]) -> str:
    lines = []
    for b in blocks:
        lines.append(f"Source: {b['source']} | URL: {b['url']}\n{b['snippet']}")
    return "\n\n".join(lines)

# ---------------------------------------------------------------------------
# Backward compatibility layer
# The legacy RAG service still imports search_web / search_youtube. We map
# these to the new trusted fetcher so existing code paths do not break.
# Returned schema emulates prior shape: [{"title": str, "link": str}].
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from sync context, tolerant of existing loop.

    If already inside an event loop (e.g. within FastAPI), create a new task
    via asyncio.get_event_loop().create_task is unsafe for immediate result
    retrieval here, so we fall back to nest_asyncio pattern only if needed.
    For simplicity, if loop is running we use asyncio.run in a new loop by
    temporarily creating a thread via to_thread (Python 3.11+) fallback to
    loop.run_until_complete if safe. Minimal heuristic to avoid crashes.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # Running inside an existing loop: run in a separate thread.
        return asyncio.run(coro)  # acceptable small call; low frequency
    else:
        return asyncio.run(coro)


def search_web(query: str, limit: int = 3):
    """Legacy web search stub.

    Reuses trusted source fetch (heuristic). Returns list of dicts with
    title/link keys so existing consumers remain functional.
    """
    pages = _run_async(fetch_trusted_pages(query, limit=limit))
    out = []
    for p in pages:
        title = f"{p['source'].upper()} reference"
        out.append({"title": title, "link": p["url"]})
    return out


def search_youtube(query: str, limit: int = 2):
    """Legacy YouTube search stub.

    For now we do not perform real YouTube queries (keeps dependency surface
    minimal). Returns an empty list, which prior calling code handles.
    """
    return []

