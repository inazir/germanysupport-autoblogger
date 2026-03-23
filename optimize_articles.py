"""
GermanySupport.de — SEO Optimizer & Article Rewriter v3
========================================================
Fully compatible with Rank Math SEO plugin.

Fixes all Rank Math errors:
  - Writes focus keyword to Rank Math meta fields
  - Focus keyword enforced in title, slug, meta description, first paragraph
  - Adds Table of Contents (TOC) after introduction
  - Adds internal links to related articles
  - Updates featured image alt text with focus keyword
  - Shorter slugs (under 60 characters)
  - Affiliate disclosure at top of every article
  - FAQ section at bottom
  - 1200-1800 words minimum

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
MIN_WORD_COUNT = 1200
DELAY_BETWEEN  = 10
CURRENT_YEAR   = 2025
MAX_SLUG_LENGTH = 60

# ============================================================
#  📢  AFFILIATE DISCLOSURE
# ============================================================
AFFILIATE_DISCLOSURE = """<div style="background:#f0f7ff;border-left:4px solid #0073aa;padding:12px 16px;margin-bottom:24px;font-size:14px;line-height:1.6;border-radius:0 4px 4px 0;">
<strong>Affiliate Disclosure:</strong> This article contains affiliate links. If you click a link and make a purchase or sign up, we may earn a small commission at no extra cost to you. We only recommend services we believe are genuinely useful for expats in Germany. <a href="/affiliate-disclosure/" style="color:#0073aa;">Read our full disclosure.</a>
</div>"""

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


def word_count(html):
    return len(strip_html(html).split())


# ============================================================
#  🧹  ROBUST JSON PARSER
# ============================================================

def parse_claude_json(raw_text):
    text = raw_text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*",     "", text)
    text = re.sub(r"```$",        "", text).strip()

    # Strategy 1: direct
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Strategy 3: fix common issues
    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    fixed = fixed.replace('\u201c', '"').replace('\u201d', '"')
    fixed = fixed.replace('\u2018', "'").replace('\u2019', "'")
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Strategy 4: ask Claude to repair
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
    repaired = re.sub(r"```$", "", repaired).strip()
    return json.loads(repaired)


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
                "_fields":  "id,title,slug,content,excerpt,tags,categories,link,lang,featured_media",
            },
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for post in batch:
            link = post.get("link", "")
            lang = post.get("lang", "")
            if lang == "de" or "/de/" in link:
                continue
            posts.append(post)
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total_pages} — {len(posts)} English posts...")
        if page >= total_pages:
            break
        page += 1
    return posts


def fetch_all_post_titles_and_urls():
    """
    Fetch all English post titles and URLs for internal linking.
    Returns list of {id, title, url, slug}
    """
    posts = []
    page  = 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={
                "per_page": 100,
                "page":     page,
                "status":   "publish",
                "_fields":  "id,title,link,slug,lang",
            },
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for post in batch:
            lang = post.get("lang", "")
            link = post.get("link", "")
            if lang == "de" or "/de/" in link:
                continue
            posts.append({
                "id":    post["id"],
                "title": post["title"]["rendered"],
                "url":   link,
                "slug":  post["slug"],
            })
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break
        page += 1
    return posts


def fetch_single_post(post_id):
    return wp_request("GET", f"posts/{post_id}")


# ============================================================
#  🔗  INTERNAL LINKS
# ============================================================

def find_related_posts(current_post_id, current_title, all_posts, max_links=3):
    """
    Find related posts for internal linking using title similarity.
    Returns list of {title, url} for up to max_links related posts.
    """
    scored = []
    title_words = set(re.findall(r'\b\w{4,}\b', current_title.lower()))

    for post in all_posts:
        if post["id"] == current_post_id:
            continue
        other_words = set(re.findall(r'\b\w{4,}\b', post["title"].lower()))
        if not title_words or not other_words:
            continue
        overlap = len(title_words & other_words) / len(title_words)
        sim     = SequenceMatcher(None, current_title.lower(), post["title"].lower()).ratio()
        score   = (overlap * 0.6) + (sim * 0.4)
        if score > 0.15:
            scored.append((score, post))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:max_links]]


def build_internal_links_html(related_posts):
    """Build an HTML 'Related Articles' section for internal linking."""
    if not related_posts:
        return ""
    items = "".join([
        f'<li><a href="{p["url"]}">{p["title"]}</a></li>'
        for p in related_posts
    ])
    return (
        f'<div style="background:#f9f9f9;border:1px solid #e0e0e0;'
        f'padding:16px;margin:24px 0;border-radius:4px;">'
        f'<strong>Related Articles</strong><ul style="margin:8px 0 0 0;'
        f'padding-left:20px;">{items}</ul></div>'
    )


# ============================================================
#  📋  TABLE OF CONTENTS
# ============================================================

def build_toc(content_html):
    """
    Extract H2 headings from content and build a TOC.
    Returns TOC HTML string.
    """
    headings = re.findall(r'<h2[^>]*>(.*?)</h2>', content_html, re.IGNORECASE | re.DOTALL)
    headings = [strip_html(h).strip() for h in headings]
    headings = [h for h in headings if h and len(h) > 3]

    if len(headings) < 3:
        return ""

    items = ""
    for i, heading in enumerate(headings, 1):
        anchor = re.sub(r'[^a-z0-9]+', '-', heading.lower()).strip('-')
        items += f'<li><a href="#{anchor}">{heading}</a></li>'

    toc = (
        f'<div style="background:#f8f9fa;border:1px solid #dee2e6;'
        f'padding:16px 20px;margin:0 0 24px 0;border-radius:4px;">'
        f'<strong style="display:block;margin-bottom:8px;">Table of Contents</strong>'
        f'<ol style="margin:0;padding-left:20px;line-height:1.9;">{items}</ol>'
        f'</div>'
    )
    return toc


def inject_anchors_into_headings(content_html):
    """Add id anchors to H2 headings so TOC links work."""
    def add_anchor(match):
        heading_text = strip_html(match.group(1)).strip()
        anchor = re.sub(r'[^a-z0-9]+', '-', heading_text.lower()).strip('-')
        return f'<h2 id="{anchor}">{match.group(1)}</h2>'
    return re.sub(r'<h2[^>]*>(.*?)</h2>', add_anchor, content_html,
                  flags=re.IGNORECASE | re.DOTALL)


# ============================================================
#  🖼️  IMAGE ALT TEXT
# ============================================================

def update_featured_image_alt(media_id, focus_keyword, post_title):
    """Update the featured image alt text with the focus keyword."""
    if not media_id:
        return
    try:
        requests.post(
            f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
            headers=HEADERS,
            json={
                "alt_text": f"{focus_keyword} — {post_title[:60]}",
            },
        )
    except Exception as e:
        print(f"  Warning: could not update image alt text: {e}")


# ============================================================
#  📂  CATEGORIES & TAGS
# ============================================================

def fetch_wp_categories():
    cat_map = {}
    page = 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            headers=HEADERS,
            params={"per_page": 100, "page": page, "_fields": "id,name"},
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for cat in batch:
            cat_map[cat["name"].lower()] = cat["id"]
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break
        page += 1
    return cat_map


def resolve_category_ids(chosen_categories, wp_cat_map):
    ids = []
    for name in chosen_categories:
        name_lower = name.lower()
        if name_lower in wp_cat_map:
            ids.append(wp_cat_map[name_lower])
            continue
        best_score, best_key = 0, None
        for wp_name_lower in wp_cat_map:
            score = SequenceMatcher(None, name_lower, wp_name_lower).ratio()
            if score > best_score:
                best_score, best_key = score, wp_name_lower
        if best_key and best_score >= 0.60:
            ids.append(wp_cat_map[best_key])
        else:
            print(f"    WARNING: Could not match category '{name}'")
    if not ids:
        fallback = "living in germany"
        if fallback in wp_cat_map:
            ids.append(wp_cat_map[fallback])
    return ids


def sync_tags(tag_names):
    tag_ids = []
    for name in tag_names:
        try:
            t = wp_request("POST", "tags", json={"name": name})
            tag_ids.append(t["id"])
        except Exception:
            search = requests.get(
                f"{WP_URL}/wp-json/wp/v2/tags",
                headers=HEADERS,
                params={"search": name, "per_page": 1},
            ).json()
            if search:
                tag_ids.append(search[0]["id"])
    return tag_ids


# ============================================================
#  🤖  CLAUDE REWRITE
# ============================================================

def rewrite_article(post, is_short, related_posts):
    client       = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    title        = post["title"]["rendered"]
    current_text = strip_html(post["content"]["rendered"])
    wc           = word_count(post["content"]["rendered"])
    links_str    = "\n".join([f"- {k}: {v}" for k, v in REFERRAL_LINKS.items()])
    cats_str     = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    # Build internal links context for Claude
    related_str = ""
    if related_posts:
        related_str = "\n".join([
            f'- <a href="{p["url"]}">{p["title"]}</a>'
            for p in related_posts
        ])
        related_str = f"\nEmbed these internal links naturally in the content:\n{related_str}"

    length_instruction = (
        f"Current article is ~{wc} words — EXPAND to at least "
        f"{MIN_WORD_COUNT} words with detailed, useful information."
        if is_short else
        f"Current article is ~{wc} words. Keep or increase this length."
    )

    system_prompt = f"""
