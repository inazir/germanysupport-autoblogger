"""
GermanySupport.de — SEO Optimizer v10
======================================
Imports all shared config from config.py (single source of truth).

Rank Math score improvements:
  - Focus keyword set via custom /wp-json/gs/v1/set-keyword endpoint
  - Keyword in title, slug, meta description, first sentence, 2+ H2s
  - ~1% keyword density enforced
  - TOC (Table of Contents) — Rank Math checks for this
  - FAQ section with schema markup wrapper
  - Internal links
  - Image alt text with keyword
  - No non-affiliated products
  - TapTap Send includes IQBAL12 promo code

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

# Import shared config
from config import (
    CURRENT_YEAR,
    ALLOWED_CATEGORIES,
    REFERRAL_LINKS,
    get_relevant_links,
    format_links_as_html,
    TAPTAP_PROMO_HTML,
)

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
TIMEOUT                   = 60

# ============================================================
#  🔄  HTTP SESSION WITH RETRY
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


def build_auth_headers():
    credentials = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

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
        raise Exception(f"POST {r.status_code}: {r.text[:300]}")
    return r


def wp_request(method, endpoint, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    url = f"{WP_URL}/wp-json/wp/v2/{endpoint}"
    r   = SESSION.request(method, url, headers=HEADERS, **kwargs)
    if not r.ok:
        raise Exception(f"WP {r.status_code}: {r.text[:300]}")
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
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc)
    except Exception:
        return None


def is_recently_updated(post, months=4):
    d = parse_wp_date(post.get("modified_gmt", "") or "")
    if not d:
        return False
    return d > datetime.now(timezone.utc) - timedelta(days=months * 30)


# ============================================================
#  🎯  RANK MATH KEYWORD SETTING
# ============================================================

def set_rank_math_keyword(post_id, focus_keyword, meta_title, meta_description):
    """
    Set Rank Math SEO data.
    Method 1: Custom Code Snippets endpoint (most reliable).
    Method 2: Native Rank Math REST API (fallback).
    """
    # Method 1: custom endpoint
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
        if r.ok and r.json().get("success"):
            print(f"  Rank Math: keyword set ✓  [{focus_keyword}]")
            return True
    except Exception as e:
        print(f"  Custom endpoint: {e}")

    # Method 2: native API
    try:
        r2 = wp_post_req(
            f"{WP_URL}/wp-json/rankmath/v1/updateMeta",
            json={
                "objectID": post_id, "objectType": "post",
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
        print(f"  Native API: {e}")

    print(f"  Rank Math: FAILED — set manually: '{focus_keyword}'")
    return False


# ============================================================
#  🔍  EDITOR DETECTION
# ============================================================

def detect_editor(post):
    meta = post.get("meta", {})
    if meta.get("_elementor_edit_mode") == "builder":
        return "elementor"
    data = meta.get("_elementor_data", "")
    if data and data not in ("", "[]", None):
        return "elementor"
    return "gutenberg"


# ============================================================
#  🧩  ELEMENTOR HELPERS
# ============================================================

def extract_text_from_elementor(raw):
    try:
        data = json.loads(raw)
    except Exception:
        return ""
    texts = []

    def traverse(obj):
        if isinstance(obj, list):
            for item in obj: traverse(item)
        elif isinstance(obj, dict):
            wt = obj.get("widgetType", "")
            s  = obj.get("settings", {})
            if wt in ("text-editor", "theme-post-content"):
                c = s.get("editor", "") or s.get("content", "")
                if c: texts.append(strip_html(c))
            elif wt == "heading":
                t = s.get("title", "")
                if t: texts.append(strip_html(t))
            elif wt == "accordion":
                for item in s.get("tabs", []):
                    texts.append(strip_html(item.get("tab_title", "")))
                    texts.append(strip_html(item.get("tab_content", "")))
            for k in ("elements", "children"):
                if k in obj: traverse(obj[k])

    traverse(data)
    return " ".join(t for t in texts if t.strip())


def update_elementor_content(raw, new_html):
    try: data = json.loads(raw)
    except Exception: return raw
    updated = [False]

    def traverse(obj):
        if isinstance(obj, list):
            for item in obj: traverse(item)
        elif isinstance(obj, dict):
            if obj.get("widgetType") == "text-editor" and not updated[0]:
                obj["settings"]["editor"] = new_html
                updated[0] = True
            for k in ("elements", "children"):
                if k in obj: traverse(obj[k])

    traverse(data)
    return json.dumps(data, ensure_ascii=False)


def fetch_elementor_raw(post_id):
    r = wp_get(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
               params={"context": "edit", "_fields": "meta"})
    return r.json().get("meta", {}).get("_elementor_data", "") or ""


def save_elementor(post_id, data_str):
    r = wp_post_req(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                    json={"meta": {"_elementor_data": data_str}})
    if not r.ok:
        raise Exception(f"Elementor save failed: {r.status_code}")


# ============================================================
#  🧹  ROBUST JSON PARSER
# ============================================================

def parse_claude_json(raw_text):
    text = raw_text.strip()
    for pat in [r"^```json\s*", r"^```\s*", r"```$"]:
        text = re.sub(pat, "", text).strip()

    try: return json.loads(text)
    except json.JSONDecodeError: pass

    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(0))
        except json.JSONDecodeError: pass

    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    fixed = fixed.replace('\u201c', '"').replace('\u201d', '"')
    fixed = fixed.replace('\u2018', "'").replace('\u2019', "'")
    try: return json.loads(fixed)
    except json.JSONDecodeError: pass

    print("  JSON malformed — asking Claude to repair...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    repair = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4096,
        messages=[{"role": "user", "content":
            "Fix this malformed JSON. Return ONLY valid JSON:\n\n" + text[:3000]}])
    r = repair.content[0].text.strip()
    r = re.sub(r"^```json\s*", "", r)
    r = re.sub(r"```$", "", r).strip()
    return json.loads(r)


# ============================================================
#  🔗  LINK VERIFICATION & INJECTION
# ============================================================

def verify_links(content_html, relevant_links):
    return [(n, u) for n, u in relevant_links.items() if u not in content_html]


def inject_missing_links(content_html, missing_links):
    if not missing_links:
        return content_html
    print(f"  Pass 3: injecting {len(missing_links)} missing links...")
    client    = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    links_str = "\n".join([
        f'- TapTap Send (promo IQBAL12, €10 bonus for €50+): {u}'
        if n == "TapTap Send" else f"- {n}: {u}"
        for n, u in missing_links
    ])
    r = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4096,
        system="""Embed affiliate links into HTML content naturally.
