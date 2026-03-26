"""
GermanySupport.de — Shared Configuration
==========================================
Single source of truth for:
  - Categories
  - Referral links (fetched dynamically from WordPress)
  - TapTap promo code logic
  - Link relevance mapping

HOW REFERRAL LINKS WORK:
  1. At runtime, fetch_referral_links() calls /wp-json/gs/v1/referral-links
     which reads all active /go/* redirects from the Redirection plugin.
  2. The result is merged with STATIC_FALLBACK_LINKS so the script
     still works even if the API is down.
  3. Removed/non-affiliated products are excluded via EXCLUDED_PRODUCTS.

TO ADD/CHANGE A LINK:
  → Edit it in WordPress Redirection plugin. No code changes needed.

TO REMOVE A PRODUCT PERMANENTLY:
  → Add its slug to EXCLUDED_PRODUCTS below.
"""

import os
import json
import time
import logging
from datetime import datetime
from difflib import SequenceMatcher

import requests as _requests

logger = logging.getLogger(__name__)

# ============================================================
#  📅  CURRENT YEAR — auto-detected
# ============================================================
CURRENT_YEAR = datetime.now().year

# ============================================================
#  🚫  EXCLUDED PRODUCTS
#  These slugs are NEVER used, even if present in WordPress.
#  Products we have no affiliation with.
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
#  Used when the WordPress API is unreachable.
#  Keep in sync manually as a backup only.
# ============================================================
STATIC_FALLBACK_LINKS = {
    # COMPARISON PORTALS
    "go/tarifcheck":          "https://germanysupport.de/go/tarifcheck",
    "go/check24":             "https://germanysupport.de/go/check24",
    "go/verivox":             "https://germanysupport.de/go/verivox",
    # BANKING
    "go/n26":                 "https://germanysupport.de/go/n26",
    "go/c24":                 "https://germanysupport.de/go/c24",
    "go/advanzia":            "https://germanysupport.de/go/advanzia",
    "go/credit-cards":        "https://germanysupport.de/go/credit-cards",
    "go/trade-republic":      "https://germanysupport.de/go/trade-republic",
    "go/scalable-capital":    "https://germanysupport.de/go/scalable-capital",
    "go/paypal":              "https://germanysupport.de/go/paypal",
    # INSURANCE
    "go/haftpflicht":         "https://germanysupport.de/go/haftpflicht",
    "go/huk24":               "https://germanysupport.de/go/huk24",
    "go/car-insurance":       "https://germanysupport.de/go/car-insurance",
    "go/legal-insurance":     "https://germanysupport.de/go/legal-insurance",
    # TAX
    "go/steuergo":            "https://germanysupport.de/go/steuergo",
    "go/wiso":                "https://germanysupport.de/go/wiso",
    # INTERNET & MOBILE
    "go/verivox-dsl":         "https://germanysupport.de/go/verivox-dsl",
    "go/dsl-check24":         "https://germanysupport.de/go/dsl-check24",
    "go/klarmobil":           "https://germanysupport.de/go/klarmobil",
    "go/check24-mobile":      "https://germanysupport.de/go/check24-mobile",
    "go/vodafone":            "https://germanysupport.de/go/vodafone",
    "go/telekom":             "https://germanysupport.de/go/telekom",
    "go/telekom-fiber":       "https://germanysupport.de/go/telekom-fiber",
    # UTILITIES
    "go/electricity":         "https://germanysupport.de/go/electricity",
    "go/gas":                 "https://germanysupport.de/go/gas",
    # TRAVEL
    "go/travel":              "https://germanysupport.de/go/travel",
    "go/car-rental":          "https://germanysupport.de/go/car-rental",
    "go/vacation":            "https://germanysupport.de/go/vacation",
    # MONEY TRANSFER
    "go/ace":                 "https://germanysupport.de/go/ace",
    "go/taptap":              "https://germanysupport.de/go/taptap",
    # CASHBACK
    "go/shoop":               "https://germanysupport.de/go/shoop",
    "go/igraal":              "https://germanysupport.de/go/igraal",
    "go/payback":             "https://germanysupport.de/go/payback",
}

# Human-readable display names for slugs
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
#  💰  TAPTAP PROMO CODE
# ============================================================
TAPTAP_PROMO_CODE = "IQBAL12"
TAPTAP_PROMO_HTML = (
    '<a href="https://germanysupport.de/go/taptap" '
    'target="_blank" rel="nofollow sponsored">TapTap Send</a> '
    f'— use promo code <strong>{TAPTAP_PROMO_CODE}</strong> when sending '
    '€50 or more to receive a <strong>€10–€15 bonus</strong> on your transfer.'
)
TAPTAP_PROMO_TEXT = (
    f"TapTap Send (promo code {TAPTAP_PROMO_CODE}: get €10-€15 bonus when sending €50+)"
)

