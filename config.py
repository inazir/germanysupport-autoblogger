"""
GermanySupport.de — Shared Configuration
==========================================
Single source of truth for all scripts.

KEY FIX in this version:
  fetch_referral_links() slug normalisation was broken — slugs like
  "go/n26" were sometimes returned as bare "n26" or with double "go/go/".
  Fixed to always return canonical "go/slug" keys with full absolute URLs.
"""

import time
import logging
from typing import Optional
from datetime import datetime
from difflib import SequenceMatcher

import requests as _requests

logger = logging.getLogger(__name__)

# ============================================================
#  📅  CURRENT YEAR
# ============================================================
CURRENT_YEAR = datetime.now().year

# ============================================================
#  🚫  EXCLUDED PRODUCTS (no affiliation)
# ============================================================
EXCLUDED_SLUGS = {
    "commerzbank",
    "amex",
    "metro",
    "getsafe",
    "congstar",
}

# ============================================================
#  🔒  STATIC FALLBACK LINKS
#  Used only when WordPress API is unreachable.
# ============================================================
STATIC_FALLBACK_LINKS = {
    "go/tarifcheck":       "https://germanysupport.de/go/tarifcheck",
    "go/check24":          "https://germanysupport.de/go/check24",
    "go/verivox":          "https://germanysupport.de/go/verivox",
    "go/n26":              "https://germanysupport.de/go/n26",
    "go/c24":              "https://germanysupport.de/go/c24",
    "go/advanzia":         "https://germanysupport.de/go/advanzia",
    "go/credit-cards":     "https://germanysupport.de/go/credit-cards",
    "go/trade-republic":   "https://germanysupport.de/go/trade-republic",
    "go/scalable-capital": "https://germanysupport.de/go/scalable-capital",
    "go/paypal":           "https://germanysupport.de/go/paypal",
    "go/haftpflicht":      "https://germanysupport.de/go/haftpflicht",
    "go/huk24":            "https://germanysupport.de/go/huk24",
    "go/car-insurance":    "https://germanysupport.de/go/car-insurance",
    "go/legal-insurance":  "https://germanysupport.de/go/legal-insurance",
    "go/steuergo":         "https://germanysupport.de/go/steuergo",
    "go/wiso":             "https://germanysupport.de/go/wiso",
    "go/verivox-dsl":      "https://germanysupport.de/go/verivox-dsl",
    "go/dsl-check24":      "https://germanysupport.de/go/dsl-check24",
    "go/klarmobil":        "https://germanysupport.de/go/klarmobil",
    "go/check24-mobile":   "https://germanysupport.de/go/check24-mobile",
    "go/vodafone":         "https://germanysupport.de/go/vodafone",
    "go/telekom":          "https://germanysupport.de/go/telekom",
    "go/telekom-fiber":    "https://germanysupport.de/go/telekom-fiber",
    "go/electricity":      "https://germanysupport.de/go/electricity",
    "go/gas":              "https://germanysupport.de/go/gas",
    "go/travel":           "https://germanysupport.de/go/travel",
    "go/car-rental":       "https://germanysupport.de/go/car-rental",
    "go/vacation":         "https://germanysupport.de/go/vacation",
    "go/ace":              "https://germanysupport.de/go/ace",
    "go/taptap":           "https://germanysupport.de/go/taptap",
    "go/shoop":            "https://germanysupport.de/go/shoop",
    "go/igraal":           "https://germanysupport.de/go/igraal",
    "go/payback":          "https://germanysupport.de/go/payback",
}