- Use: <a href="URL" target="_blank" rel="nofollow sponsored">descriptive text</a>
- For TapTap Send: mention the promo code IQBAL12 and €10 bonus in the anchor text or nearby
- Only embed where genuinely relevant
- Return COMPLETE HTML unchanged except for added links
- No disclosure boxes""",
        messages=[{"role": "user", "content":
            f"Add these links naturally:\n{links_str}\n\nARTICLE:\n{content_html}"}])
    result = r.content[0].text.strip()
    result = re.sub(r"^```html\s*", "", result)
    result = re.sub(r"```$", "", result).strip()
    return result


# ============================================================
#  📥  FETCH POSTS
# ============================================================

def fetch_all_english_posts():
    posts, page = [], 1
    print("  Fetching English posts...")
    while True:
        r = wp_get(f"{WP_URL}/wp-json/wp/v2/posts", params={
            "per_page": 20, "page": page, "status": "publish",
            "context": "edit",
            "_fields": "id,title,slug,content,excerpt,tags,categories,"
                       "link,lang,featured_media,meta,modified_gmt"})
        if r.status_code == 400: break
        batch = r.json()
        if not batch: break
        for p in batch:
            if p.get("lang") == "de" or "/de/" in p.get("link", ""): continue
            posts.append(p)
        total = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total} — {len(posts)} EN posts...")
        if page >= total: break
        page += 1
    return posts


def fetch_all_post_refs():
    refs, page = [], 1
    while True:
        r = wp_get(f"{WP_URL}/wp-json/wp/v2/posts", params={
            "per_page": 100, "page": page, "status": "publish",
            "_fields": "id,title,link,lang"})
        if r.status_code == 400: break
        batch = r.json()
        if not batch: break
        for p in batch:
            if p.get("lang") == "de" or "/de/" in p.get("link", ""): continue
            refs.append({"id": p["id"], "title": p["title"]["rendered"], "url": p["link"]})
        if page >= int(r.headers.get("X-WP-TotalPages", 1)): break
        page += 1
    return refs


def fetch_single_post(post_id):
    return wp_get(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
                  params={"context": "edit"}).json()


# ============================================================
#  🔗  INTERNAL LINKS
# ============================================================

def find_related(current_id, current_title, all_refs, max_links=3):
    scored, tw = [], set(re.findall(r'\b\w{4,}\b', current_title.lower()))
    for p in all_refs:
        if p["id"] == current_id: continue
        ow = set(re.findall(r'\b\w{4,}\b', p["title"].lower()))
        if not tw or not ow: continue
        overlap = len(tw & ow) / len(tw)
        sim = SequenceMatcher(None, current_title.lower(), p["title"].lower()).ratio()
        score = overlap * 0.6 + sim * 0.4
        if score > 0.12: scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:max_links]]


def build_internal_links_html(related):
    if not related: return ""
    items = "".join([f'<li><a href="{p["url"]}">{p["title"]}</a></li>' for p in related])
    return (
        '<div style="background:#f9f9f9;border:1px solid #e0e0e0;'
        'padding:16px;margin:24px 0;border-radius:4px;">'
        '<strong>Related Articles</strong>'
        f'<ul style="margin:8px 0 0;padding-left:20px;">{items}</ul></div>'
    )


# ============================================================
#  📋  TABLE OF CONTENTS
# ============================================================

def inject_anchors(html):
    def add(m):
        text = strip_html(m.group(1)).strip()
        anchor = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
        return f'<h2 id="{anchor}">{m.group(1)}</h2>'
    return re.sub(r'<h2[^>]*>(.*?)</h2>', add, html, flags=re.IGNORECASE | re.DOTALL)


def build_toc(html):
    hs = [strip_html(h).strip() for h in
          re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.IGNORECASE | re.DOTALL)]
    hs = [h for h in hs if len(h) > 3]
    if len(hs) < 3: return ""
    items = "".join([
        f'<li><a href="#{re.sub(chr(91)+"^a-z0-9"+chr(93)+"+", "-", h.lower()).strip("-")}">{h}</a></li>'
        for h in hs])
    return (
        '<div style="background:#f8f9fa;border:1px solid #dee2e6;'
        'padding:16px 20px;margin:0 0 24px;border-radius:4px;">'
        '<strong style="display:block;margin-bottom:8px;">Table of Contents</strong>'
        f'<ol style="margin:0;padding-left:20px;line-height:1.9;">{items}</ol></div>'
    )


# ============================================================
#  🖼️  IMAGE ALT TEXT
# ============================================================

def update_image_alt(media_id, keyword, title):
    if not media_id: return
    try:
        wp_post_req(f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
                    json={"alt_text": f"{keyword} — {title[:60]}"})
        print(f"  Image alt: updated ✓")
    except Exception as e:
        print(f"  Image alt warning: {e}")


# ============================================================
#  📂  CATEGORIES & TAGS
# ============================================================

def fetch_wp_categories():
    cat_map, page = {}, 1
    while True:
        r = wp_get(f"{WP_URL}/wp-json/wp/v2/categories",
                   params={"per_page": 100, "page": page, "_fields": "id,name"})
        if r.status_code == 400: break
        for c in r.json(): cat_map[c["name"].lower()] = c["id"]
        if page >= int(r.headers.get("X-WP-TotalPages", 1)): break
        page += 1
    return cat_map


def resolve_category_ids(chosen, wp_cat_map):
    ids = []
    for name in chosen:
        nl = name.lower()
        if nl in wp_cat_map:
            ids.append(wp_cat_map[nl]); continue
        best_score, best_key = 0, None
        for k in wp_cat_map:
            s = SequenceMatcher(None, nl, k).ratio()
            if s > best_score: best_score, best_key = s, k
        if best_key and best_score >= 0.60:
            ids.append(wp_cat_map[best_key])
        else:
            print(f"    WARNING: no match for '{name}'")
    if not ids:
        fb = "living in germany"
        if fb in wp_cat_map: ids.append(wp_cat_map[fb])
    return ids


def sync_tags(tag_names):
    ids = []
    for name in tag_names:
        try:
            ids.append(wp_request("POST", "tags", json={"name": name})["id"])
        except Exception:
            s = wp_get(f"{WP_URL}/wp-json/wp/v2/tags",
                       params={"search": name, "per_page": 1}).json()
            if s: ids.append(s[0]["id"])
    return ids


# ============================================================
#  🤖  CLAUDE — TWO-PASS REWRITE
# ============================================================

def claude_call(system_prompt, user_prompt, max_tokens=4096):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    r = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}])
    return r.content[0].text.strip()


def rewrite_pass1(title, current_text, wc, is_short, related, relevant_links):
    links_html  = format_links_as_html(relevant_links)
    cats_str    = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)
    target      = max(MIN_WORD_COUNT, wc)
    length_note = (
        f"EXPAND to at least {MIN_WORD_COUNT} words — currently only ~{wc}."
        if is_short else f"Write {target}+ words. Do NOT shorten."
    )
    related_str = ""
    if related:
        related_str = "\n\nAlso embed these INTERNAL links:\n"
        related_str += "\n".join([f'- <a href="{p["url"]}">{p["title"]}</a>' for p in related])

    system = f"""
