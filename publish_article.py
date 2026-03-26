"""
GermanySupport.de — AutoBlogger
================================
Imports shared config from config.py (single source of truth).
Reads all credentials from environment variables (GitHub Secrets).

Schedule: Monday + Thursday at 9am UTC via autoblog.yml
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

# Import shared config
from config import (
    CURRENT_YEAR,
    ALLOWED_CATEGORIES,
    REFERRAL_LINKS,
    get_relevant_links,
    format_links_for_prompt,
    TAPTAP_PROMO_TEXT,
)

# ============================================================
#  🔑  CREDENTIALS
# ============================================================
WP_URL        = os.environ["WP_URL"].rstrip("/")
WP_USER       = os.environ["WP_USER"]
WP_APP_PASS   = os.environ["WP_APP_PASS"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]
PEXELS_KEY    = os.environ["PEXELS_KEY"]

# ============================================================
#  🌱  SEED TOPIC POOL
# ============================================================
SEED_TOPICS = [
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
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

HEADERS = build_auth_headers()


def wp_request(method, endpoint, **kwargs):
    url = f"{WP_URL}/wp-json/wp/v2/{endpoint}"
    r   = requests.request(method, url, headers=HEADERS, **kwargs)
    if not r.ok:
        raise Exception(f"WP API error {r.status_code}: {r.text[:400]}")
    return r.json()


def fetch_all_post_titles():
    titles, page = [], 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts", headers=HEADERS,
            params={"per_page": 100, "page": page, "status": "publish",
                    "_fields": "title,slug"})
        if r.status_code == 400: break
        r.raise_for_status()
        batch = r.json()
        if not batch: break
        for post in batch:
            titles.append(post["title"]["rendered"].lower())
        if page >= int(r.headers.get("X-WP-TotalPages", 1)): break
        page += 1
    return titles


def fetch_wp_categories():
    cat_map, page = {}, 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories", headers=HEADERS,
            params={"per_page": 100, "page": page, "_fields": "id,name"})
        if r.status_code == 400: break
        r.raise_for_status()
        for cat in r.json():
            cat_map[cat["name"].lower()] = cat["id"]
        if page >= int(r.headers.get("X-WP-TotalPages", 1)): break
        page += 1
    return cat_map


def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def topic_already_covered(topic, existing_titles, threshold=0.55):
    topic_words = set(re.findall(r"\b\w{4,}\b", topic.lower()))
    for title in existing_titles:
        if similarity(topic, title) >= threshold:
            return True, title
        title_words = set(re.findall(r"\b\w{4,}\b", title))
        if topic_words and title_words:
            if len(topic_words & title_words) / len(topic_words) >= 0.60:
                return True, title
    return False, None


def pick_from_pool(pool, existing_titles):
    shuffled = pool.copy()
    random.shuffle(shuffled)
    skipped = []
    for topic in shuffled:
        covered, matched = topic_already_covered(topic, existing_titles)
        if covered:
            skipped.append((topic, matched))
        else:
            return topic, skipped
    return None, skipped


def generate_new_topics(existing_titles, count=20):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    sample = existing_titles[:80]
    existing_str = "\n".join(f"- {t}" for t in sample)
    prompt = f"""
You are an SEO strategist for a website helping expats in Germany (germanysupport.de).
Generate exactly {count} NEW article topic ideas for expats in Germany.
NOT similar to already published articles below.
Cover: banking, insurance, taxes, housing, mobile/internet, utilities,
healthcare, bureaucracy, transport, work, daily life, culture shock,
language tips, childcare, schools, social benefits, retirement, side hustles,
freelancing, online shopping, public transport, German food, expat communities.

Already published:
{existing_str}

