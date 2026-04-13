"""
GermanySupport.de — AutoBlogger (Production v5)
================================================
Changes in v5:
  16. Explicit topics (--topic) and manual CSV topics are title-locked by default.
      Claude may generate content, but EN title is forced to the chosen topic.
  17. Locked EN titles are translated into DE for DE publish, and DE title is also locked.
  18. Article prompts now explicitly require coverage of all named providers/brands
      appearing in the topic title.
  19. Newly added /go/ redirects can be auto-included when their slug/name appears
      directly in the topic, even if LINK_RELEVANCE was not updated yet.
  20. Plain-text auto-linking remains enabled as a conservative fallback after generation.

Earlier changes (v4):
  12. Rewritten manual topics are written back to manual_topics.csv immediately,
      so the CSV always reflects the actual published topic.
  13. Duplicate detection thresholds tightened conservatively.
  14. Duplicate rewrite fallback changed to skip instead of publish anyway.
  15. .env file auto-loaded from script directory if present.

Usage:
  python publish_article.py
  python publish_article.py --topic "Custom topic here"
  python publish_article.py --skip-translate   # publish EN only
"""

import os
import re
import sys
import json
import csv
import html as html_lib
import time
import random
import base64
import logging
import argparse
import hashlib
import socket
import smtplib
import traceback
from typing import Optional, List, Tuple
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path
from email.message import EmailMessage

import anthropic
import requests

# ============================================================
#  🌱  .env AUTO-LOAD  (v4 — optional quality-of-life)
#
#  If a .env file exists next to this script, load it so the
#  script can be run directly without pre-exporting vars in
#  run_publish.sh.  This is a no-op when:
#    - python-dotenv is not installed  (install: pip install python-dotenv)
#    - no .env file exists beside the script
#  The existing run_publish.sh workflow is fully unaffected because
#  override=False means shell-exported variables always win.
# ============================================================
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=False)
        print(f"[dotenv] Loaded environment from {_env_path}")
except ImportError:
    pass

from config import (
    CURRENT_YEAR,
    ALLOWED_CATEGORIES,
    get_relevant_links,
    fetch_referral_links,
    format_links_for_prompt,
    format_links_as_html,
    build_referral_replacement_map,
    TAPTAP_PROMO_TEXT,
    TAPTAP_PROMO_HTML,
)

# ============================================================
#  📝  LOGGING
# ============================================================
SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs"
CACHE_DIR = SCRIPT_DIR / "cache"
LOG_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

