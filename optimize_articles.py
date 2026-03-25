"""
GermanySupport.de — SEO Optimizer v6
======================================
Fixes from v5:
  - Two-pass Claude rewrite: main body first, FAQ second
    (prevents token limit cutoff and incomplete articles)
  - Affiliate disclosure removed (Popcorn theme adds it automatically)
  - Full content sent to Claude (no 5000 char truncation)
  - Referral links reliably embedded
  - Handles both Gutenberg and Elementor posts

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
DELAY_BETWEEN   = 12
CURRENT_YEAR    = 2025
MAX_SLUG_LENGTH = 60

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
    """Extract all visible text from Elementor JSON."""
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
                content = settings.get("editor", "") or settings.get("content", "")
                if content:
                    texts.append(strip_html(content))
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


def update_elementor_content(elementor_data_str, new_content_html):
    """Replace main text-editor widget content in Elementor JSON."""
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
                obj["settings"]["editor"] = new_content_html
                updated[0] = True
            for key in ("elements", "children"):
                if key in obj:
                    traverse_update(obj[key])

    traverse_update(data)
    return json.dumps(data, ensure_ascii=False)


def fetch_elementor_raw_data(post_id):
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        params={"context": "edit", "_fields": "meta"},
    )
    if r.ok:
        return r.json().get("meta", {}).get("_elementor_data", "") or ""
    return ""


def save_elementor_data(post_id, elementor_data_str):
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        json={"meta": {"_elementor_data": elementor_data_str}},
    )
    if not r.ok:
        raise Exception(f"Elementor save failed: {r.status_code} {r.text[:200]}")


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
#  🎯  RANK MATH NATIVE API
# ============================================================

def update_rank_math_seo(post_id, focus_keyword, meta_title, meta_description):
    """Update Rank Math SEO via its native REST endpoint."""
    try:
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
            print(f"  Rank Math: updated ✓")
            return True

        # Try form-encoded fallback
        form_hdrs = dict(HEADERS)
        form_hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        r2 = requests.post(
            f"{WP_URL}/wp-json/rankmath/v1/updateMeta",
            headers=form_hdrs,
            data={
                "objectID":                post_id,
                "objectType":              "post",
                "rank_math_focus_keyword": focus_keyword,
                "rank_math_title":         meta_title,
                "rank_math_description":   meta_description,
            },
        )
        if r2.ok:
            print(f"  Rank Math: updated via form data ✓")
            return True

        print(f"  Rank Math: failed ({r.status_code}) — set manually: '{focus_keyword}'")
        return False
    except Exception as e:
        print(f"  Rank Math error: {e}")
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
    refs = []
    page = 1
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
#  🤖  CLAUDE TWO-PASS REWRITE
#  Pass 1: SEO metadata + full article body (no FAQ)
#  Pass 2: FAQ section only
#  Combined: complete article that never hits token limits
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


def rewrite_pass1_metadata_and_body(title, current_text, wc, is_short, related):
    """
    Pass 1: Generate SEO metadata + full article body (without FAQ).
    Returns parsed JSON with title, slug, meta fields, and content.
    """
    links_str   = "\n".join([f"- {k}: {v}" for k, v in REFERRAL_LINKS.items()])
    cats_str    = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)
    related_str = ""
    if related:
        related_str = "\n\nEmbed these internal links naturally:\n"
        related_str += "\n".join([
            f'- <a href="{p["url"]}">{p["title"]}</a>'
            for p in related
        ])

    target_words = max(MIN_WORD_COUNT, wc)
    length_note  = (
        f"EXPAND to at least {MIN_WORD_COUNT} words — currently only ~{wc}."
        if is_short else
        f"Write approximately {target_words} words — do NOT shorten."
    )

    system = f"""
You are an expert SEO writer for an expat guide website about Germany.
Optimizing for Rank Math SEO. Today is {CURRENT_YEAR}.

RANK MATH REQUIREMENTS:
1. Focus keyword in the VERY FIRST sentence
2. Focus keyword in SEO title (near start)
3. Focus keyword in meta description (first 10 words)
4. Focus keyword in at least 2 H2 headings
5. Keyword density ~1% (every 100-150 words naturally)
6. Slug under {MAX_SLUG_LENGTH} chars, contains focus keyword

