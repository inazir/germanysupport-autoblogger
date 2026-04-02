import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

WP_URL = os.getenv("WP_URL", "").strip().rstrip("/")
WP_USER = os.getenv("WP_USER", "").strip()
WP_APP_PASS = os.getenv("WP_APP_PASS", "").strip()

DEALS_CATEGORY_SLUG = os.getenv("DEALS_CATEGORY_SLUG", "best-deals").strip()
DEALS_DEFAULT_STATUS = os.getenv("DEALS_DEFAULT_STATUS", "draft").strip().lower()
DEALS_LANGUAGE_MODE = os.getenv("DEALS_LANGUAGE_MODE", "both").strip().lower()
DEALS_INTERNAL_LINK_SOURCE = os.getenv("DEALS_INTERNAL_LINK_SOURCE", "csv_internal_url").strip().lower()
DEALS_SOURCE = os.getenv("DEALS_SOURCE", "csv").strip().lower()
DEALS_CSV_PATH = os.getenv("DEALS_CSV_PATH", str(BASE_DIR / "feeds" / "sample_deals.csv")).strip()
DEALS_MAX_PER_RUN = int(os.getenv("DEALS_MAX_PER_RUN", "20"))
DEALS_MIN_SCORE = int(os.getenv("DEALS_MIN_SCORE", "10"))

DB_PATH = BASE_DIR / "data" / "deals.sqlite"

VALID_LANGUAGE_MODES = {"en", "de", "both"}
if DEALS_LANGUAGE_MODE not in VALID_LANGUAGE_MODES:
    raise ValueError(f"Invalid DEALS_LANGUAGE_MODE: {DEALS_LANGUAGE_MODE}. Use en, de, or both.")

VALID_STATUSES = {"draft", "publish", "pending", "private"}
if DEALS_DEFAULT_STATUS not in VALID_STATUSES:
    raise ValueError(f"Invalid DEALS_DEFAULT_STATUS: {DEALS_DEFAULT_STATUS}")

VALID_LINK_SOURCES = {"csv_internal_url"}
if DEALS_INTERNAL_LINK_SOURCE not in VALID_LINK_SOURCES:
    raise ValueError(
        f"Invalid DEALS_INTERNAL_LINK_SOURCE: {DEALS_INTERNAL_LINK_SOURCE}. "
        "Current supported value: csv_internal_url"
    )