SLUG_DISPLAY_NAMES = {
    "go/tarifcheck":       "Tarifcheck",
    "go/check24":          "Check24",
    "go/verivox":          "Verivox",
    "go/n26":              "N26 Bank",
    "go/c24":              "C24 Bank",
    "go/advanzia":         "Advanzia Mastercard",
    "go/credit-cards":     "Credit Card Comparison",
    "go/trade-republic":   "Trade Republic",
    "go/scalable-capital": "Scalable Capital",
    "go/paypal":           "PayPal",
    "go/haftpflicht":      "Liability Insurance",
    "go/huk24":            "HUK24 Car Insurance",
    "go/car-insurance":    "Car Insurance Compare",
    "go/legal-insurance":  "Legal Insurance",
    "go/steuergo":         "SteuerGo",
    "go/wiso":             "WISO Steuer",
    "go/verivox-dsl":      "Verivox DSL",
    "go/dsl-check24":      "DSL Check24",
    "go/klarmobil":        "Klarmobil",
    "go/check24-mobile":   "Check24 Mobile",
    "go/vodafone":         "Vodafone",
    "go/telekom":          "Telekom",
    "go/telekom-fiber":    "Telekom Fiber",
    "go/electricity":      "Electricity Provider",
    "go/gas":              "Gas Provider",
    "go/travel":           "Check24 Travel",
    "go/car-rental":       "Check24 Car Rental",
    "go/vacation":         "Check24 Vacation",
    "go/ace":              "ACE Money Transfer",
    "go/taptap":           "TapTap Send",
    "go/shoop":            "Shoop Cashback",
    "go/igraal":           "iGraal Cashback",
    "go/payback":          "PAYBACK",
}

# ============================================================
#  💰  TAPTAP PROMO
# ============================================================
TAPTAP_PROMO_CODE = "IQBAL12"
TAPTAP_PROMO_HTML = (
    '<a href="https://germanysupport.de/go/taptap" '
    'target="_blank" rel="nofollow sponsored">TapTap Send</a> '
    f'— use promo code <strong>{TAPTAP_PROMO_CODE}</strong> when sending '
    '€50 or more to receive a <strong>€10–€15 bonus</strong>.'
)
TAPTAP_PROMO_TEXT = (
    f"TapTap Send (promo code {TAPTAP_PROMO_CODE}: "
    "get €10-€15 bonus when sending €50+)"
)

# ============================================================
#  📂  ALLOWED CATEGORIES
# ============================================================
ALLOWED_CATEGORIES = [
    "Best Deals", "Bureaucracy", "Car Rental and Driving",
    "Cost of Living", "Culture and Integration", "Emergency Services",
    "Employment and Careers", "Family & Children", "Family and Education",
    "Finance", "Finance and Banking", "Food and Restaurants",
    "German Language Learning", "Healthcare System", "Housing",
    "Immigrant Success Stories", "Immigration", "Insurance",
    "Living in Germany", "Public Transportation", "Relocation and Moving",
    "Residency and Citizenship", "Retirement in Germany",
    "Shopping and Discounts", "Student Life in Germany", "Tax",
    "Technology and Internet", "Travel and Tourism", "Utilities",
    "Working Freelance", "Bank Accounts and Payments",
    "Mobile and Internet Plans", "Electricity and Gas Providers",
    "Car Insurance and Vehicle Registration", "Health Insurance Options",
    "Pension and Retirement Planning", "Childcare and Kindergartens",
    "Schools and Universities", "Housing Rentals and Buying Property",
    "Visa and Work Permit Guidance", "Legal Assistance and Law",
    "Emergency Contacts and Police", "Public Services and Registrations",
    "Language Courses and Certifications", "Cultural Events and Festivals",
    "Local Community Networks", "Shopping Guides and Online Deals",
    "Travel Planning and Transportation", "Tax Filing and Financial Advice",
    "Freelancing and Business Registration", "Investment and Savings Options",
    "Digital Tools and Apps", "Government Support and Benefits",
    "Healthcare Providers and Doctors", "Environmental and Recycling Guidelines",
    "Insurance Comparisons and Offers", "Banking Promotions and Referral Offers",
    "Student Discounts and Campus Life", "Tourist Attractions and Sightseeing",
]

