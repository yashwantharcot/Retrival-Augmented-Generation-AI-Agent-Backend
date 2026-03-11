# app/utils/logger.py

import logging
import sys
import os

# === Configure root logger ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout
)

# === Suppress noisy third-party loggers ===
for _noisy in (
    "pdfminer", "pdfminer.pdfpage", "pdfminer.pdfinterp",
    "pdfminer.converter", "pdfminer.cmapdb", "pdfminer.psparser",
    "pymongo", "pymongo.topology", "pymongo.connection",
    "multipart", "multipart.multipart",
    "urllib3", "urllib3.connectionpool",
    "httpcore", "httpx",
    "google.auth", "google.auth.transport",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# === Named logger ===
logger = logging.getLogger("rag_agent")

# === Global hard kill switch for all logging / prints ===
if os.getenv("DISABLE_ALL_LOGS", "false").lower() == "true":
    # Disable all logging below CRITICAL
    logging.disable(logging.CRITICAL)
    # Replace handlers with NullHandler
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.addHandler(logging.NullHandler())
    # Optional separate suppression of prints
    if os.getenv("DISABLE_PRINTS", "false").lower() == "true":
        import builtins as _b
        _b.print = lambda *a, **k: None  # noqa: E731

    def log_info(msg: str):
        return None
    def log_warning(msg: str):
        return None
    def log_error(msg: str):
        return None
    def log_debug(msg: str):
        return None
else:
    # === Wrapper functions ===
    def log_info(msg: str):
        logger.info(msg)

    def log_warning(msg: str):
        logger.warning(msg)

    def log_error(msg: str):
        logger.error(msg)

    def log_debug(msg: str):
        logger.debug(msg)