You are an expert SEO writer for an expat guide site about Germany.
Optimizing for Rank Math SEO. Year: {CURRENT_YEAR}.

RANK MATH SCORE REQUIREMENTS (aim for 80+ score):
1. Focus keyword in the VERY FIRST sentence of the article
2. Focus keyword near the START of the SEO title
3. Focus keyword in meta description WITHIN FIRST 10 WORDS
4. Focus keyword in AT LEAST 2 H2 headings — exactly, not paraphrased
5. Keyword density ~1% — use every 100-150 words naturally
6. Slug under {MAX_SLUG_LENGTH} chars, MUST contain focus keyword
7. Use H2 and H3 headings throughout for clear structure
8. Use short paragraphs (2-4 sentences max per paragraph)

CONTENT:
- {length_note}
- Update ALL information to {CURRENT_YEAR} — no outdated years
- Do NOT add FAQ (separate pass)
- Do NOT add any affiliate disclosure box

AFFILIATE LINKS — ALL MANDATORY — MUST ALL APPEAR:
{links_html}{related_str}

SPECIAL RULE for TapTap Send:
When mentioning TapTap Send, ALWAYS include promo code IQBAL12
and mention the €10-€15 bonus for sending €50 or more.

JSON RULES:
- Escape all quotes in content: \\" not "
- No smart/curly quotes
- Complete valid JSON
- Slug max {MAX_SLUG_LENGTH} chars