MANUAL_TOPICS_FILE = SCRIPT_DIR / "manual_topics.csv"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "publish.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ============================================================
#  🔑  CREDENTIALS
# ============================================================
WP_URL = os.environ["WP_URL"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_APP_PASS = os.environ["WP_APP_PASS"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]
PEXELS_KEY = os.environ["PEXELS_KEY"]

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.hostinger.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
ALERT_TO = os.getenv("ALERT_TO")

# ============================================================
#  ⚙️  SETTINGS
# ============================================================
CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 6000
RETRY_MAX = 5
RETRY_BASE_SECS = 10

# ============================================================
#  📧  EMAIL ALERTS
# ============================================================

def send_email(subject: str, body: str, to_email: Optional[str] = None) -> bool:
    recipient = to_email or ALERT_TO

    if not SMTP_USER or not SMTP_PASS or not recipient:
        log.warning("Email skipped: SMTP_USER, SMTP_PASS, or ALERT_TO missing.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient
    msg["Reply-To"] = SMTP_USER
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        log.info(f"Email sent successfully to {recipient}")
        return True
    except Exception as e:
        log.error(f"Failed to send email: {e}")
        return False

# ============================================================
#  🔒  DIRECT AFFILIATE URL → /go/ REPLACEMENT MAP
# ============================================================
LIVE_DIRECT_TO_GO_MAP = {}

def enforce_go_links(html: str, wp_base: str) -> tuple:
    replacements = []
    replacement_map = LIVE_DIRECT_TO_GO_MAP or {}

    malformed_go_re = re.compile(
        re.escape(wp_base.rstrip("/")) + r'/go/([a-z0-9-]+)(?:/[^\s"\'<>()]+)+',
        flags=re.IGNORECASE,
    )

    def normalise_internal(match):
        slug = match.group(1).lower()
        old = match.group(0)
        new = f"{wp_base.rstrip('/')}/go/{slug}"
        if old != new:
            replacements.append((old, new))
        return new

    html = malformed_go_re.sub(normalise_internal, html)

    def canonicalise_candidate(url: str) -> str:
        url = html_lib.unescape((url or "").strip())
        return url.rstrip('.,;:)')

    def resolve_go_url(url: str):
        url_norm = canonicalise_candidate(url)

        if "/go/" in url_norm and url_norm.startswith(wp_base):
            m = re.search(r'/go/([a-z0-9-]+)', url_norm, flags=re.IGNORECASE)
            if m:
                return f"{wp_base.rstrip('/')}/go/{m.group(1).lower()}"
            return None

        return replacement_map.get(url_norm)

    def replace_href(match):
        full_tag = match.group(0)
        href_val = match.group(1)

        if href_val.startswith(wp_base) and "/go/" not in href_val:
            return full_tag

        new_url = resolve_go_url(href_val)
        if new_url and new_url != href_val:
            replacements.append((href_val, new_url))
            return full_tag.replace(href_val, new_url)
        return full_tag

    html = re.sub(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>',
        replace_href,
        html,
        flags=re.IGNORECASE,
    )

    url_re = re.compile(r'(?<!["\'=])(https?://[^\s<>()]+)', flags=re.IGNORECASE)

    def replace_bare_url(match):
        url = match.group(1)
        new_url = resolve_go_url(url)
        if new_url and new_url != url:
            replacements.append((url, new_url))
            return new_url
        return url

    html = url_re.sub(replace_bare_url, html)
    return html, replacements

# ============================================================
#  🔗  PLAIN-TEXT AUTO-LINKER FOR LIVE /go/ LINKS
# ============================================================

def normalize_slug_for_autolink(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", (value or "").strip().lower()).strip("-")


def extract_go_slug(url: str, wp_base: str) -> Optional[str]:
    if not url:
        return None
    url = html_lib.unescape(url).strip()
    m = re.search(r'/go/([a-z0-9-]+)', url, flags=re.IGNORECASE)
    if m:
        return m.group(1).lower()
    if url.startswith("go/"):
        return url[3:].strip("/").lower()
    if url.startswith("/go/"):
        return url[4:].strip("/").lower()
    return None


def slug_to_aliases(slug: str) -> List[str]:
    slug = normalize_slug_for_autolink(slug)
    aliases = {
        slug,
        slug.replace("-", " "),
    }
    return [a for a in aliases if a and len(a) >= 4]


def build_autolink_candidates(rel_links: dict, wp_base: str) -> List[Tuple[str, str]]:
    candidates: List[Tuple[str, str]] = []
    seen = set()

    def add_candidate(text: str, go_url: str):
        text = (text or "").strip()
        go_url = (go_url or "").strip()
        if not text or not go_url or "/go/" not in go_url:
            return
        key = (text.lower(), go_url.lower())
        if key in seen:
            return
        seen.add(key)
        candidates.append((text, go_url))

    for name, url in (rel_links or {}).items():
        slug = extract_go_slug(url, wp_base)
        if not slug:
            continue
        go_url = f"{wp_base.rstrip('/')}/go/{slug}"
        add_candidate(name, go_url)
        for alias in slug_to_aliases(slug):
            add_candidate(alias, go_url)

    try:
        live_links = fetch_referral_links(wp_base, force=False) or {}
        for key, url in live_links.items():
            slug = extract_go_slug(key, wp_base) or extract_go_slug(url, wp_base)
            if not slug:
                continue
            go_url = f"{wp_base.rstrip('/')}/go/{slug}"
            for alias in slug_to_aliases(slug):
                add_candidate(alias, go_url)
    except Exception as e:
        log.warning(f"  Autolink candidate build skipped: {e}")

    candidates.sort(key=lambda x: len(x[0]), reverse=True)
    return candidates


def autolink_plain_text_mentions(
    html: str,
    rel_links: dict,
    wp_base: str,
    max_total_links: int = 8,
) -> Tuple[str, int]:
    if not html:
        return html, 0

    candidates = build_autolink_candidates(rel_links, wp_base)
    if not candidates:
        return html, 0

    total_added = 0
    updated = html

    linked_slugs = set(
        m.group(1).lower()
        for m in re.finditer(r'href=["\'][^"\']*/go/([a-z0-9-]+)["\']', updated, flags=re.IGNORECASE)
    )

    def replace_outside_anchors(source_html: str, visible_text: str, go_url: str) -> Tuple[str, int]:
        pattern = re.compile(
            rf'(?<![\w/-])({re.escape(visible_text)})(?![\w/-])',
            flags=re.IGNORECASE
        )

        parts = re.split(r'(<a\b[^>]*>.*?</a>)', source_html, flags=re.IGNORECASE | re.DOTALL)
        replacements = 0
        out = []

        tag_splitter = re.compile(r'(<[^>]+>)')

        for part in parts:
            if not part:
                out.append(part)
                continue

            if re.match(r'^<a\b[^>]*>.*?</a>$', part, flags=re.IGNORECASE | re.DOTALL):
                out.append(part)
                continue

            subparts = tag_splitter.split(part)
            new_subparts = []

            for sub in subparts:
                if not sub:
                    new_subparts.append(sub)
                    continue

                if sub.startswith("<") and sub.endswith(">"):
                    new_subparts.append(sub)
                    continue

                if replacements == 0:
                    sub, local_count = pattern.subn(
                        rf'<a href="{go_url}" target="_blank" rel="nofollow sponsored">\1</a>',
                        sub,
                        count=1,
                    )
                    replacements += local_count

                new_subparts.append(sub)

            out.append("".join(new_subparts))

        return "".join(out), replacements

    for visible_text, go_url in candidates:
        slug = extract_go_slug(go_url, wp_base)
        if not slug or slug in linked_slugs:
            continue
        if total_added >= max_total_links:
            break

        updated, added = replace_outside_anchors(updated, visible_text, go_url)
        if added:
            total_added += added
            linked_slugs.add(slug)
            log.info(f"  Auto-linked plain mention: '{visible_text}' -> {go_url}")

    return updated, total_added

# ============================================================
#  💎  HIGH-CONVERSION MONEY PAGES
# ============================================================
HIGH_CONVERSION_TOPICS = [
    f"Best Free Bank Accounts in Germany for Expats {CURRENT_YEAR}: N26 vs C24",
    "N26 vs C24 Bank: Which Is Better for Expats in Germany?",
    f"Best Banks for Expats in Germany: Complete Guide {CURRENT_YEAR}",
    "How to Open N26 Account in Germany: Step-by-Step Guide",
    f"Best Credit Cards in Germany for Foreigners {CURRENT_YEAR}",
    "Advanzia Mastercard Germany: Zero-Fee Credit Card Review",
    "Best No-Fee Credit Cards in Germany: Complete Comparison",
    "Best Liability Insurance (Haftpflicht) in Germany: Top Providers Compared",
    f"Cheapest Car Insurance in Germany {CURRENT_YEAR}: Save Up to €850",
    "Best Legal Insurance (Rechtsschutz) in Germany for Expats",
    f"Best DSL Internet Providers in Germany {CURRENT_YEAR}: Prices & Speed",
    f"Best SIM Cards and Mobile Plans in Germany for Expats {CURRENT_YEAR}",
    "Telekom vs Vodafone vs O2: Which Mobile Network in Germany?",
    f"Cheapest Electricity Providers in Germany {CURRENT_YEAR}: Switch and Save",
    "Verivox vs Check24: Which Comparison Portal Is Better in Germany?",
    f"Best Money Transfer Services from Germany {CURRENT_YEAR}: ACE vs TapTap",
    f"TapTap Send Review {CURRENT_YEAR}: Send Money Home from Germany Cheaply",
    "Trade Republic vs Scalable Capital: Best Broker for Expats in Germany",
    f"Best ETF Brokers in Germany for Beginners {CURRENT_YEAR}",
    f"Best Cashback Apps and Websites in Germany {CURRENT_YEAR}",
    "Shoop vs iGraal: Best Cashback Portal in Germany",
    f"SteuerGo vs WISO: Best Tax Software for Expats in Germany {CURRENT_YEAR}",
]

SEED_TOPICS = [
    "How to open a bank account in Germany as a foreigner",
    "How to invest in ETFs and stocks in Germany as an expat",
    "How to build a credit score (Schufa) in Germany from scratch",
    "Sending money home from Germany: cheapest international transfer services",
    "How to get liability insurance (Haftpflichtversicherung) in Germany",
    "Car insurance in Germany for foreigners: a complete guide",
    "Public vs private health insurance in Germany: which is better for expats?",
    "How to file taxes in Germany as an expat (Steuererklärung guide)",
    "Tax classes in Germany: which Steuerklasse should you choose?",
    "Freelancer taxes in Germany: complete guide for self-employed expats",
    "Best prepaid SIM cards in Germany for expats",
    "How to compare and switch internet providers in Germany",
    "How to switch gas providers in Germany and save money",
    "How to register your address in Germany (Anmeldung): step-by-step",
    "How to find an apartment in Germany as a foreigner",
    "Understanding a German rental contract (Mietvertrag) for expats",
    "How to get a work visa in Germany: complete guide for non-EU citizens",
    "How to apply for permanent residency (Niederlassungserlaubnis) in Germany",
    "German driving licence for foreigners: how to convert",
    "How to claim unemployment benefits (Arbeitslosengeld) in Germany",
    "How to bring your family to Germany: family reunification visa guide",
]

# ============================================================
#  🔄  EXPONENTIAL BACKOFF WRAPPER
# ============================================================

def claude_with_retry(fn, *args, **kwargs):
    last_error = None
    for attempt in range(1, RETRY_MAX + 1):
        try:
            return fn(*args, **kwargs)
        except anthropic.RateLimitError as e:
            last_error = e
            wait = RETRY_BASE_SECS * (2 ** (attempt - 1)) + random.uniform(0, 5)
            log.warning(f"Claude rate limit (attempt {attempt}/{RETRY_MAX}). Waiting {wait:.0f}s...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code == 529:
                last_error = e
                wait = RETRY_BASE_SECS * (2 ** (attempt - 1)) + random.uniform(0, 5)
                log.warning(f"Claude overloaded (attempt {attempt}/{RETRY_MAX}). Waiting {wait:.0f}s...")
                time.sleep(wait)
            else:
                raise
        except Exception:
            raise
    log.error(f"Claude API failed after {RETRY_MAX} attempts.")
    raise last_error

# ============================================================
#  💾  DISK CACHE
# ============================================================

def cache_key(topic: str) -> str:
    return hashlib.md5(topic.encode()).hexdigest()[:12]

def load_cached_article(topic: str) -> dict:
    path = CACHE_DIR / f"{cache_key(topic)}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            log.info(f"  Using cached article: {path.name}")
            return data
        except Exception:
            pass
    return None

def save_cached_article(topic: str, article: dict):
    path = CACHE_DIR / f"{cache_key(topic)}.json"
    path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"  Article cached: {path.name}")

def clear_cached_article(topic: str):
    path = CACHE_DIR / f"{cache_key(topic)}.json"
    if path.exists():
        path.unlink()

# ============================================================
#  🔧  AUTH & HTTP
# ============================================================

def build_headers():
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PASS}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

HEADERS = build_headers()

def wp_request(method, endpoint, **kwargs):
    url = f"{WP_URL}/wp-json/wp/v2/{endpoint}"
    r = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)
    if not r.ok:
        raise Exception(f"WP {r.status_code}: {r.text[:300]}")
    return r.json()

def wp_get_raw(endpoint, params=None):
    r = requests.get(f"{WP_URL}/wp-json/wp/v2/{endpoint}", headers=HEADERS, params=params or {}, timeout=30)
    r.raise_for_status()
    return r

# ============================================================
#  🔍  DUPLICATE DETECTION
# ============================================================

def fetch_all_post_data():
    posts, page = [], 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={"per_page": 100, "page": page, "status": "publish", "_fields": "id,title,slug,link"},
            timeout=30,
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
    return posts


def find_duplicate(topic, all_posts, sim_threshold=0.50, kw_threshold=0.55):
    candidate_slug = re.sub(r'[^a-z0-9]+', '-', topic.lower())[:80].strip('-')
    for post in all_posts:
        existing_title = post["title"]["rendered"]
        existing_slug = post.get("slug", "")

        if candidate_slug and existing_slug and SequenceMatcher(None, candidate_slug, existing_slug).ratio() > 0.80:
            return True, post

        if SequenceMatcher(None, topic.lower(), existing_title.lower()).ratio() >= sim_threshold:
            return True, post

        words_a = set(re.findall(r'\b\w{4,}\b', topic.lower()))
        words_b = set(re.findall(r'\b\w{4,}\b', existing_title.lower()))
        if words_a and len(words_a & words_b) / len(words_a) >= kw_threshold:
            return True, post

    return False, None

# ============================================================
#  🌍  LANGUAGE DETECTION & TOPIC NORMALISATION
# ============================================================

_DE_SIGNAL_WORDS = {
    "für", "fuer", "und", "oder", "mit", "von", "bei", "das", "die", "der",
    "ein", "eine", "einen", "konto", "karten", "karte", "girokonto", "banken",
    "bestes", "beste", "bester", "günstig", "günstigste", "deutschland",
    "ausländer", "studenten", "anfänger", "vergleich", "kosten", "schritt",
    "anleitung", "leitfaden", "überblick", "versicherung", "steuer",
}

def _is_likely_non_english(text: str) -> bool:
    words = set(re.findall(r'\b\w+\b', text.lower()))
    return bool(words & _DE_SIGNAL_WORDS)


def translate_topic_to_english(topic: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    def _call():
        return client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": (
                    f"Translate the following article topic to English. "
                    f"Return ONLY the translated topic string, nothing else:\n\n{topic}"
                ),
            }],
        )

    try:
        log.info(f"  Translating non-English topic for duplicate check: {topic}")
        r = claude_with_retry(_call)
        translated = r.content[0].text.strip().strip('"').strip("'")
        log.info(f"  Translated topic (EN, for dedup only): {translated}")
        return translated
    except Exception as e:
        log.warning(f"  Topic translation failed ({e}); using original for dedup.")
        return topic

