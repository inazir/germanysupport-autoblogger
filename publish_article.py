"""
GermanySupport.de — AutoBlogger
================================
Standalone script for automated article publishing via GitHub Actions.
Reads all credentials from environment variables (set as GitHub Secrets).

Schedule: runs twice a week (Monday + Thursday) via .github/workflows/autoblog.yml
"""

import os
import re
import json
import random
import base64
import sys
from difflib import SequenceMatcher

import anthropic
import requests

# ============================================================
#  🔑  CREDENTIALS  — loaded from environment variables
# ============================================================
WP_URL        = os.environ["WP_URL"].rstrip("/")
WP_USER       = os.environ["WP_USER"]
WP_APP_PASS   = os.environ["WP_APP_PASS"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]
PEXELS_KEY    = os.environ["PEXELS_KEY"]

# ============================================================
#  📌  AFFILIATE / REFERRAL LINKS
# ============================================================
REFERRAL_LINKS = {
    # BANKING
    "N26 Bank":               "https://bit.ly/3IXPFSh",
    "C24 Bank":               "https://bit.ly/3EED0Uc",
    "Commerzbank":            "https://bit.ly/cmrzbnk",
    "Advanzia Mastercard":    "https://bit.ly/4hKu4ul",
    "American Express":       "https://bit.ly/3wfHv0e",
    "Credit Card Comparison": "https://bit.ly/41xi8Ht",
    "Trade Republic":         "https://bit.ly/3Z5B13n",
    "Metro Business":         "https://bit.ly/3MnUiFV",
    # INSURANCE
    "Liability Insurance":    "https://bit.ly/3ik93KM",
    "Getsafe Haftpflicht":    "https://bit.ly/3IBfR1l",
    "HUK24 Car Insurance":    "https://bit.ly/3tveWdm",
    "Car Insurance Compare":  "https://bit.ly/3IXJxXD",
    # TAX & FINANCE
    "SteuerGo":               "https://bit.ly/3XDNBW8",
    "WISO Steuer":            "https://bit.ly/3NLm1BE",
    # INTERNET & MOBILE
    "Verivox DSL":            "https://bit.ly/474daFa",
    "DSL Check24":            "https://bit.ly/3MFz9WH",
    "Klarmobil":              "https://bit.ly/4paMQ2e",
    "Check24 Mobile":         "https://bit.ly/3BVAAiI",
    "Congstar Mobile":        "https://bit.ly/3iVS0mb",
    # UTILITIES
    "Electricity Provider":   "https://bit.ly/chk24strm",
    "Gas Provider":           "https://bit.ly/gasbgg",
    # TRAVEL
    "Check24 Travel":         "https://bit.ly/bgstrip",
    "Check24 Car Rental":     "https://bit.ly/mtwgn",
    # MONEY TRANSFER
    "ACE Money Transfer":     "https://bit.ly/3qq18Ab",
    "TapTap Send":            "https://bit.ly/3qj6JYG",
    # CASHBACK
    "Shoop Cashback":         "https://bit.ly/3r3tW1p",
    "iGraal Cashback":        "https://bit.ly/38lWA7P",
}

# ============================================================
#  📝  TOPIC POOL  (32 high-demand, low-competition topics)
# ============================================================
TOPIC_POOL = [
    # BANKING & FINANCE
    "How to open a bank account in Germany as a foreigner in 2025",
    "Best free bank accounts in Germany for expats: N26 vs C24 vs Commerzbank",
    "How to get a credit card in Germany with no credit history",
    "How to invest in ETFs and stocks in Germany as an expat",
    "Trade Republic vs DKB vs Scalable Capital: best broker for expats in Germany",
    "How to build a credit score (Schufa) in Germany from scratch",
    "Sending money home from Germany: cheapest international transfer services",
    "Best cashback apps and websites in Germany to save money",
    # INSURANCE
    "How to get liability insurance (Haftpflichtversicherung) in Germany",
    "Car insurance in Germany for foreigners: a complete guide",
    "Public vs private health insurance in Germany: which is better for expats?",
    "What is Hausratversicherung and do expats in Germany really need it?",
    "How to get dental insurance in Germany as an expat",
    # TAX & LEGAL
    "How to file taxes in Germany as an expat (Steuererklärung guide)",
    "Tax classes in Germany explained: which Steuerklasse should you choose?",
    "Freelancer taxes in Germany: complete guide for self-employed expats",
    "How to get a tax ID (Steueridentifikationsnummer) in Germany",
    "Understanding your German payslip: Lohnabrechnung explained",
    # INTERNET & MOBILE
    "Best prepaid SIM cards in Germany for expats in 2025",
    "How to compare and switch internet providers in Germany",
    "Cheapest mobile phone plans in Germany: complete comparison",
    "How to set up internet at home in Germany: step-by-step guide",
    # UTILITIES & LIVING
    "Cheapest electricity providers in Germany 2025: how to switch and save",
    "How to switch gas providers in Germany and save money",
    "How to register your address in Germany (Anmeldung): step-by-step guide",
    "How to find an apartment in Germany as a foreigner",
    "Understanding a German rental contract (Mietvertrag): what expats must know",
    # WORK & BUREAUCRACY
    "How to get a work visa in Germany: complete guide for non-EU citizens",
    "How to apply for permanent residency (Niederlassungserlaubnis) in Germany",
    "German driving licence for foreigners: how to convert or get a new one",
    "How to claim unemployment benefits (Arbeitslosengeld) in Germany",
    "How to bring your family to Germany: family reunification visa guide",
]

