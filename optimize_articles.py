"""
GermanySupport.de — SEO Optimizer v9
======================================
Key fix: uses custom /wp-json/gs/v1/set-keyword endpoint
(registered via Code Snippets plugin) to reliably set Rank Math
focus keywords via update_post_meta — works on all Rank Math versions.

Requires: "Rank Math Keyword API" snippet active in Code Snippets plugin.

All v8 features retained plus:
  - Reliable keyword setting via custom endpoint
  - Better connection error handling with longer timeouts
  - Clearer per-article progress logging

Usage:
  python optimize_articles.py                  # all English articles
  python optimize_articles.py --limit 5        # first 5 (test)
  python optimize_articles.py --post-id 123    # single post
  python optimize_articles.py --force          # ignore last-updated date
"""

import os
import re
import json
import time
import base64
import sys
import argparse
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

import anthropic
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
#  🔑  CREDENTIALS
# ============================================================
WP_URL        = os.environ["WP_URL"].rstrip("/")
WP_USER       = os.environ["WP_USER"]
WP_APP_PASS   = os.environ["WP_APP_PASS"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]

# ============================================================
#  ⚙️  SETTINGS
# ============================================================
MIN_WORD_COUNT            = 1200
DELAY_BETWEEN             = 12
MAX_SLUG_LENGTH           = 60
SKIP_IF_NEWER_THAN_MONTHS = 4
CURRENT_YEAR              = datetime.now().year

# ============================================================
#  🔄  HTTP SESSION WITH RETRY & LONGER TIMEOUTS
# ============================================================

def build_session():
    session = requests.Session()
    retry   = Retry(
        total=5,
        backoff_factor=20,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    return session

SESSION = build_session()
TIMEOUT = 60  # seconds per request

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
    "Working Freelance",
]

# ============================================================
#  📌  REFERRAL LINKS — /go/ redirect format
# ============================================================
REFERRAL_LINKS = {
    "N26 Bank":               "https://germanysupport.de/go/n26",
    "C24 Bank":               "https://germanysupport.de/go/c24bank",
    "Commerzbank":            "https://germanysupport.de/go/commerzbank",
    "Advanzia Mastercard":    "https://germanysupport.de/go/advanzia",
    "American Express":       "https://germanysupport.de/go/amex",
    "Credit Card Comparison": "https://germanysupport.de/go/creditcard-compare",
    "Trade Republic":         "https://germanysupport.de/go/trade-republic",
    "Metro Business Account": "https://germanysupport.de/go/metro",
    "Liability Insurance":    "https://germanysupport.de/go/liability-insurance",
    "Getsafe Haftpflicht":    "https://germanysupport.de/go/getsafe",
    "HUK24 Car Insurance":    "https://germanysupport.de/go/huk24",
    "Car Insurance Compare":  "https://germanysupport.de/go/car-insurance-compare",
    "SteuerGo Tax Tool":      "https://germanysupport.de/go/steuergotax",
    "WISO Steuer Software":   "https://germanysupport.de/go/wisotax",
    "Verivox DSL Internet":   "https://germanysupport.de/go/verivox-dsl",
    "DSL Internet Check24":   "https://germanysupport.de/go/check24-dsl",
    "Klarmobil Mobile Plan":  "https://germanysupport.de/go/klarmobil",
    "Check24 Mobile Plans":   "https://germanysupport.de/go/check24-mobile",
    "Congstar Mobile":        "https://germanysupport.de/go/congstar",
    "Electricity Provider":   "https://germanysupport.de/go/electricity",
    "Gas Provider":           "https://germanysupport.de/go/gas",
    "Check24 Travel":         "https://germanysupport.de/go/check24-travel",
    "Check24 Car Rental":     "https://germanysupport.de/go/check24-carrental",
    "ACE Money Transfer":     "https://germanysupport.de/go/ace-money",
    "TapTap Send":            "https://germanysupport.de/go/taptap",
    "Shoop Cashback":         "https://germanysupport.de/go/shoop",
    "iGraal Cashback":        "https://germanysupport.de/go/igraal",
}

# ============================================================
#  🔧  AUTH & HTTP
# ============================================================

def build_auth_headers():
    credentials = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type":  "application/json",
    }

HEADERS = build_auth_headers()