# ============================================================
#  🔒  TITLE LOCK HELPERS
# ============================================================

def translate_locked_title_to_german(title_en: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = (
        "Translate the following article title into natural German.\n"
        "Rules:\n"
        "- Keep all brand/provider/product names exactly as they are.\n"
        "- Keep all compared entities present.\n"
        "- Do not shorten.\n"
        "- Return ONLY the translated title.\n\n"
        f"{title_en}"
    )

    def _call():
        return client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )

    try:
        r = claude_with_retry(_call)
        return r.content[0].text.strip().strip('"').strip("'")
    except Exception as e:
        log.warning(f"  Locked DE title translation failed ({e}); falling back to EN title.")
        return title_en

# ============================================================
#  ✨  SEO DUPLICATE REWRITE
# ============================================================

SEO_INTENT_MODIFIERS = [
    f"Complete Guide {CURRENT_YEAR}",
    f"Step-by-Step Guide for Expats {CURRENT_YEAR}",
    "Requirements and Costs Explained",
    "Costs, Fees and Hidden Charges",
    f"Best Options for Expats {CURRENT_YEAR}",
    "for Students and Foreigners",
    "for Beginners in Germany",
    "Comparison: Which Is Best?",
    "Pros, Cons and Alternatives",
    f"Top Picks {CURRENT_YEAR}: Tested and Compared",
    "What You Need to Know Before You Start",
    "Common Mistakes to Avoid",
    "Tips to Save Money in Germany",
    f"Updated {CURRENT_YEAR}: Everything You Need",
]

def _strip_year(text: str) -> str:
    return re.sub(r'\b20\d{2}\b', '', text).strip(' :–-')


def rewrite_duplicate_topic_simple(original_topic: str) -> list[str]:
    base = _strip_year(original_topic)
    base = re.sub(
        r'\s*[:\-–]\s*(guide|comparison|review|requirements|costs?|tips?|explained).*$',
        '',
        base,
        flags=re.IGNORECASE
    ).strip()
    return [f"{base}: {modifier}" for modifier in SEO_INTENT_MODIFIERS]


def rewrite_duplicate_topic_ai(original_topic: str, existing_titles: list[str], count: int = 8) -> list[str]:
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    existing_str = "\n".join(f"- {t}" for t in existing_titles[:60])

    prompt = (
        f"You are an SEO strategist for germanysupport.de, a German expat guide.\n"
        f"The following topic is already published and must NOT be duplicated:\n"
        f"  \"{original_topic}\"\n\n"
        f"These topics already exist on the site (do NOT create anything similar):\n"
        f"{existing_str}\n\n"
        f"Generate {count} NEW long-tail SEO topic variants that:\n"
        f"- Keep the same core search intent as the original topic\n"
        f"- Are useful for expats, foreigners, or students in Germany\n"
        f"- Use proven SEO patterns such as:\n"
        f"    'how to … in Germany for expats'\n"
        f"    'best … in Germany {CURRENT_YEAR}'\n"
        f"    '… requirements in Germany'\n"
        f"    '… costs in Germany'\n"
        f"    '… comparison Germany'\n"
        f"    '… for students / foreigners / beginners'\n"
        f"- Are specific enough to rank without cannibalizing existing content\n"
        f"- Include the year {CURRENT_YEAR} where it adds SEO value\n\n"
        f"Output ONLY a JSON array of {count} topic strings. No markdown, no explanation."
    )

    def _call():
        return client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )

    log.info("  Calling Claude API for AI duplicate rewrites...")
    r = claude_with_retry(_call)
    raw = r.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("  AI rewrite response was not valid JSON; falling back to empty list.")
        return []


