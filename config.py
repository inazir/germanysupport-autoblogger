"""
GermanySupport.de — Shared Configuration
==========================================
Single source of truth for categories and referral links.
All scripts (publish_article.py, optimize_articles.py,
translate_articles.py) import from here.

To update referral links or categories: edit ONLY this file.
All scripts pick up changes automatically on next run.
"""

from datetime import datetime

# ============================================================
#  📅  CURRENT YEAR — auto-detected, never hardcode
# ============================================================
CURRENT_YEAR = datetime.now().year

# ============================================================
#  📂  ALLOWED CATEGORIES
#  Keep in sync with your WordPress category list.
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
    # Extended categories
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
#  📌  REFERRAL LINKS
#
#  FORMAT: "Display Name": "https://germanysupport.de/go/slug"
#
#  REMOVED (no affiliation):
#    - Commerzbank
#    - American Express
#    - Metro Business Account
#    - Getsafe Haftpflicht
#    - Congstar Mobile
#
#  SPECIAL: TapTap Send includes promo code IQBAL12
#    → Users get €10 bonus when sending €50+
#    → This is reflected in the display name and
#      in the TAPTAP_PROMO dict below for use in articles
# ============================================================
REFERRAL_LINKS = {
    # GENERIC COMPARISON PORTALS
    "Tarifcheck":             "https://germanysupport.de/go/tarifcheck",
    "Check24":                "https://germanysupport.de/go/check24",
    "Verivox":                "https://germanysupport.de/go/verivox",
    # BANKING
    "N26 Bank":               "https://germanysupport.de/go/n26",
    "C24 Bank":               "https://germanysupport.de/go/c24",
    "Advanzia Mastercard":    "https://germanysupport.de/go/advanzia",
    "Credit Card Comparison": "https://germanysupport.de/go/credit-cards",
    "Trade Republic":         "https://germanysupport.de/go/trade-republic",
    "Scalable Capital":       "https://germanysupport.de/go/scalable-capital",
    "PayPal":                 "https://germanysupport.de/go/paypal",
    # INSURANCE
    "Liability Insurance":    "https://germanysupport.de/go/haftpflicht",
    "HUK24 Car Insurance":    "https://germanysupport.de/go/huk24",
    "Car Insurance Compare":  "https://germanysupport.de/go/car-insurance",
    "Legal Insurance":        "https://germanysupport.de/go/legal-insurance",
    # TAX & FINANCE
    "SteuerGo":               "https://germanysupport.de/go/steuergo",
    "WISO Steuer":            "https://germanysupport.de/go/wiso",
    # INTERNET & MOBILE
    "Verivox DSL":            "https://germanysupport.de/go/verivox-dsl",
    "DSL Check24":            "https://germanysupport.de/go/dsl-check24",
    "Klarmobil":              "https://germanysupport.de/go/klarmobil",
    "Check24 Mobile":         "https://germanysupport.de/go/check24-mobile",
    "Vodafone":               "https://germanysupport.de/go/vodafone",
    "Telekom":                "https://germanysupport.de/go/telekom",
    "Telekom Fiber":          "https://germanysupport.de/go/telekom-fiber",
    # UTILITIES
    "Electricity Provider":   "https://germanysupport.de/go/electricity",
    "Gas Provider":           "https://germanysupport.de/go/gas",
    # TRAVEL
    "Check24 Travel":         "https://germanysupport.de/go/travel",
    "Check24 Car Rental":     "https://germanysupport.de/go/car-rental",
    "Check24 Vacation":       "https://germanysupport.de/go/vacation",
    # MONEY TRANSFER
    "ACE Money Transfer":     "https://germanysupport.de/go/ace",
    # TapTap Send — promo code IQBAL12 gives €10 bonus when sending €50+
    "TapTap Send":            "https://germanysupport.de/go/taptap",
    # CASHBACK
    "Shoop Cashback":         "https://germanysupport.de/go/shoop",
    "iGraal Cashback":        "https://germanysupport.de/go/igraal",
    "PAYBACK":                "https://germanysupport.de/go/payback",
}

# ============================================================
#  💰  TAPTAP SEND PROMO — special handling
#  When embedding TapTap Send links, use this HTML snippet
#  to clearly show the promo code and bonus offer.
# ============================================================
TAPTAP_PROMO_HTML = (
    '<a href="https://germanysupport.de/go/taptap" '
    'target="_blank" rel="nofollow sponsored">'
    'TapTap Send</a> '
    '(use promo code <strong>IQBAL12</strong> when sending '
    '€50 or more to get a <strong>€10–€15 bonus</strong>)'
)

TAPTAP_PROMO_TEXT = (
    "TapTap Send — use promo code IQBAL12 when sending €50 or more "
    "to receive a €10–€15 bonus on your transfer."
)