# ============================================================
#  🔧  HELPERS
# ============================================================

def build_auth_headers():
    credentials = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }

HEADERS = build_auth_headers()


def wp_request(method, endpoint, **kwargs):
    url = f"{WP_URL}/wp-json/wp/v2/{endpoint}"
    r = requests.request(method, url, headers=HEADERS, **kwargs)
    if not r.ok:
        raise Exception(f"WP API error {r.status_code}: {r.text[:400]}")
    return r.json()


def fetch_all_post_titles():
    """Fetch ALL published post titles from WordPress (handles pagination)."""
    titles = []
    page = 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={"per_page": 100, "page": page, "status": "publish", "_fields": "title,slug"},
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for post in batch:
            titles.append(post["title"]["rendered"].lower())
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break
        page += 1
    return titles


def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def topic_already_covered(topic, existing_titles, threshold=0.55):
    """Returns (True, matched_title) if a similar post already exists."""
    topic_words = set(re.findall(r"\b\w{4,}\b", topic.lower()))
    for title in existing_titles:
        if similarity(topic, title) >= threshold:
            return True, title
        title_words = set(re.findall(r"\b\w{4,}\b", title))
        if topic_words and title_words:
            overlap = len(topic_words & title_words) / len(topic_words)
            if overlap >= 0.60:
                return True, title
    return False, None


def pick_fresh_topic(existing_titles):
    """Shuffle pool and return first topic not already covered."""
    shuffled = TOPIC_POOL.copy()
    random.shuffle(shuffled)
    skipped = []
    for topic in shuffled:
        covered, matched = topic_already_covered(topic, existing_titles)
        if covered:
            skipped.append((topic, matched))
            print(f"  SKIP: '{topic[:70]}'")
            print(f"        Similar to: '{matched[:70]}'")
        else:
            return topic, skipped
    return None, skipped


def generate_article(topic):
    """Call Claude API and return parsed article dict."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    links_str = "\n".join([f"- {name}: {url}" for name, url in REFERRAL_LINKS.items()])

    system_prompt = """
You are an expert SEO content writer specialising in practical guides for expats living in Germany.
Your articles are:
- Comprehensive (1200-1800 words)
- Written in clear, friendly English
- Structured with H2 and H3 headings
- Packed with actionable, practical advice
- Naturally optimised for long-tail keywords (include them in headings and body)
- Including a meta description (max 155 chars) and 10-15 SEO tags
- Including an image search keyword for the featured image
- Containing naturally placed referral/affiliate links from the provided list
  (HTML <a> tags, target=_blank, rel=nofollow) — only embed where directly relevant

Output ONLY valid JSON in this exact format, no markdown fences, no extra text:
{
  "title": "Article title",
  "slug": "url-friendly-slug",
  "meta_description": "155-char meta description",
  "focus_keyword": "main SEO keyword",
  "tags": ["tag1", "tag2"],
  "categories": ["Category Name"],
  "image_search_query": "pexels search term (2-4 words)",
  "content": "Full HTML article body using <h2>, <h3>, <p>, <ul>, <li>, <a> tags"
}
"""

    user_prompt = f"""
Write a comprehensive SEO-optimised article for expats in Germany on this topic:
TOPIC: {topic}

Available referral links — embed naturally where relevant:
{links_str}