# ============================================================
#  🔗  LINK RELEVANCE MAP
# ============================================================
LINK_RELEVANCE = {
    "go/n26":              ["bank", "account", "banking", "girokonto"],
    "go/c24":              ["bank", "account", "banking", "girokonto"],
    "go/advanzia":         ["credit card", "mastercard", "kreditkarte"],
    "go/credit-cards":     ["credit card", "kreditkarte", "card"],
    "go/trade-republic":   ["invest", "stock", "etf", "broker", "trading"],
    "go/scalable-capital": ["invest", "stock", "etf", "broker"],
    "go/paypal":           ["payment", "online shopping", "transfer"],
    "go/haftpflicht":      ["insurance", "haftpflicht", "liability"],
    "go/huk24":            ["car insurance", "kfz", "auto", "vehicle"],
    "go/car-insurance":    ["car insurance", "kfz", "auto"],
    "go/legal-insurance":  ["legal", "rechtsschutz", "lawyer"],
    "go/steuergo":         ["tax", "steuer", "finanzamt"],
    "go/wiso":             ["tax", "steuer", "finanzamt"],
    "go/verivox-dsl":      ["internet", "dsl", "broadband"],
    "go/dsl-check24":      ["internet", "dsl", "broadband"],
    "go/klarmobil":        ["mobile", "sim", "phone plan", "prepaid"],
    "go/check24-mobile":   ["mobile", "sim", "phone plan", "prepaid"],
    "go/vodafone":         ["mobile", "sim", "phone", "internet"],
    "go/telekom":          ["mobile", "sim", "phone", "internet"],
    "go/telekom-fiber":    ["fiber", "glasfaser", "internet"],
    "go/electricity":      ["electricity", "strom", "energy", "utility"],
    "go/gas":              ["gas", "heating", "heizung", "utility"],
    "go/travel":           ["travel", "trip", "holiday", "flight"],
    "go/car-rental":       ["car rental", "rent a car", "mietwagen"],
    "go/vacation":         ["vacation", "holiday", "urlaub", "hotel"],
    "go/ace":              ["money transfer", "send money", "remittance"],
    "go/taptap":           ["money transfer", "send money", "remittance"],
    "go/shoop":            ["cashback", "saving", "discount", "deals"],
    "go/igraal":           ["cashback", "saving", "discount", "deals"],
    "go/payback":          ["cashback", "loyalty", "reward", "shopping"],
    "go/tarifcheck":       ["compare", "vergleich", "tariff", "provider"],
    "go/check24":          ["compare", "vergleich", "insurance", "internet"],
    "go/verivox":          ["compare", "vergleich", "energy", "internet"],
}

# ============================================================
#  🔄  MODULE-LEVEL CACHE
# ============================================================
_LINK_CACHE: dict = {}
_CACHE_TS: float = 0.0
_CACHE_TTL: int = 3600


def _normalise_slug(raw_slug: str, wp_base_url: str = "") -> str:
    """
    Convert any slug variant to canonical 'go/slug' form.

    Handles:
      /go/n26                 → go/n26
      go/n26                  → go/n26
      https://site.de/go/n26  → go/n26
      n26                     → go/n26  (if it came from a /go/* query)
    """
    s = raw_slug.strip("/").lower()

    if wp_base_url:
        base = wp_base_url.rstrip("/").lower()
        if s.startswith(base.replace("https://", "").replace("http://", "")):
            s = s[len(base.replace("https://", "").replace("http://", "")):].strip("/")
        elif s.startswith(base):
            s = s[len(base):].strip("/")

    while s.startswith("go/go/"):
        s = s[3:]

    if not s.startswith("go/"):
        s = f"go/{s}"

    return s


def fetch_referral_links(wp_url: str, force: bool = False) -> dict:
    """
    Fetch all active /go/* redirect links from WordPress.

    Returns {canonical_slug: absolute_url} e.g.:
      {"go/n26": "https://germanysupport.de/go/n26", ...}

    BUG FIX: previous version returned inconsistent slug formats
    (sometimes bare slugs, sometimes with double go/go/ prefix).
    This version always returns canonical 'go/slug' → full URL pairs.
    """
    global _LINK_CACHE, _CACHE_TS

    now = time.time()
    if not force and _LINK_CACHE and (now - _CACHE_TS) < _CACHE_TTL:
        return _LINK_CACHE

    api_url = f"{wp_url.rstrip('/')}/wp-json/gs/v1/referral-links"
    try:
        r = _requests.get(api_url, timeout=15)
        r.raise_for_status()
        data = r.json()
        raw_links = data.get("links", {})
        normalised = {}

        for raw_slug, target in raw_links.items():
            slug = _normalise_slug(raw_slug, wp_url)
            short = slug.replace("go/", "")

            if short in EXCLUDED_SLUGS:
                continue

            normalised[slug] = f"{wp_url.rstrip('/')}/{slug}"

        if normalised:
            _LINK_CACHE = normalised
            _CACHE_TS = now
            logger.info(f"Fetched {len(normalised)} referral links from WordPress API.")
            return normalised
        else:
            logger.warning("WordPress referral links API returned 0 links.")

    except Exception as e:
        logger.warning(f"Could not fetch referral links from API: {e}")

    logger.warning("Using static fallback referral links.")
    fallback = {
        k: v for k, v in STATIC_FALLBACK_LINKS.items()
        if k.replace("go/", "") not in EXCLUDED_SLUGS
    }
    _LINK_CACHE = fallback
    _CACHE_TS = now
    return fallback