You are an expert SEO content writer for an expat guide website about Germany.
You are optimizing articles specifically for the Rank Math SEO plugin.
Today is {CURRENT_YEAR}.

CRITICAL RANK MATH SEO REQUIREMENTS:
1. Focus keyword MUST appear in the very first sentence of the article
2. Focus keyword MUST appear in the SEO title (near the beginning)
3. Focus keyword MUST appear in the meta description
4. Focus keyword MUST appear in at least 2 H2 or H3 headings
5. Focus keyword density should be around 1% (use it naturally every 100-150 words)
6. Slug MUST contain the focus keyword and be under {MAX_SLUG_LENGTH} characters
7. Add a FAQ section at the end with 5-6 questions (Rank Math FAQ schema)
8. Use H2 and H3 headings throughout for structure

CONTENT RULES:
- {length_instruction}
- Update all information to {CURRENT_YEAR}
- Write in clear, helpful English for expats in Germany
- Embed affiliate links naturally: <a href="URL" target="_blank" rel="nofollow sponsored">text</a>
- Only embed affiliate links where directly relevant{related_str}

JSON OUTPUT RULES (very important):
- Escape ALL quotes inside content field: \" not "
- No curly/smart quotes anywhere
- JSON must be complete and valid
- Slug max {MAX_SLUG_LENGTH} characters, lowercase, hyphens only

