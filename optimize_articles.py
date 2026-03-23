"""
GermanySupport.de — SEO Optimizer & Article Rewriter v2
========================================================
Loops through all published English articles, rewrites and
expands each one with Claude, then updates them in WordPress.

What it does per article:
  - Rewrites with accurate 2025 information
  - Expands short articles to 1200-1800 words minimum
  - Improves title, meta description, heading structure
  - Ensures focus keyword in first paragraph + H2 headings
  - Adds FAQ section at the end (helps Google featured snippets)
  - Strengthens referral link placement
  - Adds affiliate disclosure notice at the top
  - Updates tags, focus keyword, categories

Usage:
  python optimize_articles.py                  # optimize all articles
  python optimize_articles.py --limit 5        # first 5 only (test)
  python optimize_articles.py --post-id 123    # single post by ID
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
MIN_WORD_COUNT  = 1200   # Articles below this get fully expanded
DELAY_BETWEEN   = 10     # Seconds between articles (rate limit safety)
CURRENT_YEAR    = 2025

# ============================================================
#  📢  AFFILIATE DISCLOSURE NOTICE
#  Added to the top of every article automatically.
# ============================================================
AFFILIATE_DISCLOSURE = """<div style="background:#f8f9fa;border-left:4px solid #0073aa;padding:12px 16px;margin-bottom:24px;font-size:14px;line-height:1.6;">
<strong>Disclosure:</strong> This article contains affiliate links. If you click on a link and make a purchase or sign up, we may earn a small commission at no extra cost to you. We only recommend services we believe are genuinely useful for expats in Germany. <a href="/affiliate-disclosure/" style="color:#0073aa;">Read our full affiliate disclosure.</a>
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
    """Strip HTML tags to get plain text."""
    return re.sub(r"<[^>]+>", " ", html or "")


def word_count(html):
    return len(strip_html(html).split())


# ============================================================
#  🧹  ROBUST JSON PARSER
# ============================================================

