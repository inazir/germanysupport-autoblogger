"""
GermanySupport.de — SEO Optimizer v5
======================================
Handles BOTH Gutenberg and Elementor articles in one run.

Gutenberg posts:
  - Content read/written via standard post_content field
  - TOC, internal links, disclosure injected directly
  - Full rewrite by Claude

Elementor posts:
  - Content extracted from _elementor_data JSON blob
  - Text nodes updated with Claude-rewritten content
  - Elementor data saved back via REST API
  - SEO fields updated via Rank Math API

Both post types:
  - Rank Math focus keyword, title, description via /rankmath/v1/updateMeta
  - Featured image alt text updated
  - Tags and categories updated
  - Affiliate disclosure added
  - Internal links added
  - FAQ section added
  - Min 1200 words enforced

Usage:
  python optimize_articles.py                  # all English articles
  python optimize_articles.py --limit 5        # first 5 (test)
  python optimize_articles.py --post-id 123    # single post
"""

import os
import re
import json
import time
import base64
import sys
import argparse
from difflib import SequenceMatcher

import anthropic
import requests

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
MIN_WORD_COUNT  = 1200
DELAY_BETWEEN   = 10
CURRENT_YEAR    = 2025
MAX_SLUG_LENGTH = 60

# ============================================================
#  📢  AFFILIATE DISCLOSURE
# ============================================================
AFFILIATE_DISCLOSURE = (
    '<div style="background:#f0f7ff;border-left:4px solid #0073aa;'
    'padding:12px 16px;margin-bottom:24px;font-size:14px;'
    'line-height:1.6;border-radius:0 4px 4px 0;">'
    '<strong>Affiliate Disclosure:</strong> This article contains '
    'affiliate links. If you click a link and make a purchase or sign up, '
    'we may earn a small commission at no extra cost to you. We only '
    'recommend services genuinely useful for expats in Germany. '
    '<a href="/affiliate-disclosure/" style="color:#0073aa;">'
    'Read our full disclosure.</a></div>'
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
    "Working Freelance",
]