def wp_get(url, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    r = SESSION.get(url, headers=HEADERS, **kwargs)
    r.raise_for_status()
    return r


def wp_post_req(url, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    r = SESSION.post(url, headers=HEADERS, **kwargs)
    if not r.ok:
        raise Exception(f"POST error {r.status_code}: {r.text[:300]}")
    return r


def wp_request(method, endpoint, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    url = f"{WP_URL}/wp-json/wp/v2/{endpoint}"
    r   = SESSION.request(method, url, headers=HEADERS, **kwargs)
    if not r.ok:
        raise Exception(f"WP API {r.status_code}: {r.text[:300]}")
    return r.json()


def strip_html(html):
    return re.sub(r"<[^>]+>", " ", html or "")


def word_count(text):
    return len(strip_html(text).split())


# ============================================================
#  📅  DATE HELPERS
# ============================================================

def parse_wp_date(date_str):
    try:
        return datetime.strptime(
            date_str, "%Y-%m-%dT%H:%M:%S"
        ).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def is_recently_updated(post, months=4):
    modified_str = post.get("modified_gmt", "") or post.get("modified", "")
    if not modified_str:
        return False
    modified = parse_wp_date(modified_str)
    if not modified:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    return modified > cutoff


# ============================================================
#  🎯  RANK MATH — CUSTOM ENDPOINT (reliable)
# ============================================================

def set_rank_math_keyword(post_id, focus_keyword, meta_title, meta_description):
    """
    Set Rank Math SEO data via our custom /wp-json/gs/v1/set-keyword endpoint.
    This calls update_post_meta directly — works on all Rank Math versions.
    Requires the 'Rank Math Keyword API' Code Snippet to be active.
    Falls back to the native Rank Math API if custom endpoint not available.
    """
    # Method 1: Custom endpoint (most reliable)
    try:
        r = wp_post_req(
            f"{WP_URL}/wp-json/gs/v1/set-keyword",
            json={
                "post_id":     post_id,
                "keyword":     focus_keyword,
                "title":       meta_title,
                "description": meta_description,
            },
        )
        if r.ok:
            data = r.json()
            if data.get("success"):
                print(f"  Rank Math: keyword set via custom endpoint ✓")
                return True
    except Exception as e:
        print(f"  Custom endpoint error: {e}")

    # Method 2: Native Rank Math REST API fallback
    try:
        r2 = wp_post_req(
            f"{WP_URL}/wp-json/rankmath/v1/updateMeta",
            json={
                "objectID":   post_id,
                "objectType": "post",
                "meta": {
                    "rank_math_focus_keyword": focus_keyword,
                    "rank_math_title":         meta_title,
                    "rank_math_description":   meta_description,
                },
            },
        )
        if r2.ok:
            print(f"  Rank Math: keyword set via native API ✓")
            return True
    except Exception as e:
        print(f"  Native API error: {e}")

    print(f"  Rank Math: both methods failed.")
    print(f"  → Set manually: '{focus_keyword}'")
    return False


# ============================================================
#  🔍  EDITOR DETECTION
# ============================================================

def detect_editor(post):
    meta      = post.get("meta", {})
    edit_mode = meta.get("_elementor_edit_mode", "")
    data      = meta.get("_elementor_data", "")
    if edit_mode == "builder":
        return "elementor"
    if data and data not in ("", "[]", None):
        return "elementor"
    return "gutenberg"


# ============================================================
#  🧩  ELEMENTOR HELPERS
# ============================================================

def extract_text_from_elementor(elementor_data_str):
    try:
        data = json.loads(elementor_data_str)
    except Exception:
        return ""
    texts = []

    def traverse(obj):
        if isinstance(obj, list):
            for item in obj:
                traverse(item)
        elif isinstance(obj, dict):
            wt       = obj.get("widgetType", "")
            settings = obj.get("settings", {})
            if wt in ("text-editor", "theme-post-content"):
                c = settings.get("editor", "") or settings.get("content", "")
                if c:
                    texts.append(strip_html(c))
            elif wt == "heading":
                t = settings.get("title", "")
                if t:
                    texts.append(strip_html(t))
            elif wt == "accordion":
                for item in settings.get("tabs", []):
                    texts.append(strip_html(item.get("tab_title", "")))
                    texts.append(strip_html(item.get("tab_content", "")))
            for key in ("elements", "children"):
                if key in obj:
                    traverse(obj[key])

    traverse(data)
    return " ".join(t for t in texts if t.strip())


def update_elementor_content(elementor_data_str, new_html):
    try:
        data = json.loads(elementor_data_str)
    except Exception:
        return elementor_data_str
    updated = [False]

    def traverse_update(obj):
        if isinstance(obj, list):
            for item in obj:
                traverse_update(item)
        elif isinstance(obj, dict):
            if obj.get("widgetType") == "text-editor" and not updated[0]:
                obj["settings"]["editor"] = new_html
                updated[0] = True
            for key in ("elements", "children"):
                if key in obj:
                    traverse_update(obj[key])

    traverse_update(data)
    return json.dumps(data, ensure_ascii=False)


def fetch_elementor_raw_data(post_id):
    r = wp_get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        params={"context": "edit", "_fields": "meta"},
    )
    return r.json().get("meta", {}).get("_elementor_data", "") or ""


def save_elementor_data(post_id, elementor_data_str):
    r = wp_post_req(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        json={"meta": {"_elementor_data": elementor_data_str}},
    )
    if not r.ok:
        raise Exception(f"Elementor save failed: {r.status_code}")


# ============================================================
#  🧹  ROBUST JSON PARSER
# ============================================================

def parse_claude_json(raw_text):
    text = raw_text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*",     "", text)
    text = re.sub(r"```$",        "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    fixed = fixed.replace('\u201c', '"').replace('\u201d', '"')
    fixed = fixed.replace('\u2018', "'").replace('\u2019', "'")
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    print("  JSON malformed — asking Claude to repair...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    repair = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "Fix this malformed JSON. Return ONLY valid JSON, "
                "no markdown, no explanation:\n\n" + text[:3000]
            ),
        }],
    )
    repaired = repair.content[0].text.strip()
    repaired = re.sub(r"^```json\s*", "", repaired)
    repaired = re.sub(r"```$",        "", repaired).strip()
    return json.loads(repaired)