Output ONLY the raw JSON object.
"""

    print("  Calling Claude API...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$", "", raw).strip()
    return json.loads(raw)


def fetch_pexels_image(query):
    """Returns (image_bytes, photographer_name, image_url)."""
    headers = {"Authorization": PEXELS_KEY}
    params = {"query": query, "per_page": 5, "orientation": "landscape"}
    r = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params)
    r.raise_for_status()
    data = r.json()
    if not data.get("photos"):
        fallback = query.split()[0]
        print(f"  No Pexels results for '{query}', retrying with '{fallback}'...")
        params["query"] = fallback
        r = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params)
        data = r.json()
    if not data.get("photos"):
        raise ValueError(f"No Pexels images found for: {query}")
    photo = data["photos"][0]
    img_url = photo["src"]["large2x"]
    photographer = photo["photographer"]
    img_bytes = requests.get(img_url).content
    return img_bytes, photographer, img_url


def upload_image(img_bytes, slug, title, photographer):
    """Upload image to WP media library, return media ID."""
    safe_slug = re.sub(r"[^a-z0-9-]", "-", slug)[:60]
    media_hdrs = dict(HEADERS)
    media_hdrs["Content-Type"] = "image/jpeg"
    media_hdrs["Content-Disposition"] = f'attachment; filename="{safe_slug}.jpg"'

    r = requests.post(f"{WP_URL}/wp-json/wp/v2/media", headers=media_hdrs, data=img_bytes)
    if not r.ok:
        raise Exception(f"Media upload failed {r.status_code}: {r.text[:300]}")
    media_data = r.json()
    media_id = media_data["id"]

    # Set alt text and caption
    requests.post(
        f"{WP_URL}/wp-json/wp/v2/media/{media_id}",
        headers=HEADERS,
        json={
            "alt_text": title,
            "caption": f"Photo by {photographer} on Pexels",
        },
    )
    return media_id


def sync_tags(tag_names):
    """Create or find tags, return list of IDs."""
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


def sync_categories(cat_names):
    """Create or find categories, return list of IDs."""
    cat_ids = []
    for name in (cat_names or ["Expat Guide"]):
        try:
            c = wp_request("POST", "categories", json={"name": name})
            cat_ids.append(c["id"])
        except Exception:
            search = requests.get(
                f"{WP_URL}/wp-json/wp/v2/categories",
                headers=HEADERS,
                params={"search": name, "per_page": 1},
            ).json()
            if search:
                cat_ids.append(search[0]["id"])
    return cat_ids


def publish_post(article, featured_id, tag_ids, cat_ids, photographer):
    """Create and publish the WordPress post."""
    footer = (
        f'<hr/><p><em>Featured image by <strong>{photographer}</strong> via '
        f'<a href="https://www.pexels.com" target="_blank" rel="nofollow">Pexels</a>.</em></p>'
    )
    return wp_request(
        "POST",
        "posts",
        json={
            "title":          article["title"],
            "slug":           article["slug"],
            "content":        article["content"] + footer,
            "status":         "publish",
            "featured_media": featured_id,
            "tags":           tag_ids,
            "categories":     cat_ids,
            "excerpt":        article["meta_description"],
            "meta": {
                "_yoast_wpseo_metadesc": article["meta_description"],
                "_yoast_wpseo_focuskw":  article["focus_keyword"],
                "_aioseop_description":  article["meta_description"],
                "_aioseop_keywords":     ", ".join(article["tags"]),
            },
        },
    )


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    print("=" * 62)
    print("  GermanySupport.de — AutoBlogger")
    print("=" * 62)

    # 1. Fetch existing posts
    print("\n[1/6] Fetching existing posts from WordPress...")
    existing_titles = fetch_all_post_titles()
    print(f"      Found {len(existing_titles)} published posts.")

    # 2. Pick a fresh topic
    print("\n[2/6] Picking an uncovered topic...")
    chosen_topic, skipped = pick_fresh_topic(existing_titles)
    if not chosen_topic:
        print("\nERROR: All topics in TOPIC_POOL have already been published!")
        print("Add new topics to TOPIC_POOL and redeploy.")
        sys.exit(1)
    print(f"      Selected: {chosen_topic}")

    # 3. Generate article with Claude
    print("\n[3/6] Generating article with Claude...")
    article = generate_article(chosen_topic)
    print(f"      Title    : {article['title']}")
    print(f"      Slug     : {article['slug']}")
    print(f"      Focus KW : {article['focus_keyword']}")
    print(f"      Tags     : {', '.join(article['tags'][:5])} ...")
    print(f"      Words    : ~{len(article['content'].split())}")

    # 4. Fetch featured image from Pexels
    print(f"\n[4/6] Fetching image from Pexels: '{article['image_search_query']}'...")
    img_bytes, photographer, img_url = fetch_pexels_image(article["image_search_query"])
    print(f"      Photographer: {photographer}")

    # 5. Upload image to WordPress
    print("\n[5/6] Uploading featured image to WordPress...")
    featured_id = upload_image(img_bytes, article["slug"], article["title"], photographer)
    print(f"      Media ID: {featured_id}")

    # 6. Publish post
    print("\n[6/6] Publishing post to WordPress...")
    tag_ids = sync_tags(article["tags"])
    cat_ids = sync_categories(article.get("categories"))
    post = publish_post(article, featured_id, tag_ids, cat_ids, photographer)

    # Summary
    print()
    print("=" * 62)
    print("  ARTICLE PUBLISHED SUCCESSFULLY!")
    print("=" * 62)
    print(f"  Title       : {post['title']['rendered']}")
    print(f"  URL         : {post['link']}")
    print(f"  Post ID     : {post['id']}")
    print(f"  Image       : {img_url}")
    print(f"  Photographer: {photographer}")
    if skipped:
        print(f"\n  Skipped {len(skipped)} already-covered topic(s).")
    remaining = len(TOPIC_POOL) - len(skipped) - 1
    print(f"  Topics remaining in pool: {remaining}")
    print("=" * 62)


if __name__ == "__main__":
    main()