# ============================================================
#  📌  AFFILIATE / REFERRAL LINKS
# ============================================================
REFERRAL_LINKS = {
    "N26 Bank":               "https://bit.ly/3IXPFSh",
    "C24 Bank":               "https://bit.ly/3EED0Uc",
    "Commerzbank":            "https://bit.ly/cmrzbnk",
    "Advanzia Mastercard":    "https://bit.ly/4hKu4ul",
    "American Express":       "https://bit.ly/3wfHv0e",
    "Credit Card Comparison": "https://bit.ly/41xi8Ht",
    "Trade Republic":         "https://bit.ly/3Z5B13n",
    "Metro Business":         "https://bit.ly/3MnUiFV",
    "Liability Insurance":    "https://bit.ly/3ik93KM",
    "Getsafe Haftpflicht":    "https://bit.ly/3IBfR1l",
    "HUK24 Car Insurance":    "https://bit.ly/3tveWdm",
    "Car Insurance Compare":  "https://bit.ly/3IXJxXD",
    "SteuerGo":               "https://bit.ly/3XDNBW8",
    "WISO Steuer":            "https://bit.ly/3NLm1BE",
    "Verivox DSL":            "https://bit.ly/474daFa",
    "DSL Check24":            "https://bit.ly/3MFz9WH",
    "Klarmobil":              "https://bit.ly/4paMQ2e",
    "Check24 Mobile":         "https://bit.ly/3BVAAiI",
    "Congstar Mobile":        "https://bit.ly/3iVS0mb",
    "Electricity Provider":   "https://bit.ly/chk24strm",
    "Gas Provider":           "https://bit.ly/gasbgg",
    "Check24 Travel":         "https://bit.ly/bgstrip",
    "Check24 Car Rental":     "https://bit.ly/mtwgn",
    "ACE Money Transfer":     "https://bit.ly/3qq18Ab",
    "TapTap Send":            "https://bit.ly/3qj6JYG",
    "Shoop Cashback":         "https://bit.ly/3r3tW1p",
    "iGraal Cashback":        "https://bit.ly/38lWA7P",
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


def wp_request(method, endpoint, **kwargs):
    url = f"{WP_URL}/wp-json/wp/v2/{endpoint}"
    r   = requests.request(method, url, headers=HEADERS, **kwargs)
    if not r.ok:
        raise Exception(f"WP API error {r.status_code}: {r.text[:400]}")
    return r.json()


def strip_html(html):
    return re.sub(r"<[^>]+>", " ", html or "")


def word_count(text):
    return len(strip_html(text).split())


# ============================================================
#  🔍  EDITOR DETECTION
# ============================================================

def detect_editor(post):
    """
    Returns 'elementor' or 'gutenberg'.
    Checks _elementor_edit_mode meta and elementor data.
    """
    meta      = post.get("meta", {})
    edit_mode = meta.get("_elementor_edit_mode", "")
    data      = meta.get("_elementor_data", "")

    if edit_mode == "builder":
        return "elementor"
    if data and data not in ("", "[]", None):
        return "elementor"
    # Also check rendered content — Elementor posts have very little
    # in post_content but lots of shortcodes or empty content
    content = post.get("content", {}).get("rendered", "")
    if word_count(content) < 100 and edit_mode:
        return "elementor"
    return "gutenberg"


# ============================================================
#  🧩  ELEMENTOR DATA HELPERS
# ============================================================

def extract_text_from_elementor(elementor_data_str):
    """
    Parse Elementor JSON and extract all visible text content.
    Elementor stores content in nested widget objects.
    Returns plain text string of all content.
    """
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
            # Text widget types
            widget_type = obj.get("widgetType", "")
            settings    = obj.get("settings", {})

            if widget_type in ("text-editor", "theme-post-content"):
                content = settings.get("editor", "") or settings.get("content", "")
                if content:
                    texts.append(strip_html(content))

            elif widget_type == "heading":
                title = settings.get("title", "")
                if title:
                    texts.append(strip_html(title))

            elif widget_type == "accordion":
                items = settings.get("tabs", [])
                for item in items:
                    texts.append(strip_html(item.get("tab_title", "")))
                    texts.append(strip_html(item.get("tab_content", "")))

            # Recurse into elements/children
            for key in ("elements", "children"):
                if key in obj:
                    traverse(obj[key])

    traverse(data)
    return " ".join(t for t in texts if t.strip())


def update_elementor_content(elementor_data_str, new_content_html):
    """
    Replace the main text content in Elementor data with new HTML.
    Finds the first text-editor widget and replaces its content.
    Also updates heading widgets with focus keyword.
    Returns updated Elementor JSON string.
    """
    try:
        data = json.loads(elementor_data_str)
    except Exception:
        return elementor_data_str

    updated    = [False]  # Use list to allow mutation in nested function
    paragraphs = re.split(r'<h[23][^>]*>|</h[23]>', new_content_html)

    def traverse_update(obj):
        if isinstance(obj, list):
            for item in obj:
                traverse_update(item)
        elif isinstance(obj, dict):
            widget_type = obj.get("widgetType", "")
            settings    = obj.get("settings", {})

            # Update the first text-editor widget with full new content
            if widget_type == "text-editor" and not updated[0]:
                obj["settings"]["editor"] = new_content_html
                updated[0] = True

            # Recurse
            for key in ("elements", "children"):
                if key in obj:
                    traverse_update(obj[key])

    traverse_update(data)
    return json.dumps(data, ensure_ascii=False)


def fetch_elementor_raw_data(post_id):
    """
    Fetch the raw _elementor_data meta field using context=edit.
    Returns the raw JSON string or empty string.
    """
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        params={"context": "edit", "_fields": "meta"},
    )
    if r.ok:
        meta = r.json().get("meta", {})
        return meta.get("_elementor_data", "") or ""
    return ""


def save_elementor_data(post_id, elementor_data_str):
    """Save updated Elementor data back to the post."""
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        json={"meta": {"_elementor_data": elementor_data_str}},
    )
    if not r.ok:
        raise Exception(
            f"Failed to save Elementor data: {r.status_code} {r.text[:200]}"
        )
    return r.json()


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
                "no markdown fences, no explanation:\n\n" + text[:3000]
            ),
        }],
    )
    repaired = repair.content[0].text.strip()
    repaired = re.sub(r"^```json\s*", "", repaired)
    repaired = re.sub(r"```$",        "", repaired).strip()
    return json.loads(repaired)


# ============================================================
#  🎯  RANK MATH NATIVE API
# ============================================================