CONTENT:
- {length_note}
- Update all info to {CURRENT_YEAR}
- Clear H2/H3 structure throughout
- Embed affiliate links: <a href="URL" target="_blank" rel="nofollow sponsored">text</a>
- Only embed affiliate links where directly relevant
- Do NOT include a FAQ section — that comes in a separate pass
- Do NOT include any affiliate disclosure box{related_str}

JSON OUTPUT RULES:
- Escape all quotes in content: \\" not "
- No smart/curly quotes
- Valid complete JSON only
- Slug max {MAX_SLUG_LENGTH} chars

CATEGORIES — 1-2 only, exact names:
{cats_str}

Return ONLY this JSON:
{{
  "title": "Focus Keyword: Compelling Title",
  "slug": "focus-keyword-slug",
  "meta_title": "Focus Keyword | GermanySupport.de",
  "meta_description": "Focus keyword first. 150-155 chars exactly.",
  "focus_keyword": "exact focus keyword",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "categories": ["Category Name"],
  "content": "Full article HTML — H2/H3 structure, affiliate links, NO FAQ, NO disclosure"
}}
"""

    user = f"""
Rewrite and optimize this article for Rank Math SEO.

TITLE: {title}
WORDS: ~{wc}
TARGET: {target_words}+ words

CURRENT CONTENT:
{current_text}

AFFILIATE LINKS (embed where relevant):
{links_str}

Important:
- Write the COMPLETE article body
- Include ALL sections fully — do not stop early
- Do not add FAQ (separate pass)
- Do not add affiliate disclosure box
"""

    raw = claude_call(system, user, max_tokens=4096)
    return parse_claude_json(raw)


def rewrite_pass2_faq(title, focus_keyword, current_text):
    """
    Pass 2: Generate only the FAQ section.
    Returns HTML string starting with <h2>Frequently Asked Questions</h2>
    """
    system = f"""
You are an SEO writer creating FAQ sections for expat guides about Germany.
Today is {CURRENT_YEAR}.

Create a FAQ section with 5-6 questions and detailed answers.
Rules:
- Start with: <h2 id="faq">Frequently Asked Questions</h2>
- Each question: <h3>Question text?</h3>
- Each answer: <p>Detailed answer in 2-4 sentences.</p>
- Include the focus keyword naturally in 1-2 questions
- Questions must be things real expats actually ask
- Answers must be accurate for {CURRENT_YEAR}
- Return ONLY the HTML, no JSON wrapper, no explanation
"""

    user = f"""
Write a FAQ section for this article about Germany for expats.

ARTICLE TITLE: {title}
FOCUS KEYWORD: {focus_keyword}

ARTICLE SUMMARY:
{current_text[:1500]}