CATEGORIES (1-2, exact names only):
{cats_str}

Return ONLY this JSON:
{{
  "title": "Focus Keyword: Compelling Title {CURRENT_YEAR}",
  "slug": "focus-keyword-short-slug",
  "meta_title": "Focus Keyword | GermanySupport.de",
  "meta_description": "Focus keyword in first 10 words. 150-155 chars exactly.",
  "focus_keyword": "exact focus keyword phrase",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "categories": ["Category Name"],
  "content": "Complete HTML — short paragraphs, H2/H3 structure, all affiliate links, NO FAQ, NO disclosure"
}}
"""

    user = f"""
Rewrite for Rank Math SEO. Target score: 80+.

TITLE: {title}
YEAR: {CURRENT_YEAR}
WORDS: ~{wc} → target {target}+

CONTENT:
{current_text}

ALL affiliate links are MANDATORY. Include TapTap promo code IQBAL12.
Return COMPLETE JSON only.
"""
    return parse_claude_json(claude_call(system, user))


def rewrite_pass2_faq(title, keyword, summary):
    """Generate FAQ with Rank Math FAQ schema markup."""
    system = f"""
Write FAQ sections for expat guides about Germany ({CURRENT_YEAR}).

IMPORTANT: Use Rank Math FAQ schema markup format:
<div class="rank-math-faq-item">
  <h3 class="rank-math-question">Question here?</h3>
  <div class="rank-math-answer"><p>Answer here in 2-4 sentences.</p></div>
</div>

Rules:
- Wrap ALL questions in this exact markup
- Start with: <h2 id="faq">Frequently Asked Questions</h2>
- 5-6 questions total
- Include focus keyword in 1-2 questions
- Answers accurate for {CURRENT_YEAR}
- Return ONLY HTML, no JSON, no explanation
"""
    user = f"""