def parse_claude_json(raw_text):
    """
    Parse JSON from Claude response with multiple fallback strategies.
    Handles special characters, German umlauts, malformed output.
    """
    text = raw_text.strip()
    # Remove markdown fences
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*",     "", text)
    text = re.sub(r"```$",        "", text).strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract JSON object with regex
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Strategy 3: fix common issues
    fixed = text
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)           # trailing commas
    fixed = fixed.replace('\u201c', '"').replace('\u201d', '"')  # smart quotes
    fixed = fixed.replace('\u2018', "'").replace('\u2019', "'")
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Strategy 4: ask Claude to repair its output
    print("  JSON malformed — asking Claude to repair...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    repair = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "The following JSON is malformed. Fix it and return ONLY "
                "valid JSON, no markdown fences, no explanation:\n\n"
                + text[:3000]
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
    """
    Fetch all published posts. We treat posts without /de/ in
    their URL as English (same logic as translator script).
    """
    posts = []
    page  = 1
    print("  Fetching published posts...")
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={
                "per_page": 20,
                "page":     page,
                "status":   "publish",
                "_fields":  "id,title,slug,content,excerpt,tags,categories,link,lang",
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
            # Skip German posts
            if lang == "de" or "/de/" in link:
                continue
            posts.append(post)

        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total_pages} — {len(posts)} English posts so far...")
        if page >= total_pages:
            break
        page += 1
    return posts


def fetch_single_post(post_id):
    return wp_request("GET", f"posts/{post_id}")


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
            print(f"    Category fuzzy match: '{name}' → '{best_key}'")
        else:
            print(f"    WARNING: Could not match category '{name}' — skipping.")
    if not ids:
        fallback = "living in germany"
        if fallback in wp_cat_map:
            ids.append(wp_cat_map[fallback])
            print(f"    Category fallback: 'Living in Germany'")
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

def rewrite_article(post, is_short):
    client     = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    title      = post["title"]["rendered"]
    current_html = post["content"]["rendered"]
    current_text = strip_html(current_html)
    wc           = word_count(current_html)
    links_str    = "\n".join([f"- {k}: {v}" for k, v in REFERRAL_LINKS.items()])
    cats_str     = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    if is_short:
        length_instruction = (
            f"The current article is only ~{wc} words — too short. "
            f"You MUST expand it to at least {MIN_WORD_COUNT} words with "
            f"genuinely useful detail. Add more sections, step-by-step "
            f"instructions, cost comparisons, practical tips, and examples. "
            f"Every sentence must add real value — no filler or padding."
        )
    else:
        length_instruction = (
            f"The current article is ~{wc} words. Keep it at a similar "
            f"or greater length. Do not shorten it."
        )

    system_prompt = f"""
You are an expert SEO content writer specialising in practical guides
for expats living in Germany. Today is {CURRENT_YEAR}.

Your task: fully rewrite and SEO-optimize an existing article.

REWRITE RULES:
1. Update ALL information to be accurate and current as of {CURRENT_YEAR}
   (new laws, current fees, latest providers, updated requirements)
2. {length_instruction}
3. Improve the title — more click-worthy and keyword-rich
4. Write a compelling meta description of EXACTLY 150-155 characters
5. Focus keyword must appear in:
   - The very first paragraph (first 100 words)
   - At least 2 H2 headings
   - Naturally throughout the body (not keyword-stuffed)
6. Use clear H2 and H3 heading structure throughout
7. Add a FAQ section at the end with 5-6 questions and detailed answers
   (FAQs help rank for Google featured snippets — very important)
8. Embed referral/affiliate links naturally where relevant
   Use: <a href="URL" target="_blank" rel="nofollow sponsored">Link text</a>
   Only embed links directly relevant to the surrounding content
9. Assign 1-2 categories from the ALLOWED list only
10. Provide 10-15 relevant SEO tags

IMPORTANT — JSON OUTPUT RULES:
- All quotes inside the content field MUST be escaped: \" not "
- No smart/curly quotes anywhere
- No unescaped newlines inside JSON string values — use \\n
- The JSON must be complete and valid

CATEGORY RULES — pick ONLY from this list, exact names:
{cats_str}

Output ONLY valid JSON, no markdown fences, no extra text:
{{
  "title": "Improved article title",
  "slug": "url-friendly-slug",
  "meta_description": "Exactly 150-155 char meta description",
  "focus_keyword": "main SEO keyword phrase",
  "tags": ["tag1", "tag2"],
  "categories": ["Exact Category Name"],
  "content": "Full rewritten HTML — all quotes escaped"
}}
"""

    user_prompt = f"""
Rewrite and SEO-optimize this existing article for expats in Germany.

CURRENT TITLE: {title}
CURRENT WORD COUNT: ~{wc} words
CURRENT CONTENT:
{current_text[:5500]}

Available referral/affiliate links — embed naturally where relevant:
{links_str}

Remember:
- Update everything to {CURRENT_YEAR}
- {"EXPAND significantly — article is too short" if is_short else "Keep or increase length"}
- Add FAQ section at the end
- Output ONLY the raw JSON object
- Escape all quotes inside the content field
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    return parse_claude_json(response.content[0].text)


# ============================================================
#  📝  UPDATE POST IN WORDPRESS
# ============================================================

def update_post(post_id, optimized, cat_ids, tag_ids):
    """
    Update the existing post with rewritten content.
    Prepends the affiliate disclosure notice automatically.
    """
    content_with_disclosure = AFFILIATE_DISCLOSURE + "\n" + optimized["content"]

    return wp_request(
        "POST",
        f"posts/{post_id}",
        json={
            "title":      optimized["title"],
            "slug":       optimized["slug"],
            "content":    content_with_disclosure,
            "excerpt":    optimized["meta_description"],
            "tags":       tag_ids,
            "categories": cat_ids,
            "meta": {
                "_yoast_wpseo_metadesc": optimized["meta_description"],
                "_yoast_wpseo_focuskw":  optimized["focus_keyword"],
                "_aioseop_description":  optimized["meta_description"],
                "_aioseop_keywords":     ", ".join(optimized["tags"]),
            },
        },
    )


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport SEO Optimizer v2")
    parser.add_argument("--limit",   type=int, default=None,
                        help="Max number of articles to process")
    parser.add_argument("--post-id", type=int, default=None,
                        help="Optimize a single post by ID")
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — SEO Optimizer & Rewriter v2")
    print("=" * 62)

    # 1. Fetch categories
    print("\n[1] Fetching WordPress categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 2. Fetch posts
    print("\n[2] Fetching English posts to optimize...")
    if args.post_id:
        posts = [fetch_single_post(args.post_id)]
        print(f"    Single post mode: ID {args.post_id}")
    else:
        posts = fetch_all_english_posts()
        if args.limit:
            posts = posts[:args.limit]
        print(f"    Will optimize {len(posts)} articles.")

    if not posts:
        print("    No posts found to optimize.")
        return

    # 3. Process each article
    print(f"\n[3] Starting optimization...")
    print("=" * 62)

    results = {"success": [], "failed": []}
    total   = len(posts)

    for i, post in enumerate(posts, 1):
        post_id  = post["id"]
        title    = post["title"]["rendered"]
        wc       = word_count(post["content"]["rendered"])
        is_short = wc < MIN_WORD_COUNT

        print(f"\n[{i}/{total}] Post ID {post_id}")
        print(f"  Title : {title[:65]}")
        print(f"  Words : {wc} {'— SHORT, will expand' if is_short else '— OK'}")

        try:
            # Rewrite with Claude
            print("  Rewriting with Claude...")
            optimized = rewrite_article(post, is_short)

            new_wc = word_count(optimized["content"])
            print(f"  New title : {optimized['title'][:65]}")
            print(f"  New words : {new_wc}")
            print(f"  Focus KW  : {optimized['focus_keyword']}")
            print(f"  Category  : {optimized['categories']}")
            print(f"  Tags      : {', '.join(optimized['tags'][:4])} ...")

            # Resolve categories + sync tags
            cat_ids = resolve_category_ids(optimized["categories"], wp_cat_map)
            tag_ids = sync_tags(optimized["tags"])

            # Update post in WordPress
            updated = update_post(post_id, optimized, cat_ids, tag_ids)
            print(f"  Updated   : {updated['link']}")

            results["success"].append({
                "id":        post_id,
                "title":     optimized["title"],
                "url":       updated["link"],
                "old_words": wc,
                "new_words": new_wc,
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

    # 4. Summary
    print("\n" + "=" * 62)
    print("  OPTIMIZATION COMPLETE")
    print("=" * 62)
    print(f"  Total    : {total}")
    print(f"  Success  : {len(results['success'])}")
    print(f"  Failed   : {len(results['failed'])}")

    if results["success"]:
        print("\n  Updated articles:")
        for r in results["success"]:
            print(f"  [{r['id']}] {r['title'][:50]}")
            print(f"         {r['old_words']} words → {r['new_words']} words")
            print(f"         {r['url']}")

    if results["failed"]:
        print("\n  Failed (fix manually or re-run):")
        for r in results["failed"]:
            print(f"  [{r['id']}] {r['title'][:55]}")
            print(f"         {r['error'][:120]}")

    print("=" * 62)

    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