# ============================================================
#  🔗  AFFILIATE LINK HELPERS
# ============================================================

def get_relevant_links(title, content_text):
    combined = (title + " " + content_text).lower()
    relevance_map = {
        "N26 Bank":               ["bank", "account", "banking", "girokonto"],
        "C24 Bank":               ["bank", "account", "banking", "girokonto"],
        "Commerzbank":            ["bank", "account", "banking", "girokonto"],
        "Advanzia Mastercard":    ["credit card", "mastercard", "kreditkarte"],
        "American Express":       ["credit card", "amex", "american express"],
        "Credit Card Comparison": ["credit card", "kreditkarte"],
        "Trade Republic":         ["invest", "stock", "etf", "broker", "trading"],
        "Metro Business Account": ["business", "freelanc", "self-employ"],
        "Liability Insurance":    ["insurance", "haftpflicht", "liability"],
        "Getsafe Haftpflicht":    ["insurance", "haftpflicht", "liability"],
        "HUK24 Car Insurance":    ["car insurance", "kfz", "auto"],
        "Car Insurance Compare":  ["car insurance", "kfz", "auto"],
        "SteuerGo Tax Tool":      ["tax", "steuer", "finanzamt"],
        "WISO Steuer Software":   ["tax", "steuer", "finanzamt"],
        "Verivox DSL Internet":   ["internet", "dsl", "broadband"],
        "DSL Internet Check24":   ["internet", "dsl", "broadband"],
        "Klarmobil Mobile Plan":  ["mobile", "sim", "phone plan", "prepaid"],
        "Check24 Mobile Plans":   ["mobile", "sim", "phone plan", "prepaid"],
        "Congstar Mobile":        ["mobile", "sim", "phone plan", "prepaid"],
        "Electricity Provider":   ["electricity", "strom", "energy", "utility"],
        "Gas Provider":           ["gas", "heating", "heizung", "utility"],
        "Check24 Travel":         ["travel", "trip", "holiday", "flight"],
        "Check24 Car Rental":     ["car rental", "rent a car", "mietwagen"],
        "ACE Money Transfer":     ["money transfer", "send money", "remittance"],
        "TapTap Send":            ["money transfer", "send money", "remittance"],
        "Shoop Cashback":         ["cashback", "saving", "discount", "deals"],
        "iGraal Cashback":        ["cashback", "saving", "discount", "deals"],
    }
    relevant = {
        name: REFERRAL_LINKS[name]
        for name, keywords in relevance_map.items()
        if any(kw in combined for kw in keywords)
    }
    if len(relevant) < 2:
        relevant["N26 Bank"]          = REFERRAL_LINKS["N26 Bank"]
        relevant["Shoop Cashback"]    = REFERRAL_LINKS["Shoop Cashback"]
        relevant["SteuerGo Tax Tool"] = REFERRAL_LINKS["SteuerGo Tax Tool"]
    return relevant