def update_rank_math_seo(post_id, focus_keyword, meta_title, meta_description):
    """Update Rank Math SEO data via its native REST endpoint."""
    try:
        # Try JSON format first
        r = requests.post(
            f"{WP_URL}/wp-json/rankmath/v1/updateMeta",
            headers=HEADERS,
            json={
                "objectID":   post_id,
                "objectType": "post",
                "meta": {
                    "rank_math_focus_keyword": focus_keyword,
                    "rank_math_title":         meta_title,
                    "rank_math_description":   meta_description,
                    "rank_math_robots":        ["index", "follow"],
                },
            },
        )
        if r.ok:
            print(f"  Rank Math: updated via native API.")
            return True

        # Try form-encoded format
        form_headers = dict(HEADERS)
        form_headers["Content-Type"] = "application/x-www-form-urlencoded"
        r2 = requests.post(
            f"{WP_URL}/wp-json/rankmath/v1/updateMeta",
            headers=form_headers,
            data={
                "objectID":                post_id,
                "objectType":              "post",
                "rank_math_focus_keyword": focus_keyword,
                "rank_math_title":         meta_title,
                "rank_math_description":   meta_description,
            },
        )
        if r2.ok:
            print(f"  Rank Math: updated via form data.")
            return True

        print(f"  Rank Math API failed: {r.status_code} — "
              f"set keyword manually: '{focus_keyword}'")
        return False

    except Exception as e:
        print(f"  Rank Math API error: {e}")
        return False


# ============================================================
#  📥  FETCH POSTS
# ============================================================