def resolve_manual_topic_with_dedup(
    original_topic: str,
    all_posts: list,
    max_ai_attempts: int = 2,
) -> tuple[str, bool]:
    topic_for_dedup = (
        translate_topic_to_english(original_topic)
        if _is_likely_non_english(original_topic)
        else original_topic
    )

    is_dup, match = find_duplicate(topic_for_dedup, all_posts)

    if not is_dup:
        return original_topic, False

    matched_title = match["title"]["rendered"] if match else "unknown"
    log.warning(
        f"  [DUPLICATE] Manual topic conflicts with existing post:\n"
        f"    Original : {original_topic}\n"
        f"    Conflicts: {matched_title}\n"
        f"  → Attempting smart rewrite..."
    )

    existing_titles = [p["title"]["rendered"] for p in all_posts]
    rewrite_base = topic_for_dedup

    for candidate in rewrite_duplicate_topic_simple(rewrite_base):
        if not find_duplicate(candidate, all_posts)[0]:
            log.info(f"  [REWRITE] Rule-based rewrite chosen: {candidate}")
            return candidate, True

    for attempt in range(1, max_ai_attempts + 1):
        log.info(f"  [REWRITE] AI rewrite attempt {attempt}/{max_ai_attempts}...")
        for candidate in rewrite_duplicate_topic_ai(rewrite_base, existing_titles, count=8):
            if not find_duplicate(candidate, all_posts)[0]:
                log.info(f"  [REWRITE] AI rewrite chosen (attempt {attempt}): {candidate}")
                return candidate, True

    log.warning(
        f"  [REWRITE] All rewrite candidates still duplicate.\n"
        f"  Skipping '{original_topic}' — row will be marked 'skipped' for manual review."
    )
    return None, True

# ============================================================
#  🗂️  MANUAL TOPIC QUEUE
# ============================================================

def load_manual_topics():
    if not MANUAL_TOPICS_FILE.exists():
        return []
    try:
        with MANUAL_TOPICS_FILE.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        log.warning(f"Could not read manual topics file: {e}")
        return []

def save_manual_topics(rows):
    if not rows:
        return
    fieldnames = []
    for key in ("topic", "products", "language", "status"):
        if any(key in row for row in rows):
            fieldnames.append(key)
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with MANUAL_TOPICS_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def get_next_manual_topic():
    rows = load_manual_topics()
    for idx, row in enumerate(rows):
        status = (row.get("status") or "pending").strip().lower()
        topic = (row.get("topic") or "").strip()
        if topic and status in ("", "pending", "todo", "new"):
            return idx, row, rows
    return None, None, rows

def mark_manual_topic_done(rows, idx):
    if idx is None or idx < 0 or idx >= len(rows):
        return
    rows[idx]["status"] = "done"
    save_manual_topics(rows)

def mark_manual_topic_skipped(rows, idx):
    if idx is None or idx < 0 or idx >= len(rows):
        return
    rows[idx]["status"] = "skipped"
    save_manual_topics(rows)

def update_manual_topic_text(rows, idx, new_topic: str):
    if idx is None or idx < 0 or idx >= len(rows):
        return
    rows[idx]["topic"] = new_topic
    save_manual_topics(rows)

def parse_manual_products(row):
    raw = (row.get("products") or "").strip()
    return [p.strip() for p in raw.split("|") if p.strip()]

def normalize_publish_mode(language_value: str = "", skip_translate: bool = False) -> str:
    if skip_translate:
        return "en"
    value = (language_value or "").strip().lower()
    if value == "en":
        return "en"
    if value == "de":
        return "de"
    if value == "both":
        return "both"
    return "both"

# ============================================================
#  🎯  TOPIC SELECTION
# ============================================================

def pick_fresh_topic(all_posts, custom_topic=None):
    if custom_topic:
        is_dup, match = find_duplicate(custom_topic, all_posts)
        if is_dup:
            log.warning(f"Custom topic similar to: '{match['title']['rendered']}'")
        return custom_topic, "custom"

    log.info("Checking mixed pool of high-conversion and general seed topics...")
    mixed_pool = [(t, "high-conversion") for t in HIGH_CONVERSION_TOPICS] + [(t, "seed") for t in SEED_TOPICS]
    random.shuffle(mixed_pool)
    for topic, source in mixed_pool:
        if not find_duplicate(topic, all_posts)[0]:
            return topic, source

    log.info("Generating AI topics (SEO-intent, keyword-driven)...")
    existing = [p["title"]["rendered"] for p in all_posts[:80]]
    for attempt in range(1, 6):
        log.info(f"  AI generation attempt {attempt}/5...")
        new_topics = _generate_topics_api(existing, count=20)
        random.shuffle(new_topics)
        for topic in new_topics:
            if not find_duplicate(topic, all_posts)[0]:
                return topic, "ai-generated"

    log.error("No fresh topics found.")
    sys.exit(1)


def _generate_topics_api(existing_titles, count=20):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    existing_str = "\n".join(f"- {t}" for t in existing_titles)

    prompt = (
        f"You are an SEO strategist for germanysupport.de, a guide for expats in Germany.\n"
        f"Generate {count} NEW article topics that:\n"
        f"- Have clear search intent (informational or commercial investigation)\n"
        f"- Use long-tail keyword structures with high ranking potential\n"
        f"- Are useful for expats, foreigners, or students living in Germany\n"
        f"- Relate to practical topics: banking, insurance, taxes, housing, visas, mobile, internet, investing\n"
        f"- Favour patterns such as:\n"
        f"    'how to … in Germany for expats'\n"
        f"    'best … in Germany {CURRENT_YEAR}'\n"
        f"    '… requirements in Germany'\n"
        f"    '… costs in Germany'\n"
        f"    '… comparison Germany'\n"
        f"    '… for students / foreigners / beginners'\n"
        f"- Include {CURRENT_YEAR} in the title where it adds SEO value\n"
        f"- Are specific enough to avoid cannibalizing existing content\n\n"
        f"Do NOT generate anything similar to these already-published titles:\n"
        f"{existing_str}\n\n"
        f"Output ONLY a JSON array of {count} topic strings. No markdown, no explanation."
    )

    def _call():
        return client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )

    r = claude_with_retry(_call)
    raw = r.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$", "", raw).strip()
    return json.loads(raw)

# ============================================================
#  🔗  REFERRAL LINK RESOLUTION
# ============================================================

def _humanize_slug(slug: str) -> str:
    text = slug.replace("-", " ").strip()
    words = []
    for word in text.split():
        if word.upper() in {"DSL", "SIM", "PKV", "GKV"}:
            words.append(word.upper())
        elif word.lower() in {"n26", "c24", "o2", "eon", "eprimo"}:
            words.append(word.upper() if word.lower() in {"eon"} else word)
        else:
            words.append(word.capitalize())
    return " ".join(words) if words else slug