CATEGORIES — pick 1-2, exact names only:
{cats_str}

Output ONLY valid JSON:
{{
  "title": "Focus Keyword Near Start — Compelling Title",
  "slug": "focus-keyword-short-slug",
  "meta_description": "Focus keyword in first 10 words. Compelling description. Exactly 150-155 chars.",
  "focus_keyword": "exact focus keyword phrase",
  "tags": ["tag1", "tag2", "tag3"],
  "categories": ["Category Name"],
  "content": "Full HTML with escaped quotes, H2/H3 headings, FAQ section at end"
}}
"""

    user_prompt = f"""
Rewrite and SEO-optimize this article for Rank Math SEO plugin.

CURRENT TITLE: {title}
CURRENT WORD COUNT: ~{wc} words

CURRENT CONTENT:
{current_text[:5000]}

AFFILIATE LINKS (embed naturally where relevant):
{links_str}

Output ONLY the raw JSON object. All quotes in content must be escaped.
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    return parse_claude_json(response.content[0].text)


# ============================================================
#  📝  ASSEMBLE FINAL CONTENT
# ============================================================

def assemble_content(optimized, related_posts):
    """
    Build the final article HTML:
    1. Affiliate disclosure
    2. Introduction (first paragraph — already in content)
    3. Table of Contents
    4. Rest of content with anchor IDs on H2s
    5. Internal links box
    """
    content = optimized["content"]

    # Inject anchor IDs into H2 headings
    content = inject_anchors_into_headings(content)

    # Split off first paragraph for TOC placement
    first_p_match = re.search(r'(<p>.*?</p>)', content, re.DOTALL | re.IGNORECASE)
    if first_p_match:
        first_p = first_p_match.group(1)
        rest    = content[first_p_match.end():]
        toc     = build_toc(content)
        content = first_p + "\n" + toc + "\n" + rest
    else:
        toc = build_toc(content)
        if toc:
            content = toc + "\n" + content

    # Add internal links section before FAQ
    internal_links_html = build_internal_links_html(related_posts)
    if internal_links_html:
        # Insert before FAQ section if it exists
        faq_match = re.search(
            r'(<h2[^>]*>.*?[Ff][Aa][Qq].*?</h2>)',
            content, re.DOTALL | re.IGNORECASE
        )
        if faq_match:
            content = (
                content[:faq_match.start()]
                + internal_links_html + "\n"
                + content[faq_match.start():]
            )
        else:
            content += "\n" + internal_links_html

    # Prepend affiliate disclosure
    final = AFFILIATE_DISCLOSURE + "\n" + content
    return final


# ============================================================
#  📤  UPDATE POST
# ============================================================