# ============================================================
#  📂  ALLOWED CATEGORIES
# ============================================================
ALLOWED_CATEGORIES = [
    "Best Deals",
    "Bureaucracy",
    "Car Rental and Driving",
    "Cost of Living",
    "Culture and Integration",
    "Emergency Services",
    "Employment and Careers",
    "Family & Children",
    "Family and Education",
    "Finance",
    "Finance and Banking",
    "Food and Restaurants",
    "German Language Learning",
    "Healthcare System",
    "Housing",
    "Immigrant Success Stories",
    "Immigration",
    "Insurance",
    "Living in Germany",
    "Public Transportation",
    "Relocation and Moving",
    "Residency and Citizenship",
    "Retirement in Germany",
    "Shopping and Discounts",
    "Student Life in Germany",
    "Tax",
    "Technology and Internet",
    "Travel and Tourism",
    "Utilities",
    "Working Freelance",
    "Bank Accounts and Payments",
    "Mobile and Internet Plans",
    "Electricity and Gas Providers",
    "Car Insurance and Vehicle Registration",
    "Health Insurance Options",
    "Pension and Retirement Planning",
    "Childcare and Kindergartens",
    "Schools and Universities",
    "Housing Rentals and Buying Property",
    "Visa and Work Permit Guidance",
    "Legal Assistance and Law",
    "Emergency Contacts and Police",
    "Public Services and Registrations",
    "Language Courses and Certifications",
    "Cultural Events and Festivals",
    "Local Community Networks",
    "Shopping Guides and Online Deals",
    "Travel Planning and Transportation",
    "Tax Filing and Financial Advice",
    "Freelancing and Business Registration",
    "Investment and Savings Options",
    "Digital Tools and Apps",
    "Government Support and Benefits",
    "Healthcare Providers and Doctors",
    "Environmental and Recycling Guidelines",
    "Insurance Comparisons and Offers",
    "Banking Promotions and Referral Offers",
    "Student Discounts and Campus Life",
    "Tourist Attractions and Sightseeing",
]

# ============================================================
#  🔗  LINK RELEVANCE MAP
#  slug_suffix → [keywords that trigger this link]
# ============================================================
LINK_RELEVANCE = {
    "go/n26":              ["bank", "account", "banking", "girokonto", "finanz"],
    "go/c24":              ["bank", "account", "banking", "girokonto", "finanz"],
    "go/advanzia":         ["credit card", "mastercard", "kreditkarte"],
    "go/credit-cards":     ["credit card", "kreditkarte", "card comparison"],
    "go/trade-republic":   ["invest", "stock", "etf", "broker", "trading", "aktien"],
    "go/scalable-capital": ["invest", "stock", "etf", "broker", "trading"],
    "go/paypal":           ["payment", "online shopping", "transfer"],
    "go/haftpflicht":      ["insurance", "haftpflicht", "liability", "versicherung"],
    "go/huk24":            ["car insurance", "kfz", "auto", "vehicle"],
    "go/car-insurance":    ["car insurance", "kfz", "auto", "vehicle"],
    "go/legal-insurance":  ["legal", "rechtsschutz", "lawyer", "anwalt"],
    "go/steuergo":         ["tax", "steuer", "steuererklärung", "finanzamt"],
    "go/wiso":             ["tax", "steuer", "steuererklärung", "finanzamt"],
    "go/verivox-dsl":      ["internet", "dsl", "broadband", "provider"],
    "go/dsl-check24":      ["internet", "dsl", "broadband", "provider"],
    "go/klarmobil":        ["mobile", "sim", "phone plan", "prepaid", "handy"],
    "go/check24-mobile":   ["mobile", "sim", "phone plan", "prepaid", "handy"],
    "go/vodafone":         ["mobile", "sim", "phone", "internet", "network"],
    "go/telekom":          ["mobile", "sim", "phone", "internet", "telekom"],
    "go/telekom-fiber":    ["fiber", "glasfaser", "internet", "broadband"],
    "go/electricity":      ["electricity", "strom", "energy", "energie", "utility"],
    "go/gas":              ["gas", "heating", "heizung", "energie", "utility"],
    "go/travel":           ["travel", "trip", "holiday", "flight", "reise"],
    "go/car-rental":       ["car rental", "rent a car", "mietwagen", "driving"],
    "go/vacation":         ["vacation", "holiday", "urlaub", "hotel"],
    "go/ace":              ["money transfer", "send money", "remittance", "overseas"],
    "go/taptap":           ["money transfer", "send money", "remittance", "overseas"],
    "go/shoop":            ["cashback", "saving", "discount", "deals", "shopping"],
    "go/igraal":           ["cashback", "saving", "discount", "deals", "shopping"],
    "go/payback":          ["cashback", "loyalty", "points", "reward", "shopping"],
    "go/tarifcheck":       ["compare", "vergleich", "tariff", "plan", "provider"],
    "go/check24":          ["compare", "vergleich", "insurance", "internet", "energy"],
    "go/verivox":          ["compare", "vergleich", "energy", "internet", "gas"],
}