def resolve_referral_links(topic: str, content_hint: str = "", forced_products=None) -> dict:
    fetch_referral_links(WP_URL, force=True)
    global LIVE_DIRECT_TO_GO_MAP
    LIVE_DIRECT_TO_GO_MAP = build_referral_replacement_map(WP_URL)
    log.info(f"    Loaded {len(LIVE_DIRECT_TO_GO_MAP)} raw→/go/ replacement rules from WordPress plugin")

    rel = get_relevant_links(topic, content_hint, WP_URL)
    verified = {}

    for name, url in rel.items():
        if not url.startswith("http"):
            url = WP_URL.rstrip("/") + "/" + url.lstrip("/")
        if "/go/" not in url:
            log.warning(f"Link '{name}' does not use /go/ path: {url}")
        verified[name] = url

    live_links = fetch_referral_links(WP_URL, force=False) or {}
    topic_lc = (topic or "").lower()

    # Auto-include redirects whose slug text appears directly in the topic.
    for slug_key, url in live_links.items():
        slug = slug_key.replace("go/", "").strip().lower()
        aliases = slug_to_aliases(slug)
        matched = any(alias.lower() in topic_lc for alias in aliases)
        if matched:
            display_name = _humanize_slug(slug)
            if display_name not in verified:
                verified[display_name] = url
                log.info(f"  Topic-matched live redirect added: {display_name} -> {url}")

    if forced_products:
        display_to_slug = {
            "ace": "go/ace", "ace money transfer": "go/ace",
            "taptap": "go/taptap", "taptap send": "go/taptap",
            "paypal": "go/paypal", "n26": "go/n26",
            "c24": "go/c24", "c24 bank": "go/c24",
            "advanzia": "go/advanzia", "advanzia mastercard": "go/advanzia",
            "trade republic": "go/trade-republic",
            "scalable capital": "go/scalable-capital",
            "shoop": "go/shoop", "igraal": "go/igraal",
            "payback": "go/payback", "verivox": "go/verivox",
            "check24": "go/check24", "tarifcheck": "go/tarifcheck",
            "steuergo": "go/steuergo", "wiso": "go/wiso",
            "vodafone": "go/vodafone", "telekom": "go/telekom",
            "huk24": "go/huk24",
            "preisvergleich": "go/preisvergleich",
        }
        for product in forced_products:
            key = product.strip().lower()
            slug = display_to_slug.get(key)
            if slug and slug in live_links:
                verified[product] = live_links[slug]

    log.info(f"  Resolved {len(verified)} affiliate links ({list(verified.keys())[:5]}...)")
    return verified

# ============================================================
#  🎯  RANK MATH SEO SETTER
# ============================================================

def set_rank_math_seo(post_id: int, keyword: str, meta_title: str, meta_description: str) -> bool:
    payload = {"post_id": post_id, "keyword": keyword, "title": meta_title, "description": meta_description}
    try:
        r = requests.post(f"{WP_URL}/wp-json/gs/v1/set-keyword", headers=HEADERS, json=payload, timeout=15)
        if r.ok and r.json().get("success"):
            log.info(f"  Rank Math keyword set ✓  [{keyword}]")
            return True
    except Exception as e:
        log.warning(f"  Custom endpoint error: {e}")

    try:
        r2 = requests.post(
            f"{WP_URL}/wp-json/rankmath/v1/updateMeta",
            headers=HEADERS,
            json={"objectID": post_id, "objectType": "post", "meta": {
                "rank_math_focus_keyword": keyword,
                "rank_math_title": meta_title,
                "rank_math_description": meta_description,
            }},
            timeout=15,
        )
        if r2.ok:
            log.info(f"  Rank Math keyword set via native API ✓")
            return True
    except Exception as e:
        log.warning(f"  Native Rank Math API error: {e}")

    log.warning(f"  Rank Math keyword NOT set — do manually: '{keyword}'")
    return False

# ============================================================
#  🛠️  SEO NORMALISER
# ============================================================