# ============================================================
#  🔗  RELEVANCE MAP
#  Which referral links are relevant for which article topics.
#  Used by optimize_articles.py and publish_article.py to
#  only embed links that make sense for the article content.
# ============================================================
LINK_RELEVANCE = {
    "N26 Bank":               ["bank", "account", "banking", "girokonto", "finanz"],
    "C24 Bank":               ["bank", "account", "banking", "girokonto", "finanz"],
    "Advanzia Mastercard":    ["credit card", "mastercard", "kreditkarte"],
    "Credit Card Comparison": ["credit card", "kreditkarte", "card"],
    "Trade Republic":         ["invest", "stock", "etf", "broker", "trading", "aktien"],
    "Scalable Capital":       ["invest", "stock", "etf", "broker", "trading"],
    "PayPal":                 ["payment", "online shopping", "transfer", "paypal"],
    "Liability Insurance":    ["insurance", "haftpflicht", "liability", "versicherung"],
    "HUK24 Car Insurance":    ["car insurance", "kfz", "auto", "vehicle", "fahrzeug"],
    "Car Insurance Compare":  ["car insurance", "kfz", "auto", "vehicle"],
    "Legal Insurance":        ["legal", "rechtsschutz", "lawyer", "anwalt"],
    "SteuerGo":               ["tax", "steuer", "steuererklärung", "finanzamt"],
    "WISO Steuer":            ["tax", "steuer", "steuererklärung", "finanzamt"],
    "Verivox DSL":            ["internet", "dsl", "broadband", "provider"],
    "DSL Check24":            ["internet", "dsl", "broadband", "provider"],
    "Klarmobil":              ["mobile", "sim", "phone plan", "prepaid", "handy"],
    "Check24 Mobile":         ["mobile", "sim", "phone plan", "prepaid", "handy"],
    "Vodafone":               ["mobile", "sim", "phone", "internet", "network"],
    "Telekom":                ["mobile", "sim", "phone", "internet", "telekom"],
    "Telekom Fiber":          ["fiber", "glasfaser", "internet", "broadband"],
    "Electricity Provider":   ["electricity", "strom", "energy", "energie", "utility"],
    "Gas Provider":           ["gas", "heating", "heizung", "energie", "utility"],
    "Check24 Travel":         ["travel", "trip", "holiday", "flight", "reise"],
    "Check24 Car Rental":     ["car rental", "rent a car", "mietwagen", "driving"],
    "Check24 Vacation":       ["vacation", "holiday", "urlaub", "hotel", "travel"],
    "ACE Money Transfer":     ["money transfer", "send money", "remittance", "overseas"],
    "TapTap Send":            ["money transfer", "send money", "remittance", "overseas"],
    "Shoop Cashback":         ["cashback", "saving", "discount", "deals", "shopping"],
    "iGraal Cashback":        ["cashback", "saving", "discount", "deals", "shopping"],
    "PAYBACK":                ["cashback", "loyalty", "points", "reward", "shopping"],
    "Tarifcheck":             ["compare", "vergleich", "tariff", "plan", "provider"],
    "Check24":                ["compare", "vergleich", "insurance", "internet", "energy"],
    "Verivox":                ["compare", "vergleich", "energy", "internet", "gas"],
}


def get_relevant_links(title, content_text, min_links=2):
    """
    Return relevant affiliate links for an article based on its content.
    Always returns at least `min_links` links even for generic topics.
    Never includes removed/non-affiliated products.
    Handles TapTap Send with special promo code treatment.
    """
    combined = (title + " " + content_text).lower()
    relevant = {}

    for name, keywords in LINK_RELEVANCE.items():
        if name not in REFERRAL_LINKS:
            continue  # skip if removed from REFERRAL_LINKS
        if any(kw in combined for kw in keywords):
            relevant[name] = REFERRAL_LINKS[name]

    # Ensure minimum links for generic topics
    if len(relevant) < min_links:
        defaults = ["N26 Bank", "Shoop Cashback", "SteuerGo"]
        for d in defaults:
            if d not in relevant and d in REFERRAL_LINKS:
                relevant[d] = REFERRAL_LINKS[d]

    return relevant


def format_links_for_prompt(relevant_links):
    """
    Format referral links for inclusion in Claude prompts.
    TapTap Send gets special treatment with promo code info.
    """
    lines = []
    for name, url in relevant_links.items():
        if name == "TapTap Send":
            lines.append(
                f'- TapTap Send (promo code IQBAL12 — €10 bonus for €50+ transfers): {url}'
            )
        else:
            lines.append(f"- {name}: {url}")
    return "\n".join(lines)


def format_links_as_html(relevant_links):
    """
    Format referral links as ready-to-embed HTML <a> tags for Claude.
    TapTap Send gets the full promo code HTML.
    """
    lines = []
    for name, url in relevant_links.items():
        if name == "TapTap Send":
            lines.append(
                f'- TapTap Send with promo code: {TAPTAP_PROMO_HTML}'
            )
        else:
            lines.append(
                f'- {name}: <a href="{url}" target="_blank" '
                f'rel="nofollow sponsored">{name}</a>'
            )
    return "\n".join(lines)