def verify_links(content_html, relevant_links):
    return [
        (name, url) for name, url in relevant_links.items()
        if url not in content_html
    ]


def inject_missing_links(content_html, missing_links, focus_keyword):
    if not missing_links:
        return content_html
    print(f"  Pass 3: injecting {len(missing_links)} missing links...")
    client    = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    links_str = "\n".join([f"- {name}: {url}" for name, url in missing_links])
    response  = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system="""
You are an HTML editor embedding affiliate links into article content.
- Find the most relevant sentence for each link
- Embed as: <a href="URL" target="_blank" rel="nofollow sponsored">descriptive text</a>
- Anchor text must be natural and descriptive
- Only embed where genuinely relevant
- Return the COMPLETE modified HTML — do not shorten or summarize
- Do not add any disclosure boxes
""",
        messages=[{
            "role": "user",
            "content": f"""
Add these affiliate links naturally into the article.

LINKS:
{links_str}

ARTICLE:
{content_html}

Return the COMPLETE article HTML with links embedded.
""",
        }],
    )
    result = response.content[0].text.strip()
    result = re.sub(r"^```html\s*", "", result)
    result = re.sub(r"^```\s*",     "", result)
    result = re.sub(r"```$",        "", result).strip()
    return result


# ============================================================
#  📥  FETCH POSTS
# ============================================================

def fetch_all_english_posts():
    posts = []
    page  = 1
    print("  Fetching English posts...")
    while True:
        r = wp_get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={
                "per_page":  20,
                "page":      page,
                "status":    "publish",
                "context":   "edit",
                "_fields":   (
                    "id,title,slug,content,excerpt,tags,"
                    "categories,link,lang,featured_media,"
                    "meta,modified_gmt"
                ),
            },
        )
        if r.status_code == 400:
            break
        batch = r.json()
        if not batch:
            break
        for post in batch:
            if post.get("lang") == "de" or "/de/" in post.get("link", ""):
                continue
            posts.append(post)
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total_pages} — {len(posts)} English posts...")
        if page >= total_pages:
            break
        page += 1
    return posts


def fetch_all_post_refs():
    refs = []
    page = 1
    while True:
        r = wp_get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={
                "per_page": 100,
                "page":     page,
                "status":   "publish",
                "_fields":  "id,title,link,lang",
            },
        )
        if r.status_code == 400:
            break
        batch = r.json()
        if not batch:
            break
        for post in batch:
            if post.get("lang") == "de" or "/de/" in post.get("link", ""):
                continue
            refs.append({
                "id":    post["id"],
                "title": post["title"]["rendered"],
                "url":   post["link"],
            })
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
    return refs


def fetch_single_post(post_id):
    r = wp_get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        params={"context": "edit"},
    )
    return r.json()


# ============================================================
#  🔗  INTERNAL LINKS
# ============================================================

def find_related_posts(current_id, current_title, all_refs, max_links=3):
    scored      = []
    title_words = set(re.findall(r'\b\w{4,}\b', current_title.lower()))
    for post in all_refs:
        if post["id"] == current_id:
            continue
        other_words = set(re.findall(r'\b\w{4,}\b', post["title"].lower()))
        if not title_words or not other_words:
            continue
        overlap = len(title_words & other_words) / len(title_words)
        sim     = SequenceMatcher(
            None, current_title.lower(), post["title"].lower()
        ).ratio()
        score = (overlap * 0.6) + (sim * 0.4)
        if score > 0.12:
            scored.append((score, post))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:max_links]]