# ============================================================
#  🌐  DYNAMIC LINK FETCHING
# ============================================================

# Module-level cache: {slug: full_url}
_LINK_CACHE: dict = {}
_CACHE_TS: float  = 0.0
_CACHE_TTL: int   = 3600  # 1 hour


def fetch_referral_links(wp_url: str, force: bool = False) -> dict:
    """
    Fetch all active /go/* redirect links from WordPress.
    Returns a dict of {slug: full_url} — e.g. {"go/n26": "https://..."}.

    Caches results for 1 hour.  Falls back to STATIC_FALLBACK_LINKS
    if the API call fails.

    Excluded slugs (EXCLUDED_SLUGS) are always removed from the result.
    """
    global _LINK_CACHE, _CACHE_TS

    now = time.time()
    if not force and _LINK_CACHE and (now - _CACHE_TS) < _CACHE_TTL:
        return _LINK_CACHE

    api_url = f"{wp_url.rstrip('/')}/wp-json/gs/v1/referral-links"
    try:
        r = _requests.get(api_url, timeout=15)
        r.raise_for_status()
        data  = r.json()
        links = data.get("links", {})
        # Normalise: ensure full URLs
        normalised = {}
        for slug, target in links.items():
            slug = slug.strip("/")
            if not slug.startswith("go/"):
                slug = f"go/{slug.split('go/')[-1]}" if "go/" in slug else slug
            # Skip excluded
            short = slug.replace("go/", "")
            if short in EXCLUDED_SLUGS:
                continue
            # Ensure absolute URL
            if target.startswith("/"):
                target = wp_url.rstrip("/") + target
            normalised[slug] = target

        if normalised:
            _LINK_CACHE = normalised
            _CACHE_TS   = now
            logger.info(f"Fetched {len(normalised)} referral links from WordPress API.")
            return normalised

    except Exception as e:
        logger.warning(f"Could not fetch referral links from API: {e}")

    # Fallback
    logger.warning("Using static fallback referral links.")
    fallback = {
        k: v for k, v in STATIC_FALLBACK_LINKS.items()
        if k.replace("go/", "") not in EXCLUDED_SLUGS
    }
    _LINK_CACHE = fallback
    _CACHE_TS   = now
    return fallback


def get_relevant_links(title: str, content_text: str,
                       wp_url: str = "", min_links: int = 2) -> dict:
    """
    Return relevant affiliate links for an article.
    Fetches links dynamically if wp_url is provided; uses cache otherwise.
    Returns {display_name: full_url}.
    """
    all_links = fetch_referral_links(wp_url) if wp_url else _LINK_CACHE or STATIC_FALLBACK_LINKS
    combined  = (title + " " + content_text).lower()
    relevant  = {}

    for slug, keywords in LINK_RELEVANCE.items():
        if slug not in all_links:
            continue
        if any(kw in combined for kw in keywords):
            name = SLUG_DISPLAY_NAMES.get(slug, slug)
            relevant[name] = all_links[slug]

    # Ensure minimum
    if len(relevant) < min_links:
        for slug in ["go/n26", "go/shoop", "go/steuergo"]:
            if slug in all_links:
                name = SLUG_DISPLAY_NAMES.get(slug, slug)
                if name not in relevant:
                    relevant[name] = all_links[slug]

    return relevant


def get_all_links_dict(wp_url: str = "") -> dict:
    """Return all referral links as {display_name: url}."""
    raw = fetch_referral_links(wp_url) if wp_url else _LINK_CACHE or STATIC_FALLBACK_LINKS
    return {
        SLUG_DISPLAY_NAMES.get(slug, slug): url
        for slug, url in raw.items()
        if slug.replace("go/", "") not in EXCLUDED_SLUGS
    }


def format_links_for_prompt(relevant_links: dict) -> str:
    """Format as plain text list for Claude prompts."""
    lines = []
    for name, url in relevant_links.items():
        if name == "TapTap Send":
            lines.append(f"- {TAPTAP_PROMO_TEXT}: {url}")
        else:
            lines.append(f"- {name}: {url}")
    return "\n".join(lines)


def format_links_as_html(relevant_links: dict) -> str:
    """Format as ready-to-embed HTML <a> tags for Claude."""
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