def get_relevant_links(title: str, content_text: str, wp_url: str = "", min_links: int = 3) -> dict:
    """
    Return relevant affiliate links for an article as {display_name: url}.
    Always uses /go/* links.
    """
    all_links = fetch_referral_links(wp_url) if wp_url else _LINK_CACHE or STATIC_FALLBACK_LINKS
    combined = (title + " " + content_text).lower()
    relevant = {}

    for slug, keywords in LINK_RELEVANCE.items():
        if slug not in all_links:
            continue
        if any(kw in combined for kw in keywords):
            name = SLUG_DISPLAY_NAMES.get(slug, slug)
            relevant[name] = all_links[slug]

    defaults = ["go/n26", "go/shoop", "go/steuergo"]
    while len(relevant) < min_links:
        for slug in defaults:
            if slug in all_links:
                name = SLUG_DISPLAY_NAMES.get(slug, slug)
                if name not in relevant:
                    relevant[name] = all_links[slug]
                    break
        else:
            break

    return relevant


def get_all_links_dict(wp_url: str = "") -> dict:
    """All referral links as {display_name: url}."""
    raw = fetch_referral_links(wp_url) if wp_url else _LINK_CACHE or STATIC_FALLBACK_LINKS
    return {
        SLUG_DISPLAY_NAMES.get(slug, slug): url
        for slug, url in raw.items()
    }


def format_links_for_prompt(relevant_links: dict) -> str:
    """Plain-text list for Claude prompts."""
    lines = []
    for name, url in relevant_links.items():
        if name == "TapTap Send":
            lines.append(f"- {TAPTAP_PROMO_TEXT}: {url}")
        else:
            lines.append(f"- {name}: {url}")
    return "\n".join(lines)


def format_referral_links(relevant_links: dict) -> str:
    """Backward-compatible alias used by publish_article.py."""
    return format_links_for_prompt(relevant_links)


def format_links_as_html(relevant_links: dict) -> str:
    """HTML <a> tags for Claude prompts."""
    lines = []
    for name, url in relevant_links.items():
        if name == "TapTap Send":
            lines.append(f"- TapTap Send with promo: {TAPTAP_PROMO_HTML}")
        else:
            lines.append(
                f'- {name}: <a href="{url}" target="_blank" '
                f'rel="nofollow sponsored">{name}</a>'
            )
    return "\n".join(lines)


def build_referral_replacement_map(wp_url: str, force: bool = False) -> dict:
    """
    Build a strict replacement map from the live WordPress referral endpoint.

    Returns {raw_affiliate_url_or_domain_pattern: public_go_url}.
    Only links present in the plugin response are included. No guessed products.
    """
    api_url = f"{wp_url.rstrip('/')}/wp-json/gs/v1/referral-links"
    replacement_map = {}

    try:
        r = _requests.get(api_url, timeout=15)
        r.raise_for_status()
        data = r.json()
        raw_links = data.get("links", {})

        for raw_slug, target in raw_links.items():
            slug = _normalise_slug(raw_slug, wp_url)
            short = slug.replace("go/", "")
            if short in EXCLUDED_SLUGS:
                continue

            public_url = f"{wp_url.rstrip('/')}/{slug}"

            if target.startswith("/"):
                target = wp_url.rstrip("/") + target
            elif not target.startswith("http"):
                target = wp_url.rstrip("/") + "/" + target.lstrip("/")

            replacement_map[target] = public_url

            try:
                from urllib.parse import urlparse
                parsed = urlparse(target)
                domain = parsed.netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
                if domain:
                    replacement_map[domain] = public_url
            except Exception:
                pass

        logger.info(f"Built strict replacement map with {len(replacement_map)} entries.")
        return replacement_map

    except Exception as e:
        logger.warning(f"Could not build referral replacement map from API: {e}")
        return {}