def build_internal_links_html(related):
    if not related:
        return ""
    items = "".join([
        f'<li><a href="{p["url"]}">{p["title"]}</a></li>'
        for p in related
    ])
    return (
        '<div style="background:#f9f9f9;border:1px solid #e0e0e0;'
        'padding:16px;margin:24px 0;border-radius:4px;">'
        '<strong>Related Articles</strong>'
        f'<ul style="margin:8px 0 0;padding-left:20px;">{items}</ul>'
        '</div>'
    )


# ============================================================
#  📋  TABLE OF CONTENTS
# ============================================================

def inject_anchors(html):
    def add_anchor(m):
        text   = strip_html(m.group(1)).strip()
        anchor = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
        return f'<h2 id="{anchor}">{m.group(1)}</h2>'
    return re.sub(
        r'<h2[^>]*>(.*?)</h2>', add_anchor, html,
        flags=re.IGNORECASE | re.DOTALL
    )


def build_toc(html):
    headings = re.findall(
        r'<h2[^>]*>(.*?)</h2>', html,
        re.IGNORECASE | re.DOTALL
    )
    headings = [
        strip_html(h).strip() for h in headings
        if len(strip_html(h).strip()) > 3
    ]
    if len(headings) < 3:
        return ""
    items = ""
    for h in headings:
        anchor = re.sub(r'[^a-z0-9]+', '-', h.lower()).strip('-')
        items += f'<li><a href="#{anchor}">{h}</a></li>'
    return (
        '<div style="background:#f8f9fa;border:1px solid #dee2e6;'
        'padding:16px 20px;margin:0 0 24px;border-radius:4px;">'
        '<strong style="display:block;margin-bottom:8px;">Table of Contents</strong>'
        f'<ol style="margin:0;padding-left:20px;line-height:1.9;">{items}</ol>'
        '</div>'
    )


# ============================================================
#  🖼️  IMAGE ALT TEXT
# ============================================================

def update_image_alt(media_id, focus_keyword, title):
    if not media_id:
        return
    try:
        wp_post_req(
            f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
            json={"alt_text": f"{focus_keyword} — {title[:60]}"},
        )
        print(f"  Image alt text updated.")
    except Exception as e:
        print(f"  Image alt warning: {e}")


# ============================================================
#  📂  CATEGORIES & TAGS
# ============================================================

def fetch_wp_categories():
    cat_map = {}
    page    = 1
    while True:
        r = wp_get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            params={"per_page": 100, "page": page, "_fields": "id,name"},
        )
        if r.status_code == 400:
            break
        for cat in r.json():
            cat_map[cat["name"].lower()] = cat["id"]
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
    return cat_map


def resolve_category_ids(chosen, wp_cat_map):
    ids = []
    for name in chosen:
        nl = name.lower()
        if nl in wp_cat_map:
            ids.append(wp_cat_map[nl])
            continue
        best_score, best_key = 0, None
        for k in wp_cat_map:
            s = SequenceMatcher(None, nl, k).ratio()
            if s > best_score:
                best_score, best_key = s, k
        if best_key and best_score >= 0.60:
            ids.append(wp_cat_map[best_key])
        else:
            print(f"    WARNING: no match for '{name}'")
    if not ids:
        fb = "living in germany"
        if fb in wp_cat_map:
            ids.append(wp_cat_map[fb])
    return ids


def sync_tags(tag_names):
    ids = []
    for name in tag_names:
        try:
            t = wp_request("POST", "tags", json={"name": name})
            ids.append(t["id"])
        except Exception:
            s = wp_get(
                f"{WP_URL}/wp-json/wp/v2/tags",
                params={"search": name, "per_page": 1},
            ).json()
            if s:
                ids.append(s[0]["id"])
    return ids


# ============================================================
#  🤖  CLAUDE — TWO-PASS REWRITE
# ============================================================

def claude_call(system_prompt, user_prompt, max_tokens=4096):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    r = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return r.content[0].text.strip()