def update_post(post_id, optimized, final_content, cat_ids, tag_ids):
    """
    Update the WordPress post with all optimized content.
    Writes to BOTH Rank Math AND Yoast meta fields for maximum compatibility.
    """
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
            "meta": {
                # ── Rank Math fields ──────────────────────
                "rank_math_focus_keyword":    optimized["focus_keyword"],
                "rank_math_description":      optimized["meta_description"],
                "rank_math_title":            optimized["title"],
                "rank_math_robots":           ["index", "follow"],
                # ── Yoast fields (fallback) ───────────────
                "_yoast_wpseo_focuskw":       optimized["focus_keyword"],
                "_yoast_wpseo_metadesc":      optimized["meta_description"],
                # ── AIOSEO fields (fallback) ─────────────
                "_aioseop_description":       optimized["meta_description"],
                "_aioseop_keywords":          ", ".join(optimized["tags"]),
            },
        },
    )


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport SEO Optimizer v3")
    parser.add_argument("--limit",   type=int, default=None)
    parser.add_argument("--post-id", type=int, default=None)
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — SEO Optimizer v3 (Rank Math)")
    print("=" * 62)

    # 1. Fetch categories
    print("\n[1] Fetching WordPress categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 2. Fetch all post titles/URLs for internal linking
    print("\n[2] Fetching all post titles for internal linking...")
    all_post_refs = fetch_all_post_titles_and_urls()
    print(f"    Found {len(all_post_refs)} English posts for internal links.")

    # 3. Fetch posts to optimize
    print("\n[3] Fetching posts to optimize...")
    if args.post_id:
        posts = [fetch_single_post(args.post_id)]
        print(f"    Single post mode: ID {args.post_id}")
    else:
        posts = fetch_all_english_posts()
        if args.limit:
            posts = posts[:args.limit]
        print(f"    Will optimize {len(posts)} articles.")

    if not posts:
        print("    No posts found.")
        return

    # 4. Optimize loop
    print(f"\n[4] Starting optimization...")
    print("=" * 62)

    results = {"success": [], "failed": []}
    total   = len(posts)

    for i, post in enumerate(posts, 1):
        post_id           = post["id"]
        title             = post["title"]["rendered"]
        wc                = word_count(post["content"]["rendered"])
        is_short          = wc < MIN_WORD_COUNT
        featured_media_id = post.get("featured_media") or None

        print(f"\n[{i}/{total}] Post ID {post_id}")
        print(f"  Title : {title[:65]}")
        print(f"  Words : {wc} {'— SHORT, will expand' if is_short else '— OK'}")

        try:
            # Find related posts for internal linking
            related = find_related_posts(post_id, title, all_post_refs)
            print(f"  Internal links: {len(related)} related posts found")

            # Rewrite with Claude
            print("  Rewriting with Claude...")
            optimized = rewrite_article(post, is_short, related)

            new_wc = word_count(optimized["content"])
            print(f"  New title    : {optimized['title'][:65]}")
            print(f"  New slug     : {optimized['slug'][:60]}")
            print(f"  Focus KW     : {optimized['focus_keyword']}")
            print(f"  Meta desc    : {len(optimized['meta_description'])} chars")
            print(f"  New words    : {new_wc}")
            print(f"  Category     : {optimized['categories']}")

            # Assemble final content (disclosure + TOC + content + internal links)
            final_content = assemble_content(optimized, related)

            # Resolve categories + tags
            cat_ids = resolve_category_ids(optimized["categories"], wp_cat_map)
            tag_ids = sync_tags(optimized["tags"])

            # Update post
            updated = update_post(post_id, optimized, final_content, cat_ids, tag_ids)
            print(f"  Updated : {updated['link']}")

            # Update featured image alt text
            if featured_media_id:
                update_featured_image_alt(
                    featured_media_id,
                    optimized["focus_keyword"],
                    optimized["title"],
                )
                print(f"  Image alt text updated with focus keyword.")

            results["success"].append({
                "id":        post_id,
                "title":     optimized["title"],
                "url":       updated["link"],
                "old_words": wc,
                "new_words": new_wc,
                "keyword":   optimized["focus_keyword"],
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            results["failed"].append({
                "id":    post_id,
                "title": title,
                "error": str(e),
            })

        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s...")
            time.sleep(DELAY_BETWEEN)

    # 5. Summary
    print("\n" + "=" * 62)
    print("  OPTIMIZATION COMPLETE")
    print("=" * 62)
    print(f"  Total   : {total}")
    print(f"  Success : {len(results['success'])}")
    print(f"  Failed  : {len(results['failed'])}")

    if results["success"]:
        print("\n  Updated:")
        for r in results["success"]:
            print(f"  [{r['id']}] {r['title'][:55]}")
            print(f"         KW: {r['keyword']}")
            print(f"         {r['old_words']}w → {r['new_words']}w")
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