def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def _make_slug(text: str, max_len: int = 60) -> str:
    text = (text or "").lower()
    text = re.sub(r"[äàáâãå]", "a", text)
    text = re.sub(r"[öòóôõ]", "o", text)
    text = re.sub(r"[üùúû]", "u", text)
    text = re.sub(r"[ß]", "ss", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text[:max_len].strip("-")

def _trim_meta_description(text: str, min_len: int = 150, max_len: int = 155) -> str:
    text = _collapse_spaces(text)
    if len(text) <= max_len and len(text) >= min_len:
        return text
    if len(text) > max_len:
        cut = text[:max_len].rstrip(" ,;:-")
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut[:max_len].rstrip(" ,;:-.")
    return text[:max_len]

def _first_nonempty(*values) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _ensure_keyword_in_intro(content: str, keyword: str) -> str:
    if not content or not keyword:
        return content
    if re.search(re.escape(keyword), content[:1200], flags=re.IGNORECASE):
        return content

    intro = f"<p><strong>{html_lib.escape(keyword)}</strong> is one of the most searched topics for expats in Germany. This guide explains the key facts, costs, options and practical steps you should know.</p>"
    h_match = re.search(r"<h[1-6][^>]*>", content, flags=re.IGNORECASE)
    if h_match:
        return content[:h_match.start()] + intro + content[h_match.start():]
    return intro + content

def _ensure_keyword_in_h2(content: str, keyword: str) -> str:
    if not content or not keyword:
        return content
    if re.search(rf"<h2[^>]*>.*?{re.escape(keyword)}.*?</h2>", content, flags=re.IGNORECASE | re.DOTALL):
        return content

    def repl(match):
        inner = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        new_inner = f"{html_lib.escape(keyword)}: {inner}" if inner else html_lib.escape(keyword)
        return f"<h2>{new_inner}</h2>"

    return re.sub(r"<h2[^>]*>(.*?)</h2>", repl, content, count=1, flags=re.IGNORECASE | re.DOTALL)

def normalize_article_seo(article: dict, topic: str, lang: str = "en", locked_title: Optional[str] = None) -> dict:
    article = dict(article or {})

    original_title = _first_nonempty(article.get("title"), topic, "Germany Guide")
    original_keyword = _first_nonempty(article.get("focus_keyword"), topic, original_title)

    if locked_title:
        title = _collapse_spaces(locked_title)
    else:
        title = original_title

    keyword = _collapse_spaces(
        re.sub(r"[|:–-]\s*(guide|review|comparison|explained|requirements|costs?)\b.*$", "", original_keyword, flags=re.IGNORECASE)
    )
    keyword = keyword[:65].strip(" -:|")
    if not keyword:
        keyword = _collapse_spaces(topic)[:65]

    if not locked_title and keyword and keyword.lower() not in title.lower():
        title = f"{keyword}: {title}"

    slug_source = _first_nonempty(article.get("slug"), title, keyword)
    slug = _make_slug(title or slug_source, max_len=60) or _make_slug(slug_source, max_len=60)

    meta = _first_nonempty(article.get("meta_description"))
    if not meta or (keyword and keyword.lower() not in meta.lower()):
        if lang == "de":
            meta = f"{title} in Deutschland: verständlicher Guide für Expats mit Kosten, Voraussetzungen, Vergleich und praktischen Tipps."
        else:
            meta = f"{title} in Germany explained for expats: comparison, costs, options, pros and cons, and practical tips before you choose."
    meta = _trim_meta_description(meta)

    content = article.get("content", "")
    content = _ensure_keyword_in_intro(content, keyword or title[:60])
    content = _ensure_keyword_in_h2(content, keyword or title[:60])

    article["title"] = title
    article["focus_keyword"] = keyword or title[:65]
    article["slug"] = slug
    article["meta_description"] = meta
    article["content"] = content
    return article

# ============================================================
#  ✍️  ARTICLE GENERATION (EN)
# ============================================================

def generate_article_en(topic: str, rel_links: dict, locked_title: Optional[str] = None) -> dict:
    cache_name = topic if not locked_title else f"LOCKED_EN::{topic}"
    cached = load_cached_article(cache_name)
    if cached:
        return cached

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    links_html = format_links_as_html(rel_links)
    cats_str = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    system = f"""You are an SEO writer for germanysupport.de (expat guide, Germany). Year: {CURRENT_YEAR}.

LANGUAGE RULE:
- Write EVERYTHING in English only.
- Even if the provided topic is in German or any other language, the output must be fully in English.
- The title, slug, meta_description, focus_keyword, tags, image_search_query, and article content must all be in English.
- Do NOT output German.

OUTPUT: Return ONLY a single-line minified JSON object. No markdown. No code blocks.
All double-quotes inside HTML values must be escaped as \\".

JSON schema (all fields required):
{{"title":"string","slug":"string max 60 chars","meta_description":"string 150-155 chars","focus_keyword":"string","tags":["string"],"categories":["string"],"image_search_query":"string 2-4 words","content":"HTML string"}}

CONTENT RULES:
- 1200-1500 words
- Focus keyword in first sentence, 2+ H2 headings, ~1% density
- Short paragraphs (2-4 sentences)
- Include HTML comparison table if comparing products
- If the topic title explicitly names brands/providers/products, every named item must be covered in the article and included in any comparison table.
- Embed ALL affiliate links below using <a href="URL" target="_blank" rel="nofollow sponsored">CTA text</a>
- Use ONLY the exact affiliate URLs provided below.
- Do NOT invent, shorten, expand, replace, or modify any URL.
- Do NOT include any external product/referral/tracking URL unless it appears exactly in the list below.
- TapTap: always mention promo code IQBAL12 + €10 bonus for €50+
- Add FAQ section at end using Rank Math schema.
- NO affiliate disclosure box.

CATEGORIES (pick 1-2, exact names only):
{cats_str}

AFFILIATE LINKS (ALL must appear in content):
{links_html}"""

    if locked_title:
        user = (
            f"Write a high-conversion SEO article in English for this topic: {topic}\n\n"
            f"Important: preserve this exact final English title verbatim in the JSON title field:\n"
            f"{locked_title}"
        )
    else:
        user = f"Write a high-conversion SEO article in English for this topic: {topic}"

    def _call():
        return client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

    log.info("  Calling Claude API (EN article)...")
    r = claude_with_retry(_call)
    raw = r.content[0].text.strip()
    article = _parse_json_safe(raw, "failed_en_article.txt")

    if locked_title:
        article["title"] = locked_title

    for name, url in rel_links.items():
        if url not in article.get("content", ""):
            log.warning(f"  Link missing from content: {name} ({url})")

    if article.get("content"):
        cleaned, swaps = enforce_go_links(article["content"], WP_URL)
        if swaps:
            log.info(f"  Enforced /go/ links: replaced {len(swaps)} direct URL(s):")
            for old, new in swaps:
                log.info(f"    {old[:60]} → {new}")
        article["content"] = cleaned

        article["content"], auto_linked_count = autolink_plain_text_mentions(
            article["content"],
            rel_links,
            WP_URL,
        )
        if auto_linked_count:
            log.info(f"  Auto-linked {auto_linked_count} plain-text mention(s) in EN article")

    article = normalize_article_seo(article, topic, lang="en", locked_title=locked_title)
    save_cached_article(cache_name, article)
    return article

# ============================================================
#  ✍️  ARTICLE TRANSLATION (DE)
# ============================================================

def generate_article_de(
    en_article: dict,
    rel_links: dict,
    locked_title_de: Optional[str] = None,
) -> dict:
    base_slug = en_article.get("slug", "unknown")
    de_cache_key = f"DE_{base_slug}" if not locked_title_de else f"LOCKED_DE_{base_slug}"
    cached = load_cached_article(de_cache_key)
    if cached:
        return cached

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    links_html = format_links_as_html(rel_links)
    cats_str = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)
    en_content = re.sub(r"<[^>]+>", " ", en_article.get("content", ""))[:4000]

    system = f"""Du bist ein SEO-Texter für germanysupport.de. Jahr: {CURRENT_YEAR}.

SPRACHREGEL:
- Schreibe ALLES nur auf Deutsch.
- Auch wenn der ursprüngliche Titel oder Inhalt auf Englisch oder in einer anderen Sprache ist, muss die Ausgabe vollständig auf Deutsch sein.
- Titel, Slug, Meta-Beschreibung, Focus-Keyword, Tags und kompletter Content müssen auf Deutsch sein.
- Gib keinen englischen Fließtext aus, außer bei Markennamen oder feststehenden Produktnamen.

AUSGABE: Nur ein einzeiliges minimiertes JSON-Objekt. Kein Markdown.
Alle Anführungszeichen in HTML müssen escaped sein: \\".

JSON-Schema:
{{"title":"string","slug":"string max 60","meta_description":"string 150-155 Zeichen","focus_keyword":"string","tags":["string"],"categories":["string"],"content":"HTML string"}}

REGELN:
- Natürliches, flüssiges Deutsch
- Deutsche SEO-Keywords
- Alle HTML-Tags beibehalten
- Affiliate-Links beibehalten — nur Linktext übersetzen, URLs NICHT ändern
- Wenn im Thema explizit Marken/Anbieter/Produkte genannt werden, müssen alle genannten Einträge im Inhalt vorkommen und in Vergleichstabellen enthalten sein.
- Nutze NUR die unten angegebenen exakten URLs.
- TapTap: Promo-Code IQBAL12 erwähnen, €10 Bonus für €50+
- FAQ-Sektion am Ende mit Rank Math Schema
- KEIN Disclosure-Box

KATEGORIEN (1-2, exakte Namen):
{cats_str}

AFFILIATE-LINKS (alle müssen im Content erscheinen):
{links_html}"""

    if locked_title_de:
        user = (
            f"Übersetze und optimiere für deutsche Expats:\n\n"
            f"TITEL: {en_article['title']}\n\n"
            f"INHALT:\n{en_content}\n\n"
            f"Wichtig: Verwende exakt diesen finalen deutschen Titel im JSON-Feld 'title':\n"
            f"{locked_title_de}"
        )
    else:
        user = (
            f"Übersetze und optimiere für deutsche Expats:\n\n"
            f"TITEL: {en_article['title']}\n\n"
            f"INHALT:\n{en_content}"
        )

    def _call():
        return client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

    log.info("  Calling Claude API (DE translation)...")
    r = claude_with_retry(_call)
    raw = r.content[0].text.strip()
    article = _parse_json_safe(raw, "failed_de_article.txt")

    if locked_title_de:
        article["title"] = locked_title_de

    if article.get("content"):
        cleaned, swaps = enforce_go_links(article["content"], WP_URL)
        if swaps:
            log.info(f"  Enforced /go/ links (DE): replaced {len(swaps)} direct URL(s)")
        article["content"] = cleaned

        article["content"], auto_linked_count = autolink_plain_text_mentions(
            article["content"],
            rel_links,
            WP_URL,
        )
        if auto_linked_count:
            log.info(f"  Auto-linked {auto_linked_count} plain-text mention(s) in DE article")

    article = normalize_article_seo(
        article,
        article.get("title") or en_article.get("title", ""),
        lang="de",
        locked_title=locked_title_de,
    )

    save_cached_article(de_cache_key, article)
    return article