def rewrite_pass1(title, current_text, wc, is_short, related, relevant_links):
    links_str   = "\n".join([
        f'- {name}: <a href="{url}" target="_blank" rel="nofollow sponsored">{name}</a>'
        for name, url in relevant_links.items()
    ])
    cats_str    = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)
    related_str = ""
    if related:
        related_str = "\n\nAlso embed these INTERNAL links naturally:\n"
        related_str += "\n".join([
            f'- <a href="{p["url"]}">{p["title"]}</a>'
            for p in related
        ])

    target = max(MIN_WORD_COUNT, wc)
    length = (
        f"EXPAND to at least {MIN_WORD_COUNT} words — currently only ~{wc}."
        if is_short else
        f"Write approximately {target}+ words. Do NOT shorten."
    )

    system = f"""
You are an expert SEO writer for an expat guide website about Germany.
Optimizing for Rank Math SEO. Current year: {CURRENT_YEAR}.

RANK MATH REQUIREMENTS (all mandatory):
1. Focus keyword in the VERY FIRST sentence
2. Focus keyword near the start of the SEO title
3. Focus keyword in meta description (first 10 words)
4. Focus keyword in at least 2 H2 headings
5. Keyword density ~1% (use every 100-150 words)
6. Slug under {MAX_SLUG_LENGTH} chars, contains focus keyword

CONTENT:
- {length}
- Update ALL information to {CURRENT_YEAR}
- Replace outdated year references with {CURRENT_YEAR}
- Clear H2/H3 structure throughout
- Do NOT add FAQ (separate pass)
- Do NOT add any affiliate disclosure box

AFFILIATE LINKS — MANDATORY — ALL MUST APPEAR IN CONTENT:
{links_str}{related_str}

JSON RULES:
- Escape all quotes in content: \\" not "
- No smart/curly quotes
- Complete valid JSON
- Slug max {MAX_SLUG_LENGTH} chars

CATEGORIES — 1-2 only, exact names:
{cats_str}

Return ONLY this JSON:
{{
  "title": "Focus Keyword: Title {CURRENT_YEAR}",
  "slug": "focus-keyword-slug",
  "meta_title": "Focus Keyword | GermanySupport.de",
  "meta_description": "Focus keyword first. 150-155 chars exactly.",
  "focus_keyword": "exact focus keyword phrase",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "categories": ["Category Name"],
  "content": "Complete HTML — all affiliate links, NO FAQ, NO disclosure"
}}
"""

    user = f"""
Rewrite for Rank Math SEO. Year: {CURRENT_YEAR}.

TITLE: {title}
WORDS: ~{wc} → target {target}+

CONTENT:
{current_text}

ALL affiliate links above are MANDATORY.
Return COMPLETE JSON only.
"""

    return parse_claude_json(claude_call(system, user, max_tokens=4096))


def rewrite_pass2_faq(title, focus_keyword, content_summary):
    system = f"""
Write FAQ sections for expat guides about Germany ({CURRENT_YEAR}).
- Start: <h2 id="faq">Frequently Asked Questions</h2>
- 5-6 questions as <h3>Question?</h3>
- Answers as <p>2-4 sentences, accurate for {CURRENT_YEAR}.</p>
- Include focus keyword in 1-2 questions
- Return ONLY HTML, no JSON, no explanation
"""
    user = f"""
Write FAQ for:
TITLE: {title}
KEYWORD: {focus_keyword}
SUMMARY: {content_summary[:1000]}
Return ONLY the FAQ HTML.
"""
    return claude_call(system, user, max_tokens=1200)


# ============================================================
#  📝  ASSEMBLE FINAL CONTENT
# ============================================================

def assemble_content(optimized, related):
    content = inject_anchors(optimized["content"])

    first_p = re.search(r'(<p>.*?</p>)', content, re.DOTALL | re.IGNORECASE)
    toc     = build_toc(content)
    if first_p and toc:
        content = (
            content[:first_p.end()] + "\n" + toc + "\n" + content[first_p.end():]
        )
    elif toc:
        content = toc + "\n" + content

    il_html = build_internal_links_html(related)
    if il_html:
        faq = re.search(
            r'(<h2[^>]*>.*?[Ff][Aa][Qq].*?</h2>)',
            content, re.DOTALL | re.IGNORECASE
        )
        if faq:
            content = (
                content[:faq.start()] + il_html + "\n" + content[faq.start():]
            )
        else:
            content += "\n" + il_html

    return content


# ============================================================
#  📤  UPDATE POSTS
# ============================================================

def update_wp_post(post_id, optimized, final_content, cat_ids, tag_ids):
    return wp_request(
        "POST",
        f"posts/{post_id}",
        json={
            "title":      optimized["title"],
            "slug":       optimized["slug"][:MAX_SLUG_LENGTH],
            "content":    final_content,
            "excerpt":    optimized["meta_description"],
            "tags":       tag_ids,
            "categories": cat_ids,
        },
    )