Return ONLY the FAQ HTML starting with <h2 id="faq">Frequently Asked Questions</h2>
"""

    return claude_call(system, user, max_tokens=1500)


def rewrite_article(title, current_text, wc, is_short, related):
    """
    Full two-pass rewrite:
    1. Main article body + SEO metadata
    2. FAQ section
    Returns optimized dict with complete content.
    """
    print("  Pass 1: rewriting article body...")
    optimized = rewrite_pass1_metadata_and_body(
        title, current_text, wc, is_short, related
    )

    print("  Pass 2: generating FAQ section...")
    faq_html = rewrite_pass2_faq(
        optimized["title"],
        optimized["focus_keyword"],
        strip_html(optimized["content"])[:2000],
    )

    # Append FAQ to content
    optimized["content"] = optimized["content"] + "\n" + faq_html

    return optimized


# ============================================================
#  📝  ASSEMBLE FINAL CONTENT
# ============================================================

def assemble_content(optimized, related):
    """
    Build final HTML:
    1. Article content with anchor IDs on H2s
    2. TOC after first paragraph
    3. Internal links before FAQ
    Note: NO affiliate disclosure (theme handles it)
    """
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

    return content


# ============================================================
#  📤  UPDATE POSTS
# ============================================================

def process_gutenberg(post, optimized, final_content, cat_ids, tag_ids):
    updated = wp_request(
        "POST",
        f"posts/{post['id']}",
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


def process_elementor(post, optimized, final_content, cat_ids, tag_ids):
    post_id = post["id"]
    print(f"  Fetching Elementor data...")
    raw_el  = fetch_elementor_raw_data(post_id)

    if raw_el and raw_el not in ("", "[]"):
        updated_el = update_elementor_content(raw_el, final_content)
        save_elementor_data(post_id, updated_el)
        print(f"  Elementor data updated.")
    else:
        print(f"  No Elementor data — updating post_content only.")

    # Always update post_content for SEO crawlers
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
    parser = argparse.ArgumentParser(description="GermanySupport SEO Optimizer v6")
    parser.add_argument("--limit",   type=int, default=None)
    parser.add_argument("--post-id", type=int, default=None)
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — SEO Optimizer v6")
    print("  Two-pass rewrite | Gutenberg + Elementor | Rank Math")
    print("=" * 62)

    # 1. Check Rank Math API
    print("\n[1] Checking Rank Math API...")
    rm_check = requests.get(f"{WP_URL}/wp-json/rankmath/v1/", headers=HEADERS)
    print(f"    Rank Math API: {'available ✓' if rm_check.ok else f'{rm_check.status_code} — will list keywords manually'}")

    # 2. Fetch categories
    print("\n[2] Fetching categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 3. Fetch post refs for internal linking
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
        print(f"    Will process {len(posts)} articles.")

    if not posts:
        print("    No posts found.")
        return

    # 5. Optimize
    print(f"\n[5] Optimizing...")
    print("=" * 62)

    results = {"success": [], "failed": []}
    total   = len(posts)

    for i, post in enumerate(posts, 1):
        post_id  = post["id"]
        title    = post["title"]["rendered"]
        media_id = post.get("featured_media") or None
        editor   = detect_editor(post)

        # Get content based on editor type
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

        print(f"\n[{i}/{total}] Post ID {post_id} [{editor.upper()}]")
        print(f"  Title  : {title[:65]}")
        print(f"  Words  : {wc} {'— SHORT, will expand' if is_short else '— OK'}")

        try:
            # Related posts for internal linking
            related = find_related_posts(post_id, title, all_refs)
            print(f"  Links  : {len(related)} related posts found")

            # Two-pass rewrite
            optimized = rewrite_article(
                title, current_text, wc, is_short, related
            )

            new_wc = word_count(optimized["content"])
            print(f"  New title : {optimized['title'][:60]}")
            print(f"  New slug  : {optimized['slug'][:MAX_SLUG_LENGTH]}")
            print(f"  Focus KW  : {optimized['focus_keyword']}")
            print(f"  Meta desc : {len(optimized['meta_description'])} chars")
            print(f"  New words : {new_wc}")
            print(f"  Category  : {optimized['categories']}")

            # Assemble final content
            final = assemble_content(optimized, related)

            # Resolve cats + tags
            cat_ids = resolve_category_ids(optimized["categories"], wp_cat_map)
            tag_ids = sync_tags(optimized["tags"])

            # Update post
            if editor == "elementor":
                print("  Updating Elementor post...")
                url = process_elementor(post, optimized, final, cat_ids, tag_ids)
            else:
                print("  Updating Gutenberg post...")
                url = process_gutenberg(post, optimized, final, cat_ids, tag_ids)

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
            print(f"  Waiting {DELAY_BETWEEN}s before next article...")
            time.sleep(DELAY_BETWEEN)

    # 6. Summary
    print("\n" + "=" * 62)
    print("  OPTIMIZATION COMPLETE")
    print("=" * 62)
    g_ok     = [r for r in results["success"] if r["editor"] == "gutenberg"]
    e_ok     = [r for r in results["success"] if r["editor"] == "elementor"]
    rm_count = len([r for r in results["success"] if r["rm_ok"]])

    print(f"  Total processed   : {total}")
    print(f"  Success           : {len(results['success'])}")
    print(f"    Gutenberg       : {len(g_ok)}")
    print(f"    Elementor       : {len(e_ok)}")
    print(f"  Rank Math updated : {rm_count}/{len(results['success'])}")
    print(f"  Failed            : {len(results['failed'])}")

    if results["success"]:
        print("\n  Updated articles:")
        for r in results["success"]:
            rm  = "✓ RM" if r["rm_ok"] else "✗ RM"
            print(f"  [{r['editor'][0].upper()}][{r['id']}] "
                  f"{r['title'][:48]} [{rm}]")
            print(f"         KW: {r['keyword']}")
            print(f"         {r['old_words']}w → {r['new_words']}w")
            print(f"         {r['url']}")

    # Manual Rank Math list
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
        print("\n  Failed:")
        for r in results["failed"]:
            print(f"  [{r['id']}] {r['title'][:55]}")
            print(f"         {r['error'][:120]}")

    print("=" * 62)

    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