FAQ for:
TITLE: {title}
KEYWORD: {keyword}
SUMMARY: {summary[:1000]}
Return ONLY the FAQ HTML with Rank Math schema markup.
"""
    return claude_call(system, user, max_tokens=1200)


# ============================================================
#  📝  ASSEMBLE FINAL CONTENT
# ============================================================

def assemble_content(optimized, related):
    content = inject_anchors(optimized["content"])

    # TOC after first paragraph
    first_p = re.search(r'(<p>.*?</p>)', content, re.DOTALL | re.IGNORECASE)
    toc     = build_toc(content)
    if first_p and toc:
        content = content[:first_p.end()] + "\n" + toc + "\n" + content[first_p.end():]
    elif toc:
        content = toc + "\n" + content

    # Internal links before FAQ
    il = build_internal_links_html(related)
    if il:
        faq = re.search(r'(<h2[^>]*>.*?[Ff][Aa][Qq].*?</h2>)',
                        content, re.DOTALL | re.IGNORECASE)
        if faq:
            content = content[:faq.start()] + il + "\n" + content[faq.start():]
        else:
            content += "\n" + il

    return content


# ============================================================
#  📤  UPDATE POSTS
# ============================================================

def update_wp_post(post_id, optimized, final, cat_ids, tag_ids):
    return wp_request("POST", f"posts/{post_id}", json={
        "title":      optimized["title"],
        "slug":       optimized["slug"][:MAX_SLUG_LENGTH],
        "content":    final,
        "excerpt":    optimized["meta_description"],
        "tags":       tag_ids,
        "categories": cat_ids,
    })


def process_elementor(post, optimized, final, cat_ids, tag_ids):
    pid   = post["id"]
    raw   = fetch_elementor_raw(pid)
    if raw and raw not in ("", "[]"):
        save_elementor(pid, update_elementor_content(raw, final))
        print("  Elementor: updated ✓")
    return update_wp_post(pid, optimized, final, cat_ids, tag_ids)


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport SEO Optimizer v10")
    parser.add_argument("--limit",   type=int,  default=None)
    parser.add_argument("--post-id", type=int,  default=None)
    parser.add_argument("--force",   action="store_true")
    args = parser.parse_args()

    print("=" * 62)
    print(f"  GermanySupport.de — SEO Optimizer v10 ({CURRENT_YEAR})")
    print("  config.py | Rank Math 80+ | TapTap IQBAL12 | No removed products")
    print("=" * 62)

    # 1. Check custom endpoint
    print("\n[1] Checking custom Rank Math endpoint...")
    try:
        test = wp_post_req(f"{WP_URL}/wp-json/gs/v1/set-keyword",
                           json={"post_id": 0, "keyword": "test"})
        print("    Custom endpoint: available ✓")
    except Exception as e:
        if "400" in str(e) or "missing" in str(e).lower():
            print("    Custom endpoint: available ✓")
        else:
            print(f"    Custom endpoint: NOT found — add Code Snippet first")
            print(f"    Falling back to native Rank Math API")

    # 2. Categories
    print("\n[2] Fetching categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 3. Post refs
    print("\n[3] Fetching post list for internal linking...")
    all_refs = fetch_all_post_refs()
    print(f"    Found {len(all_refs)} English posts.")

    # 4. Posts to optimize
    print("\n[4] Fetching posts...")
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
        posts  = [p for p in posts if not is_recently_updated(p, SKIP_IF_NEWER_THAN_MONTHS)]
        print(f"    Skipping {before - len(posts)} recently updated. Will process {len(posts)}.")

    if not posts:
        print("\n    All articles recently updated. Use --force to override.")
        return

    # 6. Optimize loop
    print(f"\n[5] Optimizing {len(posts)} articles...")
    print("=" * 62)

    results = {"success": [], "failed": []}
    total   = len(posts)

    for i, post in enumerate(posts, 1):
        pid      = post["id"]
        title    = post["title"]["rendered"]
        media_id = post.get("featured_media") or None
        editor   = detect_editor(post)
        modified = post.get("modified_gmt", "")[:10]

        if editor == "elementor":
            raw_el = fetch_elementor_raw(pid)
            curr   = extract_text_from_elementor(raw_el) if raw_el else ""
            if not curr:
                curr = strip_html(post.get("content", {}).get("rendered", ""))
        else:
            curr = strip_html(post.get("content", {}).get("rendered", ""))

        wc       = len(curr.split())
        is_short = wc < MIN_WORD_COUNT

        print(f"\n[{i}/{total}] Post {pid} [{editor.upper()}] mod:{modified}")
        print(f"  Title : {title[:65]}")
        print(f"  Words : {wc} {'— SHORT' if is_short else '— OK'}")

        try:
            rel_links = get_relevant_links(title, curr)
            related   = find_related(pid, title, all_refs)
            print(f"  Links : {len(rel_links)} affiliate | {len(related)} internal")

            # Pass 1
            print("  Pass 1: rewriting...")
            optimized = rewrite_pass1(title, curr, wc, is_short, related, rel_links)

            # Verify + inject
            missing = verify_links(optimized["content"], rel_links)
            print(f"  Links : {len(rel_links)-len(missing)}/{len(rel_links)} present")
            if missing:
                optimized["content"] = inject_missing_links(optimized["content"], missing)
                still = verify_links(optimized["content"], rel_links)
                print(f"  Links : {len(rel_links)-len(still)}/{len(rel_links)} after injection")

            # Pass 2: FAQ with schema markup
            print("  Pass 2: FAQ with Rank Math schema...")
            faq = rewrite_pass2_faq(
                optimized["title"],
                optimized["focus_keyword"],
                strip_html(optimized["content"])[:2000],
            )
            optimized["content"] += "\n" + faq

            new_wc = word_count(optimized["content"])
            print(f"  KW    : {optimized['focus_keyword']}")
            print(f"  Meta  : {len(optimized['meta_description'])} chars")
            print(f"  Words : {wc} → {new_wc}")

            final   = assemble_content(optimized, related)
            cat_ids = resolve_category_ids(optimized["categories"], wp_cat_map)
            tag_ids = sync_tags(optimized["tags"])

            if editor == "elementor":
                updated = process_elementor(post, optimized, final, cat_ids, tag_ids)
            else:
                updated = update_wp_post(pid, optimized, final, cat_ids, tag_ids)

            url = updated["link"]
            print(f"  Saved : {url}")

            meta_title = optimized.get("meta_title",
                                       f"{optimized['title']} | GermanySupport.de")
            rm_ok = set_rank_math_keyword(
                pid, optimized["focus_keyword"], meta_title,
                optimized["meta_description"])

            update_image_alt(media_id, optimized["focus_keyword"], optimized["title"])

            results["success"].append({
                "id": pid, "title": optimized["title"], "url": url,
                "old_words": wc, "new_words": new_wc,
                "keyword": optimized["focus_keyword"],
                "editor": editor, "rm_ok": rm_ok,
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            results["failed"].append({"id": pid, "title": title, "error": str(e)})

        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s...")
            time.sleep(DELAY_BETWEEN)

    # 7. Summary
    print("\n" + "=" * 62)
    print(f"  COMPLETE — {CURRENT_YEAR}")
    print("=" * 62)
    rm_count = len([r for r in results["success"] if r["rm_ok"]])
    print(f"  Year       : {CURRENT_YEAR}")
    print(f"  Total      : {total}")
    print(f"  Success    : {len(results['success'])}")
    print(f"  Keyword set: {rm_count}/{len(results['success'])}")
    print(f"  Failed     : {len(results['failed'])}")

    if results["success"]:
        print("\n  Updated:")
        for r in results["success"]:
            rm = "✓ KW" if r["rm_ok"] else "✗ KW manual"
            print(f"  [{r['editor'][0].upper()}][{r['id']}] {r['title'][:48]} [{rm}]")
            print(f"         {r['old_words']}w → {r['new_words']}w | {r['keyword']}")

    need_rm = [r for r in results["success"] if not r["rm_ok"]]
    if need_rm:
        print("\n  SET MANUALLY IN RANK MATH (WP editor → Rank Math → Focus Keyword):")
        for r in need_rm:
            print(f"  [{r['id']}] {r['keyword']} → {r['url']}")

    if results["failed"]:
        print("\n  Failed (run again to retry):")
        for r in results["failed"]:
            print(f"  [{r['id']}] {r['title'][:55]} — {r['error'][:80]}")

    print("=" * 62)
    if results["failed"]: sys.exit(1)


if __name__ == "__main__":
    main()