# ============================================================
#  🧹  JSON PARSER
# ============================================================

def _parse_json_safe(raw: str, error_filename: str = "failed.txt") -> dict:
    text = raw.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    fixed = fixed.replace('\u201c', '"').replace('\u201d', '"')
    fixed = fixed.replace('\u2018', "'").replace('\u2019', "'")
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    log.warning("JSON malformed — asking Claude to repair (no content regenerated)...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    def _repair_call():
        return client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": f"Fix this malformed JSON. Return ONLY valid JSON:\n\n{text[:4000]}"}],
        )

    r2 = claude_with_retry(_repair_call)
    repaired = r2.content[0].text.strip()
    repaired = re.sub(r"^```json\s*", "", repaired)
    repaired = re.sub(r"```$", "", repaired).strip()
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        error_path = LOG_DIR / error_filename
        error_path.write_text(raw, encoding="utf-8")
        log.error(f"JSON repair failed. Raw saved to: {error_path}")
        raise

# ============================================================
#  🖼️  PEXELS IMAGE
# ============================================================

def fetch_pexels_image(query: str):
    hdrs = {"Authorization": PEXELS_KEY}
    params = {"query": query, "per_page": 5, "orientation": "landscape"}
    r = requests.get("https://api.pexels.com/v1/search", headers=hdrs, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("photos"):
        fallback = query.split()[0]
        log.warning(f"No Pexels results for '{query}', retrying '{fallback}'")
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers=hdrs,
            params={"query": fallback, "per_page": 5, "orientation": "landscape"},
            timeout=20
        )
        data = r.json()
    if not data.get("photos"):
        raise ValueError(f"No Pexels images found for: {query}")
    photo = data["photos"][0]
    return (requests.get(photo["src"]["large2x"], timeout=30).content, photo["photographer"], photo["src"]["large2x"])

def upload_image(img_bytes, slug, title, photographer):
    safe = re.sub(r"[^a-z0-9-]", "-", slug)[:60]
    hdrs = dict(HEADERS)
    hdrs["Content-Type"] = "image/jpeg"
    hdrs["Content-Disposition"] = f'attachment; filename="{safe}.jpg"'
    r = requests.post(f"{WP_URL}/wp-json/wp/v2/media", headers=hdrs, data=img_bytes, timeout=60)
    if not r.ok:
        raise Exception(f"Image upload failed {r.status_code}: {r.text[:200]}")
    mid = r.json()["id"]
    requests.post(
        f"{WP_URL}/wp-json/wp/v2/media/{mid}",
        headers=HEADERS,
        json={"alt_text": title, "caption": f"Photo by {photographer} on Pexels"},
        timeout=15,
    )
    return mid

# ============================================================
#  📂  CATEGORIES & TAGS
# ============================================================

def fetch_wp_categories():
    cat_map, page = {}, 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            headers=HEADERS,
            params={"per_page": 100, "page": page, "_fields": "id,name"},
            timeout=20,
        )
        if r.status_code == 400 or not r.ok:
            break
        batch = r.json()
        if not batch:
            break
        for c in batch:
            cat_map[c["name"].lower()] = c["id"]
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
    return cat_map

def resolve_cats(chosen, cat_map):
    from difflib import SequenceMatcher as SM
    ids = []
    for name in chosen:
        nl = name.lower()
        if nl in cat_map:
            ids.append(cat_map[nl])
            continue
        best_s, best_k = 0, None
        for k in cat_map:
            s = SM(None, nl, k).ratio()
            if s > best_s:
                best_s, best_k = s, k
        if best_k and best_s >= 0.60:
            ids.append(cat_map[best_k])
    if not ids:
        fb = "living in germany"
        if fb in cat_map:
            ids.append(cat_map[fb])
    return ids

def sync_tags(names):
    ids = []
    for name in names:
        try:
            ids.append(wp_request("POST", "tags", json={"name": name})["id"])
        except Exception:
            try:
                s = requests.get(
                    f"{WP_URL}/wp-json/wp/v2/tags",
                    headers=HEADERS,
                    params={"search": name, "per_page": 1},
                    timeout=15,
                ).json()
                if s:
                    ids.append(s[0]["id"])
            except Exception:
                pass
    return ids

# ============================================================
#  🌐  POLYLANG: LINK EN ↔ DE
# ============================================================

def link_translations(en_id: int, de_id: int):
    try:
        r1 = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{en_id}",
            headers=HEADERS,
            json={"lang": "en", "translations": {"en": en_id, "de": de_id}},
            timeout=15,
        )
        r2 = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{de_id}",
            headers=HEADERS,
            json={"lang": "de", "translations": {"en": en_id, "de": de_id}},
            timeout=15,
        )
        if r1.ok and r2.ok:
            log.info(f"  Polylang: EN {en_id} ↔ DE {de_id} linked ✓")
            return True
        log.warning(f"  Polylang link failed: EN={r1.status_code} DE={r2.status_code}")
        return False
    except Exception as e:
        log.warning(f"  Polylang link error: {e}")
        return False

# ============================================================
#  🚀  PUBLISH TO WORDPRESS
# ============================================================

def publish_post(article: dict, featured_id, cat_ids, tag_ids, photographer: str, lang: str = "en") -> dict:
    footer = (
        f'<hr/><p><em>Featured image by <strong>{photographer}</strong> via '
        f'<a href="https://www.pexels.com" target="_blank" rel="nofollow">Pexels</a>.'
        f'</em></p>'
    )
    payload = {
        "title": article["title"],
        "slug": article["slug"],
        "content": article["content"] + footer,
        "status": "publish",
        "featured_media": featured_id,
        "tags": tag_ids,
        "categories": cat_ids,
        "excerpt": article["meta_description"],
        "lang": lang,
    }
    return wp_request("POST", "posts", json=payload)