def process_elementor(post, optimized, final_content, cat_ids, tag_ids):
    post_id = post["id"]
    raw_el  = fetch_elementor_raw_data(post_id)
    if raw_el and raw_el not in ("", "[]"):
        updated_el = update_elementor_content(raw_el, final_content)
        save_elementor_data(post_id, updated_el)
        print(f"  Elementor data updated.")
    return update_wp_post(post_id, optimized, final_content, cat_ids, tag_ids)


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport SEO Optimizer v9")
    parser.add_argument("--limit",   type=int,  default=None)
    parser.add_argument("--post-id", type=int,  default=None)
    parser.add_argument("--force",   action="store_true",
                        help="Rewrite all articles regardless of modified date")
    args = parser.parse_args()

    print("=" * 62)
    print(f"  GermanySupport.de — SEO Optimizer v9 ({CURRENT_YEAR})")
    print("  Custom keyword endpoint | Two-pass | Gutenberg + Elementor")
    print("=" * 62)
    print(f"  Year: {CURRENT_YEAR} (auto-detected)")

    # 1. Verify custom keyword endpoint is working
    print("\n[1] Checking custom Rank Math keyword endpoint...")
    try:
        test = wp_post_req(
            f"{WP_URL}/wp-json/gs/v1/set-keyword",
            json={"post_id": 0, "keyword": "test"},
        )
        # Expects a 400 (missing post_id validation) or 200 — either means endpoint exists
        print("    Custom endpoint: available ✓")
        custom_endpoint_ok = True
    except Exception as e:
        err = str(e)
        if "400" in err or "missing" in err.lower():
            print("    Custom endpoint: available ✓")
            custom_endpoint_ok = True
        else:
            print(f"    Custom endpoint: NOT found — {err[:80]}")
            print("    → Add the Code Snippet first, then re-run")
            print("    → Falling back to native Rank Math API")
            custom_endpoint_ok = False

    # 2. Categories
    print("\n[2] Fetching categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 3. Post refs
    print("\n[3] Fetching post list for internal linking...")
    all_refs = fetch_all_post_refs()
    print(f"    Found {len(all_refs)} English posts.")

    # 4. Fetch posts
    print("\n[4] Fetching posts to optimize...")
    if args.post_id:
        posts = [fetch_single_post(args.post_id)]
        print(f"    Single post: ID {args.post_id}")
    else:
        posts = fetch_all_english_posts()
        if args.limit:
            posts = posts[:args.limit]
        print(f"    Found {len(posts)} English posts.")

    if not posts:
        print("    No posts found.")
        return

    # 5. Filter recently updated
    if not args.force and not args.post_id:
        before = len(posts)
        posts  = [p for p in posts if not is_recently_updated(
            p, SKIP_IF_NEWER_THAN_MONTHS
        )]
        print(f"    Skipping {before - len(posts)} recently updated posts.")
        print(f"    Will optimize {len(posts)} articles.")

    if not posts:
        print("\n    All articles recently updated. Use --force to override.")
        return

    # 6. Optimize loop
    print(f"\n[5] Optimizing {len(posts)} articles...")
    print("=" * 62)

    results = {"success": [], "failed": []}
    total   = len(posts)

    for i, post in enumerate(posts, 1):
        post_id  = post["id"]
        title    = post["title"]["rendered"]
        media_id = post.get("featured_media") or None
        editor   = detect_editor(post)
        modified = post.get("modified_gmt", "unknown")[:10]

        # Get content
        if editor == "elementor":
            raw_el       = fetch_elementor_raw_data(post_id)
            current_text = extract_text_from_elementor(raw_el) if raw_el else ""
            if not current_text:
                current_text = strip_html(
                    post.get("content", {}).get("rendered", "")
                )
        else:
            current_text = strip_html(
                post.get("content", {}).get("rendered", "")
            )

        wc       = len(current_text.split())
        is_short = wc < MIN_WORD_COUNT

        print(f"\n[{i}/{total}] Post {post_id} [{editor.upper()}] modified:{modified}")
        print(f"  Title : {title[:65]}")
        print(f"  Words : {wc} {'— SHORT' if is_short else '— OK'}")

        try:
            # Relevant links + related posts
            relevant_links = get_relevant_links(title, current_text)
            related        = find_related_posts(post_id, title, all_refs)
            print(f"  Links : {len(relevant_links)} affiliate | {len(related)} internal")

            # Pass 1: article body
            print("  Pass 1: rewriting...")
            optimized = rewrite_pass1(
                title, current_text, wc, is_short, related, relevant_links
            )

            # Verify + inject missing links
            missing = verify_links(optimized["content"], relevant_links)
            print(f"  Links : {len(relevant_links)-len(missing)}/{len(relevant_links)} present")
            if missing:
                optimized["content"] = inject_missing_links(
                    optimized["content"], missing, optimized["focus_keyword"]
                )
                still = verify_links(optimized["content"], relevant_links)
                print(f"  Links : {len(relevant_links)-len(still)}/{len(relevant_links)} after injection")

            # Pass 2: FAQ
            print("  Pass 2: FAQ...")
            faq_html = rewrite_pass2_faq(
                optimized["title"],
                optimized["focus_keyword"],
                strip_html(optimized["content"])[:2000],
            )
            optimized["content"] += "\n" + faq_html

            new_wc = word_count(optimized["content"])
            print(f"  KW    : {optimized['focus_keyword']}")
            print(f"  Meta  : {len(optimized['meta_description'])} chars")
            print(f"  Words : {wc} → {new_wc}")

            # Assemble
            final = assemble_content(optimized, related)

            # Cats + tags
            cat_ids = resolve_category_ids(optimized["categories"], wp_cat_map)
            tag_ids = sync_tags(optimized["tags"])

            # Update post
            if editor == "elementor":
                updated = process_elementor(post, optimized, final, cat_ids, tag_ids)
            else:
                updated = update_wp_post(post_id, optimized, final, cat_ids, tag_ids)

            url = updated["link"]
            print(f"  Saved : {url}")

            # Set Rank Math keyword
            meta_title = optimized.get(
                "meta_title", f"{optimized['title']} | GermanySupport.de"
            )
            rm_ok = set_rank_math_keyword(
                post_id,
                optimized["focus_keyword"],
                meta_title,
                optimized["meta_description"],
            )

            # Image alt
            update_image_alt(media_id, optimized["focus_keyword"],
                             optimized["title"])

            results["success"].append({
                "id":        post_id,
                "title":     optimized["title"],
                "url":       url,
                "old_words": wc,
                "new_words": new_wc,
                "keyword":   optimized["focus_keyword"],
                "editor":    editor,
                "rm_ok":     rm_ok,
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            results["failed"].append({
                "id": post_id, "title": title, "error": str(e)
            })

        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s...")
            time.sleep(DELAY_BETWEEN)

    # 7. Summary
    print("\n" + "=" * 62)
    print(f"  COMPLETE — {CURRENT_YEAR}")
    print("=" * 62)
    rm_count = len([r for r in results["success"] if r["rm_ok"]])
    print(f"  Year used  : {CURRENT_YEAR}")
    print(f"  Total      : {total}")
    print(f"  Success    : {len(results['success'])}")
    print(f"  Keyword set: {rm_count}/{len(results['success'])}")
    print(f"  Failed     : {len(results['failed'])}")

    if results["success"]:
        print("\n  Updated articles:")
        for r in results["success"]:
            rm = "✓ KW" if r["rm_ok"] else "✗ KW manual"
            ed = r["editor"][0].upper()
            print(f"  [{ed}][{r['id']}] {r['title'][:48]} [{rm}]")
            print(f"         {r['old_words']}w → {r['new_words']}w | {r['keyword']}")
            print(f"         {r['url']}")

    need_rm = [r for r in results["success"] if not r["rm_ok"]]
    if need_rm:
        print("\n" + "=" * 62)
        print("  SET FOCUS KEYWORDS MANUALLY IN RANK MATH:")
        print("  WP editor → Rank Math panel → Focus Keyword field")
        print("=" * 62)
        for r in need_rm:
            print(f"  [{r['id']}] Keyword: {r['keyword']}")
            print(f"         {r['url']}")

    if results["failed"]:
        print("\n  Failed (run again to retry):")
        for r in results["failed"]:
            print(f"  [{r['id']}] {r['title'][:55]}")
            print(f"         {r['error'][:100]}")

    print("=" * 62)

    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