Output ONLY a valid JSON array of {count} strings. No markdown.
"""
    print("  Asking Claude for new topics...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=1500,
        messages=[{"role": "user", "content": prompt}])
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$", "", raw).strip()
    topics = json.loads(raw)
    print(f"  Generated {len(topics)} new topic ideas.")
    return topics


def pick_fresh_topic(existing_titles):
    print("  Checking seed pool...")
    topic, skipped = pick_from_pool(SEED_TOPICS, existing_titles)
    if topic:
        print(f"  Found fresh seed topic ({len(skipped)} seeds covered).")
        return topic, "seed"

    print(f"  All {len(SEED_TOPICS)} seeds covered. Generating AI topics...")
    for attempt in range(1, 6):
        print(f"  AI attempt {attempt}/5...")
        new_topics = generate_new_topics(existing_titles, count=20)
        topic, _   = pick_from_pool(new_topics, existing_titles)
        if topic:
            print(f"  Found fresh AI topic on attempt {attempt}.")
            return topic, "ai-generated"
        print("  All generated topics overlapped. Retrying...")

    print("ERROR: No fresh topics found.")
    sys.exit(1)


def generate_article(topic):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    # Get relevant links for this topic
    rel_links = get_relevant_links(topic, "")
    links_str = format_links_for_prompt(rel_links)
    cats_str  = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    system_prompt = f"""
You are an expert SEO content writer for an expat guide website about Germany.
Year: {CURRENT_YEAR}.

Your articles are:
- Comprehensive (1200-1800 words)
- Written in clear, friendly English
- Structured with H2 and H3 headings, short paragraphs
- Packed with actionable, practical advice
- Naturally optimised for long-tail keywords
- Including a meta description (max 155 chars) and 10-15 SEO tags
- Including an image search keyword for the featured image
- Containing naturally placed referral links

SPECIAL RULE for TapTap Send:
Always mention promo code IQBAL12 and the €10-€15 bonus for sending €50+.
Example: "{TAPTAP_PROMO_TEXT}"

CATEGORY RULES — pick 1-2, EXACT names only:
{cats_str}

Output ONLY valid JSON, no markdown fences:
{{
  "title": "Article title {CURRENT_YEAR}",
  "slug": "url-friendly-slug",
  "meta_description": "155-char meta description",
  "focus_keyword": "main SEO keyword",
  "tags": ["tag1", "tag2"],
  "categories": ["Exact Category Name"],
  "image_search_query": "pexels search term (2-4 words)",
  "content": "Full HTML body using <h2>, <h3>, <p>, <ul>, <li>, <a> tags"
}}
"""

    user_prompt = f"""
Write a comprehensive SEO-optimised article for expats in Germany:
TOPIC: {topic}
YEAR: {CURRENT_YEAR}

Available referral links — embed naturally where relevant:
{links_str}

Output ONLY the raw JSON object.
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}])

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$", "", raw).strip()
    return json.loads(raw)


def fetch_pexels_image(query):
    headers = {"Authorization": PEXELS_KEY}
    params  = {"query": query, "per_page": 5, "orientation": "landscape"}
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
    return requests.get(photo["src"]["large2x"]).content, photo["photographer"], photo["src"]["large2x"]


def upload_image(img_bytes, slug, title, photographer):
    safe_slug   = re.sub(r"[^a-z0-9-]", "-", slug)[:60]
    media_hdrs  = dict(HEADERS)
    media_hdrs["Content-Type"]        = "image/jpeg"
    media_hdrs["Content-Disposition"] = f'attachment; filename="{safe_slug}.jpg"'
    r = requests.post(f"{WP_URL}/wp-json/wp/v2/media", headers=media_hdrs, data=img_bytes)
    if not r.ok:
        raise Exception(f"Media upload failed {r.status_code}: {r.text[:300]}")
    media_id = r.json()["id"]
    requests.post(f"{WP_URL}/wp-json/wp/v2/media/{media_id}", headers=HEADERS,
                  json={"alt_text": title, "caption": f"Photo by {photographer} on Pexels"})
    return media_id