# ============================================================
#  🚀  MAIN PIPELINE
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport AutoBlogger")
    parser.add_argument("--topic", type=str, default=None, help="Optional custom topic override")
    parser.add_argument("--skip-translate", action="store_true", help="Publish English article only, skip German translation")
    parser.add_argument("--manual-only", action="store_true", help="Publish only from manual_topics.csv and exit if none pending")
    args = parser.parse_args()

    log.info("=" * 62)
    log.info(f"GermanySupport AutoBlogger — {CURRENT_YEAR}")
    log.info("=" * 62)

    log.info("[1] Fetching WordPress data...")
    fetch_referral_links(WP_URL, force=True)
    cat_map = fetch_wp_categories()
    all_posts = fetch_all_post_data()
    log.info(f"    {len(all_posts)} existing posts | {len(cat_map)} categories")

    manual_idx = None
    manual_row = None
    manual_rows = []
    forced_products = []
    locked_title_en = None
    locked_title_de = None

    if not args.topic:
        manual_idx, manual_row, manual_rows = get_next_manual_topic()
        if manual_row:
            forced_products = parse_manual_products(manual_row)

    log.info("[2] Selecting topic...")
    publish_mode = normalize_publish_mode(skip_translate=args.skip_translate)

    if args.topic:
        topic, source = pick_fresh_topic(all_posts, args.topic)
        locked_title_en = topic

    elif manual_row:
        raw_topic = (manual_row.get("topic") or "").strip()
        topic, was_rewritten = resolve_manual_topic_with_dedup(raw_topic, all_posts)

        if topic is None:
            if manual_rows and manual_idx is not None:
                mark_manual_topic_skipped(manual_rows, manual_idx)
                log.info(f"  [CSV] Row marked 'skipped' in {MANUAL_TOPICS_FILE.name}")
            log.warning("  Exiting without publishing — update the topic in the CSV and re-queue.")
            return

        if was_rewritten:
            log.info(
                f"  [REWRITE] Manual topic rewritten to avoid duplication:\n"
                f"    Original : {raw_topic}\n"
                f"    Final    : {topic}"
            )
            if manual_rows and manual_idx is not None:
                update_manual_topic_text(manual_rows, manual_idx, topic)
                log.info(f"  [CSV] Rewritten topic saved back to {MANUAL_TOPICS_FILE.name}")

        source = "manual"
        row_lang = (manual_row.get("language") or "").strip().lower()
        publish_mode = normalize_publish_mode(language_value=row_lang, skip_translate=False)
        locked_title_en = topic

    elif args.manual_only:
        log.info("    No pending manual topics found.")
        return

    else:
        topic, source = pick_fresh_topic(all_posts, None)

    if locked_title_en and publish_mode in ("de", "both"):
        log.info("  Translating locked title for DE...")
        locked_title_de = translate_locked_title_to_german(locked_title_en)
        log.info(f"  Locked DE title: {locked_title_de}")

    log.info(f"    Source : {source}")
    log.info(f"    Topic  : {topic}")
    log.info(f"    Mode   : {publish_mode}")
    if locked_title_en:
        log.info(f"    Locked EN title: {locked_title_en}")
    if locked_title_de:
        log.info(f"    Locked DE title: {locked_title_de}")
    if forced_products:
        log.info(f"    Manual products: {forced_products}")

    log.info("[3] Resolving referral links...")
    rel_links = resolve_referral_links(topic, forced_products=forced_products)

    log.info("[4] Generating English article...")
    en_article = generate_article_en(topic, rel_links, locked_title=locked_title_en)
    log.info(f"    Title   : {en_article['title']}")
    log.info(f"    KW      : {en_article.get('focus_keyword', 'N/A')}")
    log.info(f"    Words   : ~{len(en_article.get('content','').split())}")

    log.info("[5] Fetching featured image...")
    img_query = en_article.get("image_search_query", topic.split()[0])
    img_bytes, photographer, img_url = fetch_pexels_image(img_query)
    featured_id = upload_image(img_bytes, en_article["slug"], en_article["title"], photographer)
    log.info(f"    Photographer : {photographer}")
    log.info(f"    Media ID     : {featured_id}")

    en_post = None
    en_post_id = None
    de_post = None
    de_post_id = None
    publish_success = False

    if publish_mode in ("en", "both"):
        log.info("[6] Publishing English article...")
        en_tag_ids = sync_tags(en_article.get("tags", []))
        en_cat_ids = resolve_cats(en_article.get("categories", ["Living in Germany"]), cat_map)
        en_post = publish_post(en_article, featured_id, en_cat_ids, en_tag_ids, photographer, lang="en")
        en_post_id = en_post["id"]
        publish_success = True
        log.info(f"    Published EN: {en_post['link']}")

        log.info("[7] Setting Rank Math SEO (EN)...")
        meta_title = f"{en_article['title']} | GermanySupport.de"
        set_rank_math_seo(en_post_id, en_article.get("focus_keyword", ""), meta_title, en_article.get("meta_description", ""))
    else:
        log.info("[6] Skipping English publish (DE-only mode).")

    if publish_mode in ("de", "both"):
        log.info("[8] Generating German translation...")
        try:
            de_article = generate_article_de(
                en_article,
                rel_links,
                locked_title_de=locked_title_de,
            )
            log.info(f"    DE Title : {de_article['title']}")

            de_tag_ids = sync_tags(de_article.get("tags", []))
            de_cat_ids = resolve_cats(de_article.get("categories", ["Living in Germany"]), cat_map)
            de_post = publish_post(de_article, featured_id, de_cat_ids, de_tag_ids, photographer, lang="de")
            de_post_id = de_post["id"]
            publish_success = True
            log.info(f"    Published DE: {de_post['link']}")

            de_meta_title = f"{de_article['title']} | GermanySupport.de"
            set_rank_math_seo(de_post_id, de_article.get("focus_keyword", ""), de_meta_title, de_article.get("meta_description", ""))

            if en_post_id and de_post_id:
                link_translations(en_post_id, de_post_id)

            clear_cached_article(f"DE_{en_article.get('slug', 'unknown')}")
            clear_cached_article(f"LOCKED_DE_{en_article.get('slug', 'unknown')}")

        except Exception as e:
            log.error(f"    German translation failed: {e}")
            if publish_mode == "both":
                log.warning("    EN article was published successfully. Run translate_articles.py to create DE version later.")
            else:
                log.warning("    DE-only publish failed. EN was not published.")
    else:
        log.info("[8] Skipping German translation/publish.")

    clear_cached_article(topic)
    if locked_title_en:
        clear_cached_article(f"LOCKED_EN::{topic}")

    if source == "manual" and manual_rows and manual_idx is not None and publish_success:
        mark_manual_topic_done(manual_rows, manual_idx)
        log.info(f"    Manual topic marked done in {MANUAL_TOPICS_FILE.name}")

    log.info("")
    log.info("=" * 62)
    log.info("  PIPELINE COMPLETE")
    log.info("=" * 62)
    if en_post:
        log.info(f"  EN post  : {en_post['link']}")
    if de_post:
        log.info(f"  DE post  : {de_post['link']}")
    log.info(f"  Topic    : {topic}")
    log.info(f"  Source   : {source}")
    log.info(f"  Mode     : {publish_mode}")
    log.info(f"  Image    : {img_url}")
    log.info("=" * 62)

    success_lines = [
        f"Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Host   : {socket.gethostname()}",
        "",
        "publish_article.py completed successfully.",
        f"Topic  : {topic}",
        f"Source : {source}",
        f"Mode   : {publish_mode}",
        f"Image  : {img_url}",
    ]
    if en_post:
        success_lines.append(f"EN post : {en_post['link']}")
    if de_post:
        success_lines.append(f"DE post : {de_post['link']}")

    send_email(
        subject="Autoblogger success: publish_article.py",
        body="\n".join(success_lines),
    )

if __name__ == "__main__":
    try:
        main()
    except Exception:
        error_details = traceback.format_exc()
        failure_body = "\n".join([
            f"Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Host : {socket.gethostname()}",
            "",
            "publish_article.py failed with an unhandled exception.",
            "",
            error_details,
        ])
        send_email(
            subject="Autoblogger FAILED: publish_article.py",
            body=failure_body,
        )
        raise