def fetch_all_english_posts():
    posts = []
    page  = 1
    print("  Fetching English posts...")
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={
                "per_page": 20,
                "page":     page,
                "status":   "publish",
                "context":  "edit",
                "_fields":  (
                    "id,title,slug,content,excerpt,tags,"
                    "categories,link,lang,featured_media,meta"
                ),
            },
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
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
    refs  = []
    page  = 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={
                "per_page": 100,
                "page":     page,
                "status":   "publish",
                "_fields":  "id,title,link,lang",
            },
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
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
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        params={"context": "edit"},
    )
    r.raise_for_status()
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
    headings = [strip_html(h).strip() for h in headings if len(strip_html(h).strip()) > 3]
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
        requests.post(
            f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
            headers=HEADERS,
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
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            headers=HEADERS,
            params={"per_page": 100, "page": page, "_fields": "id,name"},
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
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
            s = requests.get(
                f"{WP_URL}/wp-json/wp/v2/tags",
                headers=HEADERS,
                params={"search": name, "per_page": 1},
            ).json()
            if s:
                ids.append(s[0]["id"])
    return ids


# ============================================================
#  🤖  CLAUDE REWRITE
# ============================================================

def rewrite_article(title, current_text, wc, is_short, related, editor_type):
    client    = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    links_str = "\n".join([f"- {k}: {v}" for k, v in REFERRAL_LINKS.items()])
    cats_str  = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    related_str = ""
    if related:
        related_str = "\n\nEmbed these internal links naturally in the body:\n"
        related_str += "\n".join([
            f'- <a href="{p["url"]}">{p["title"]}</a>'
            for p in related
        ])

    length_note = (
        f"EXPAND to at least {MIN_WORD_COUNT} words — current is only ~{wc}."
        if is_short else
        f"Keep or increase current ~{wc} word length."
    )

    system_prompt = f"""
You are an expert SEO writer for an expat guide site about Germany.
Optimizing specifically for Rank Math SEO plugin. Today is {CURRENT_YEAR}.

RANK MATH REQUIREMENTS (critical — all must be met):
1. Focus keyword in the VERY FIRST sentence of the article
2. Focus keyword in the SEO title (near the start)
3. Focus keyword in meta description (first 10 words)
4. Focus keyword in at least 2 H2 headings exactly
5. Keyword density ~1% (use every 100-150 words naturally)
6. Slug: contains focus keyword, under {MAX_SLUG_LENGTH} chars
7. FAQ section at the end: 5-6 questions with detailed answers

CONTENT RULES:
- {length_note}
- Update all information to {CURRENT_YEAR}
- H2 and H3 structure throughout
- Affiliate links: <a href="URL" target="_blank" rel="nofollow sponsored">text</a>
- Only embed affiliate links where directly relevant{related_str}

JSON OUTPUT RULES (strict):
- Escape ALL quotes in content field: \\" not "
- No smart/curly quotes
- Valid complete JSON only
- Slug max {MAX_SLUG_LENGTH} chars, lowercase, hyphens only

CATEGORIES — 1-2 only, exact names:
{cats_str}

Return ONLY this JSON:
{{
  "title": "Focus Keyword: Rest of Title",
  "slug": "focus-keyword-slug",
  "meta_title": "Focus Keyword | GermanySupport.de",
  "meta_description": "Focus keyword first. Exactly 150-155 chars.",
  "focus_keyword": "exact focus keyword phrase",
  "tags": ["tag1", "tag2", "tag3"],
  "categories": ["Category Name"],
  "content": "Full HTML with H2/H3 structure, FAQ at end, escaped quotes"
}}
"""

    user_prompt = f"""
Rewrite and optimize this article for Rank Math SEO.

TITLE: {title}
EDITOR: {editor_type}
WORDS: ~{wc}

CURRENT CONTENT:
{current_text[:5000]}

AFFILIATE LINKS (embed where relevant):
{links_str}

Return ONLY the JSON. Escape all quotes inside content.
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return parse_claude_json(response.content[0].text)


# ============================================================
#  📝  ASSEMBLE GUTENBERG CONTENT
# ============================================================

def assemble_gutenberg_content(optimized, related):
    content = optimized["content"]
    content = inject_anchors(content)

    # TOC after first paragraph
    first_p = re.search(r'(<p>.*?</p>)', content, re.DOTALL | re.IGNORECASE)
    toc     = build_toc(content)
    if first_p and toc:
        content = (
            content[:first_p.end()]
            + "\n" + toc + "\n"
            + content[first_p.end():]
        )
    elif toc:
        content = toc + "\n" + content

    # Internal links before FAQ
    il_html = build_internal_links_html(related)
    if il_html:
        faq = re.search(
            r'(<h2[^>]*>.*?[Ff][Aa][Qq].*?</h2>)',
            content, re.DOTALL | re.IGNORECASE
        )
        if faq:
            content = (
                content[:faq.start()]
                + il_html + "\n"
                + content[faq.start():]
            )
        else:
            content += "\n" + il_html

    return AFFILIATE_DISCLOSURE + "\n" + content


# ============================================================
#  🚀  PROCESS GUTENBERG POST
# ============================================================

def process_gutenberg(post, optimized, related, cat_ids, tag_ids):
    """Update a standard Gutenberg post."""
    final = assemble_gutenberg_content(optimized, related)
    updated = wp_request(
        "POST",
        f"posts/{post['id']}",
        json={
            "title":      optimized["title"],
            "slug":       optimized["slug"][:MAX_SLUG_LENGTH],
            "content":    final,
            "excerpt":    optimized["meta_description"],
            "tags":       tag_ids,
            "categories": cat_ids,
        },
    )
    return updated["link"]


# ============================================================
#  ⚡  PROCESS ELEMENTOR POST
# ============================================================

def process_elementor(post, optimized, related, cat_ids, tag_ids):
    """
    Update an Elementor post:
    1. Fetch raw Elementor JSON
    2. Replace main text content with Claude's rewrite
    3. Also update post_content for SEO crawlers
    4. Save both
    """
    post_id = post["id"]

    # Fetch raw Elementor data
    print(f"  Fetching Elementor data...")
    raw_elementor = fetch_elementor_raw_data(post_id)

    # Build final content to inject
    final_content = assemble_gutenberg_content(optimized, related)

    if raw_elementor and raw_elementor not in ("", "[]"):
        # Update Elementor JSON with new content
        updated_elementor = update_elementor_content(raw_elementor, final_content)
        save_elementor_data(post_id, updated_elementor)
        print(f"  Elementor data updated.")
    else:
        print(f"  No Elementor data found — updating post_content only.")

    # Always update post_content too (used by SEO crawlers and Rank Math)
    updated = wp_request(
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
    return updated["link"]


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport SEO Optimizer v5")
    parser.add_argument("--limit",   type=int, default=None)
    parser.add_argument("--post-id", type=int, default=None)
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — SEO Optimizer v5")
    print("  Supports Gutenberg + Elementor")
    print("=" * 62)

    # 1. Check Rank Math API
    print("\n[1] Checking Rank Math API...")
    rm_check = requests.get(f"{WP_URL}/wp-json/rankmath/v1/", headers=HEADERS)
    if rm_check.ok:
        print("    Rank Math REST API: available ✓")
    else:
        print(f"    Rank Math REST API: {rm_check.status_code} "
              f"— will print manual keyword list at end")

    # 2. Fetch categories
    print("\n[2] Fetching categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 3. Fetch post refs for internal linking
    print("\n[3] Fetching post list for internal linking...")
    all_refs = fetch_all_post_refs()
    print(f"    Found {len(all_refs)} English posts.")

    # 4. Fetch posts to optimize
    print("\n[4] Fetching posts to optimize...")
    if args.post_id:
        posts = [fetch_single_post(args.post_id)]
        print(f"    Single post: ID {args.post_id}")
    else:
        posts = fetch_all_english_posts()
        if args.limit:
            posts = posts[:args.limit]
        print(f"    Will process {len(posts)} articles.")

    if not posts:
        print("    No posts found.")
        return

    # 5. Optimize loop
    print(f"\n[5] Optimizing...")
    print("=" * 62)

    results = {"success": [], "failed": []}
    total   = len(posts)

    for i, post in enumerate(posts, 1):
        post_id   = post["id"]
        title     = post["title"]["rendered"]
        media_id  = post.get("featured_media") or None
        editor    = detect_editor(post)

        # Get content — for Elementor, extract from elementor_data
        if editor == "elementor":
            raw_el = fetch_elementor_raw_data(post_id)
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

        print(f"\n[{i}/{total}] Post ID {post_id} [{editor.upper()}]")
        print(f"  Title : {title[:65]}")
        print(f"  Words : {wc} {'— SHORT, will expand' if is_short else '— OK'}")

        try:
            # Find related posts
            related = find_related_posts(post_id, title, all_refs)
            print(f"  Links : {len(related)} related posts")

            # Rewrite with Claude
            print("  Rewriting with Claude...")
            optimized = rewrite_article(
                title, current_text, wc, is_short, related, editor
            )

            new_wc = word_count(optimized["content"])
            print(f"  New title : {optimized['title'][:60]}")
            print(f"  New slug  : {optimized['slug'][:MAX_SLUG_LENGTH]}")
            print(f"  Focus KW  : {optimized['focus_keyword']}")
            print(f"  Meta desc : {len(optimized['meta_description'])} chars")
            print(f"  New words : {new_wc}")

            # Resolve cats + tags
            cat_ids = resolve_category_ids(optimized["categories"], wp_cat_map)
            tag_ids = sync_tags(optimized["tags"])

            # Update post based on editor type
            if editor == "elementor":
                print("  Updating Elementor post...")
                url = process_elementor(post, optimized, related, cat_ids, tag_ids)
            else:
                print("  Updating Gutenberg post...")
                url = process_gutenberg(post, optimized, related, cat_ids, tag_ids)

            print(f"  Updated : {url}")

            # Update Rank Math SEO
            meta_title = optimized.get(
                "meta_title",
                f"{optimized['title']} | GermanySupport.de"
            )
            rm_ok = update_rank_math_seo(
                post_id,
                optimized["focus_keyword"],
                meta_title,
                optimized["meta_description"],
            )

            # Update image alt text
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

    # 6. Summary
    print("\n" + "=" * 62)
    print("  OPTIMIZATION COMPLETE")
    print("=" * 62)
    gutenberg_ok = [r for r in results["success"] if r["editor"] == "gutenberg"]
    elementor_ok = [r for r in results["success"] if r["editor"] == "elementor"]
    rm_ok_count  = len([r for r in results["success"] if r["rm_ok"]])

    print(f"  Total             : {total}")
    print(f"  Success           : {len(results['success'])}")
    print(f"    Gutenberg       : {len(gutenberg_ok)}")
    print(f"    Elementor       : {len(elementor_ok)}")
    print(f"  Rank Math updated : {rm_ok_count}/{len(results['success'])}")
    print(f"  Failed            : {len(results['failed'])}")

    if results["success"]:
        print("\n  Updated:")
        for r in results["success"]:
            rm  = "✓ RM" if r["rm_ok"] else "✗ RM manual"
            print(f"  [{r['editor'][0].upper()}][{r['id']}] "
                  f"{r['title'][:48]} [{rm}]")
            print(f"         KW: {r['keyword']}")
            print(f"         {r['old_words']}w → {r['new_words']}w | {r['url']}")

    # Manual Rank Math fix list
    need_manual_rm = [r for r in results["success"] if not r["rm_ok"]]
    if need_manual_rm:
        print("\n" + "=" * 62)
        print("  SET THESE FOCUS KEYWORDS MANUALLY IN RANK MATH:")
        print("  (WP editor → Rank Math panel → Focus Keyword field)")
        print("=" * 62)
        for r in need_manual_rm:
            print(f"  [{r['id']}] {r['title'][:50]}")
            print(f"  Keyword: {r['keyword']}")
            print()

    if results["failed"]:
        print("\n  Failed:")
        for r in results["failed"]:
            print(f"  [{r['id']}] {r['title'][:55]}")
            print(f"         {r['error'][:120]}")

    print("=" * 62)

    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