def resolve_category_ids(chosen_categories, wp_cat_map):
    ids = []
    for name in chosen_categories:
        nl = name.lower()
        if nl in wp_cat_map:
            ids.append(wp_cat_map[nl]); continue
        best_score, best_key = 0, None
        for k in wp_cat_map:
            s = SequenceMatcher(None, nl, k).ratio()
            if s > best_score: best_score, best_key = s, k
        if best_key and best_score >= 0.60:
            ids.append(wp_cat_map[best_key])
            print(f"      Category fuzzy: '{name}' → '{best_key}'")
        else:
            print(f"      WARNING: no match for '{name}'")
    if not ids:
        fb = "living in germany"
        if fb in wp_cat_map: ids.append(wp_cat_map[fb])
    return ids


def sync_tags(tag_names):
    tag_ids = []
    for name in tag_names:
        try:
            t = wp_request("POST", "tags", json={"name": name})
            tag_ids.append(t["id"])
        except Exception:
            search = requests.get(f"{WP_URL}/wp-json/wp/v2/tags", headers=HEADERS,
                                  params={"search": name, "per_page": 1}).json()
            if search: tag_ids.append(search[0]["id"])
    return tag_ids


def publish_post(article, featured_id, cat_ids, tag_ids, photographer):
    footer = (
        f'<hr/><p><em>Featured image by <strong>{photographer}</strong> via '
        f'<a href="https://www.pexels.com" target="_blank" rel="nofollow">Pexels</a>.</em></p>'
    )
    return wp_request("POST", "posts", json={
        "title":          article["title"],
        "slug":           article["slug"],
        "content":        article["content"] + footer,
        "status":         "publish",
        "featured_media": featured_id,
        "tags":           tag_ids,
        "categories":     cat_ids,
        "excerpt":        article["meta_description"],
        "meta": {
            "rank_math_focus_keyword": article["focus_keyword"],
            "rank_math_description":   article["meta_description"],
            "_yoast_wpseo_focuskw":    article["focus_keyword"],
            "_yoast_wpseo_metadesc":   article["meta_description"],
        },
    })


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    print("=" * 62)
    print(f"  GermanySupport.de — AutoBlogger ({CURRENT_YEAR})")
    print("=" * 62)

    print("\n[1/7] Fetching existing posts...")
    existing_titles = fetch_all_post_titles()
    print(f"      Found {len(existing_titles)} published posts.")

    print("\n[2/7] Fetching WordPress categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"      Found {len(wp_cat_map)} categories.")

    print("\n[3/7] Picking an uncovered topic...")
    chosen_topic, source = pick_fresh_topic(existing_titles)
    print(f"      Source : {source}")
    print(f"      Topic  : {chosen_topic}")

    print("\n[4/7] Generating article with Claude...")
    article = generate_article(chosen_topic)
    print(f"      Title    : {article['title']}")
    print(f"      Slug     : {article['slug']}")
    print(f"      Focus KW : {article['focus_keyword']}")
    print(f"      Tags     : {', '.join(article['tags'][:5])} ...")
    print(f"      Words    : ~{len(article['content'].split())}")

    print(f"\n[5/7] Fetching image: '{article['image_search_query']}'...")
    img_bytes, photographer, img_url = fetch_pexels_image(article["image_search_query"])
    print(f"      Photographer: {photographer}")

    print("\n[6/7] Uploading featured image...")
    featured_id = upload_image(img_bytes, article["slug"], article["title"], photographer)
    print(f"      Media ID: {featured_id}")

    print("\n[7/7] Publishing post...")
    tag_ids = sync_tags(article["tags"])
    cat_ids = resolve_category_ids(article.get("categories", ["Living in Germany"]), wp_cat_map)
    post    = publish_post(article, featured_id, cat_ids, tag_ids, photographer)

    print()
    print("=" * 62)
    print("  ARTICLE PUBLISHED!")
    print("=" * 62)
    print(f"  Title       : {post['title']['rendered']}")
    print(f"  URL         : {post['link']}")
    print(f"  Post ID     : {post['id']}")
    print(f"  Topic source: {source}")
    print(f"  Image       : {img_url}")
    print("=" * 62)


if __name__ == "__main__":
    main()