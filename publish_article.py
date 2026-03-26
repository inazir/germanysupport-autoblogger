"""
GermanySupport.de — AutoBlogger (Production)
=============================================
Features:
  - Dynamic referral links from WordPress API (config.py)
  - Duplicate detection: title similarity + slug check
  - High-conversion article strategy (money pages first)
  - TapTap IQBAL12 promo code
  - Auto-year
  - Structured logging

Usage:
  python publish_article.py
  python publish_article.py --topic "Custom topic here"
"""

import os
import re
import sys
import json
import random
import base64
import logging
import argparse
from difflib import SequenceMatcher
from datetime import datetime

import anthropic
import requests

from config import (
    CURRENT_YEAR,
    ALLOWED_CATEGORIES,
    get_relevant_links,
    fetch_referral_links,
    format_links_for_prompt,
    TAPTAP_PROMO_TEXT,
)

# ============================================================
#  📝  LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "logs", "publish.log"),
            encoding="utf-8",
        ) if os.path.isdir(os.path.join(os.path.dirname(__file__), "logs")) else logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ============================================================
#  🔑  CREDENTIALS
# ============================================================
WP_URL        = os.environ["WP_URL"].rstrip("/")
WP_USER       = os.environ["WP_USER"]
WP_APP_PASS   = os.environ["WP_APP_PASS"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]
PEXELS_KEY    = os.environ["PEXELS_KEY"]

# ============================================================
#  💎  HIGH-CONVERSION MONEY PAGES (prioritised topic pool)
#  These topics have high affiliate conversion potential.
#  They are tried first before the general seed pool.
# ============================================================
HIGH_CONVERSION_TOPICS = [
    # BANKING
    "Best Free Bank Accounts in Germany for Expats 2026: N26 vs C24 Comparison",
    "N26 vs C24 Bank: Which Is Better for Expats in Germany?",
    "Best Banks for Expats in Germany: Complete Guide 2026",
    "How to Open N26 Account in Germany: Step-by-Step Guide",
    # CREDIT CARDS
    "Best Credit Cards in Germany for Foreigners 2026",
    "Advanzia Mastercard Germany: Zero-Fee Credit Card Review",
    "Best No-Fee Credit Cards in Germany: Complete Comparison",
    # INSURANCE
    "Best Liability Insurance (Haftpflicht) in Germany: Top Providers Compared",
    "Cheapest Car Insurance in Germany 2026: How to Save Up to €850",
    "Best Legal Insurance (Rechtsschutz) in Germany for Expats",
    # INTERNET & MOBILE
    "Best DSL Internet Providers in Germany 2026: Prices & Speed",
    "Best SIM Cards and Mobile Plans in Germany for Expats 2026",
    "Telekom vs Vodafone vs O2: Which Mobile Network in Germany?",
    # UTILITIES
    "Cheapest Electricity Providers in Germany 2026: Switch and Save",
    "Verivox vs Check24: Which Comparison Portal Is Better in Germany?",
    # TRAVEL & TRANSPORT
    "Best Travel Deals and Booking Sites in Germany 2026",
    "Cheapest Car Rental in Germany: Complete Comparison Guide",
    # MONEY TRANSFER
    "Best Money Transfer Services from Germany 2026: Wise vs ACE vs TapTap",
    "TapTap Send Review 2026: Send Money Home from Germany Cheaply",
    "ACE Money Transfer Review: Sending Money from Germany",
    # INVESTMENT
    "Trade Republic vs Scalable Capital: Best Broker for Expats in Germany",
    "Best ETF Brokers in Germany for Beginners 2026",
    # CASHBACK
    "Best Cashback Apps and Websites in Germany 2026",
    "Shoop vs iGraal: Best Cashback Portal in Germany",
    # TAX
    "SteuerGo vs WISO: Best Tax Software for Expats in Germany",
    "How to Get a Tax Refund in Germany: Complete Guide 2026",
]

# ============================================================
#  🌱  GENERAL SEED TOPIC POOL
# ============================================================
SEED_TOPICS = [
    # BANKING & FINANCE
    "How to open a bank account in Germany as a foreigner",
    "How to invest in ETFs and stocks in Germany as an expat",
    "How to build a credit score (Schufa) in Germany from scratch",
    "Sending money home from Germany: cheapest international transfer services",
    "Best cashback apps and websites in Germany to save money",
    # INSURANCE
    "How to get liability insurance (Haftpflichtversicherung) in Germany",
    "Car insurance in Germany for foreigners: a complete guide",
    "Public vs private health insurance in Germany: which is better for expats?",
    "What is Hausratversicherung and do expats in Germany really need it?",
    # TAX & LEGAL
    "How to file taxes in Germany as an expat (Steuererklärung guide)",
    "Tax classes in Germany explained: which Steuerklasse should you choose?",
    "Freelancer taxes in Germany: complete guide for self-employed expats",
    "How to get a tax ID (Steueridentifikationsnummer) in Germany",
    "Understanding your German payslip: Lohnabrechnung explained",
    # INTERNET & MOBILE
    "Best prepaid SIM cards in Germany for expats",
    "How to compare and switch internet providers in Germany",
    "How to set up internet at home in Germany: step-by-step guide",
    # UTILITIES & LIVING
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
#  🔧  AUTH & HTTP
# ============================================================

def build_headers():
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PASS}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

HEADERS = build_headers()


def wp_request(method, endpoint, **kwargs):
    url = f"{WP_URL}/wp-json/wp/v2/{endpoint}"
    r   = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)
    if not r.ok:
        raise Exception(f"WP {r.status_code}: {r.text[:300]}")
    return r.json()


# ============================================================
#  🔍  DUPLICATE DETECTION
# ============================================================

def fetch_all_post_data():
    """Fetch all posts returning list of {id, title, slug, link}."""
    posts, page = [], 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts", headers=HEADERS,
            params={"per_page": 100, "page": page, "status": "publish",
                    "_fields": "id,title,slug,link"}, timeout=30)
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        if page >= int(r.headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
    return posts


def title_similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def keyword_overlap(a, b, min_word_len=4):
    words_a = set(re.findall(rf'\b\w{{{min_word_len},}}\b', a.lower()))
    words_b = set(re.findall(rf'\b\w{{{min_word_len},}}\b', b.lower()))
    if not words_a:
        return 0.0
    return len(words_a & words_b) / len(words_a)


def find_duplicate(topic, all_posts, sim_threshold=0.55, kw_threshold=0.60):
    """
    Check if a similar article already exists.
    Returns (True, existing_post) or (False, None).
    Checks:
      1. Title similarity (fuzzy string match)
      2. Keyword overlap (shared significant words)
      3. Slug match (exact slug already exists)
    """
    candidate_slug = re.sub(r'[^a-z0-9]+', '-',
                            topic.lower())[:80].strip('-')

    for post in all_posts:
        existing_title = post["title"]["rendered"]
        existing_slug  = post.get("slug", "")

        # Slug match
        if candidate_slug and existing_slug and \
           SequenceMatcher(None, candidate_slug, existing_slug).ratio() > 0.85:
            return True, post

        # Title similarity
        if title_similarity(topic, existing_title) >= sim_threshold:
            return True, post

        # Keyword overlap
        if keyword_overlap(topic, existing_title) >= kw_threshold:
            return True, post

    return False, None


# ============================================================
#  🎯  TOPIC SELECTION
# ============================================================

def pick_fresh_topic(all_posts, custom_topic=None):
    """
    Pick a fresh topic.
    Order: custom → high-conversion → general seeds → AI-generated.
    Returns (topic, source).
    """
    existing_titles = [p["title"]["rendered"] for p in all_posts]

    # Custom topic from CLI
    if custom_topic:
        is_dup, match = find_duplicate(custom_topic, all_posts)
        if is_dup:
            log.warning(f"Custom topic is similar to existing: '{match['title']['rendered']}'")
            log.warning("Publishing anyway (custom override).")
        return custom_topic, "custom"

    # Try high-conversion pool first
    log.info("Checking high-conversion money pages...")
    shuffled_hc = HIGH_CONVERSION_TOPICS.copy()
    random.shuffle(shuffled_hc)
    for topic in shuffled_hc:
        is_dup, _ = find_duplicate(topic, all_posts)
        if not is_dup:
            log.info(f"Found fresh high-conversion topic.")
            return topic, "high-conversion"

    # Try general seeds
    log.info("High-conversion pool exhausted. Trying general seeds...")
    shuffled_seed = SEED_TOPICS.copy()
    random.shuffle(shuffled_seed)
    for topic in shuffled_seed:
        is_dup, _ = find_duplicate(topic, all_posts)
        if not is_dup:
            log.info(f"Found fresh seed topic.")
            return topic, "seed"

    # AI generation
    log.info("All seeds covered. Generating AI topics...")
    for attempt in range(1, 6):
        log.info(f"AI topic generation attempt {attempt}/5...")
        new_topics = generate_new_topics(existing_titles, count=20)
        random.shuffle(new_topics)
        for topic in new_topics:
            is_dup, _ = find_duplicate(topic, all_posts)
            if not is_dup:
                log.info(f"Found fresh AI topic on attempt {attempt}.")
                return topic, "ai-generated"
        log.warning("All generated topics overlapped. Retrying...")

    log.error("No fresh topics found after all attempts.")
    sys.exit(1)


def generate_new_topics(existing_titles, count=20):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    sample = existing_titles[:80]
    existing_str = "\n".join(f"- {t}" for t in sample)
    prompt = f"""
You are an SEO strategist for germanysupport.de — a guide for expats in Germany.
Generate exactly {count} NEW article topic ideas.
Topics must be high-demand, low-competition, practical for expats.
NOT similar to already published articles below.
Focus on: banking, insurance, taxes, housing, mobile/internet, utilities,
healthcare, bureaucracy, transport, work, investments, cashback, deals.
Prioritize "comparison" and "best X" topics — they get high affiliate clicks.

Already published:
{existing_str}

Output ONLY a JSON array of {count} strings. No markdown.
"""
    r = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=1500,
        messages=[{"role": "user", "content": prompt}])
    raw = r.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$",        "", raw).strip()
    return json.loads(raw)


# ============================================================
#  ✍️  ARTICLE GENERATION
# ============================================================

def generate_article(topic, relevant_links):
    client    = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    links_str = format_links_for_prompt(relevant_links)
    cats_str  = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    system_prompt = f"""
You are an expert SEO content writer for germanysupport.de — an expat guide for Germany.
Year: {CURRENT_YEAR}.

ARTICLE STRUCTURE (high-conversion format):
1. Introduction (focus keyword in first sentence, explain what reader will learn)
2. Quick Summary Box (HTML table: key facts at a glance)
3. H2 sections with practical, detailed content
4. Comparison Table (HTML <table>) if the topic involves comparing options
5. Step-by-step instructions where relevant
6. Pros/Cons or Comparison sections
7. Strong CTA (call-to-action) sections near affiliate links
8. FAQ section (5-6 questions, Rank Math schema format)
9. Conclusion with summary and recommended action

RANK MATH SEO:
- Focus keyword in the very first sentence
- Focus keyword in title (near start), meta description (first 10 words)
- Focus keyword in at least 2 H2 headings
- ~1% keyword density
- Short paragraphs (2-4 sentences max)
- Slug under 60 chars

AFFILIATE LINKS:
- Embed naturally with strong CTAs like "Open a free account", "Compare rates now"
- Use: <a href="URL" target="_blank" rel="nofollow sponsored">CTA text</a>
- TapTap Send: ALWAYS mention promo code {TAPTAP_PROMO_TEXT}

CATEGORIES — 1-2, exact names:
{cats_str}

Output ONLY valid JSON, no markdown:
{{
  "title": "Keyword-rich Title {CURRENT_YEAR}",
  "slug": "keyword-slug-max-60",
  "meta_description": "Focus keyword first. Exactly 150-155 chars.",
  "focus_keyword": "exact keyword phrase",
  "tags": ["tag1","tag2","tag3","tag4","tag5"],
  "categories": ["Category Name"],
  "image_search_query": "2-4 word Pexels search",
  "content": "Full HTML — comparison tables, CTAs, FAQ schema, all affiliate links"
}}
"""

    user_prompt = f"""
Write a high-conversion SEO article for expats in Germany.
TOPIC: {topic}
YEAR: {CURRENT_YEAR}

Affiliate links (embed with strong CTAs):
{links_str}

Include comparison tables and/or step-by-step sections where relevant.
Output ONLY the raw JSON.
"""

    r = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}])

    raw = r.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```$",        "", raw).strip()
    return json.loads(raw)


# ============================================================
#  🖼️  PEXELS IMAGE
# ============================================================

def fetch_pexels_image(query):
    hdrs   = {"Authorization": PEXELS_KEY}
    params = {"query": query, "per_page": 5, "orientation": "landscape"}
    r = requests.get("https://api.pexels.com/v1/search",
                     headers=hdrs, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("photos"):
        fallback = query.split()[0]
        log.warning(f"No Pexels results for '{query}', retrying '{fallback}'")
        params["query"] = fallback
        r = requests.get("https://api.pexels.com/v1/search",
                         headers=hdrs, params=params, timeout=20)
        data = r.json()
    if not data.get("photos"):
        raise ValueError(f"No Pexels images for: {query}")
    photo = data["photos"][0]
    return (requests.get(photo["src"]["large2x"], timeout=30).content,
            photo["photographer"], photo["src"]["large2x"])


def upload_image(img_bytes, slug, title, photographer):
    safe  = re.sub(r"[^a-z0-9-]", "-", slug)[:60]
    hdrs  = dict(HEADERS)
    hdrs["Content-Type"]        = "image/jpeg"
    hdrs["Content-Disposition"] = f'attachment; filename="{safe}.jpg"'
    r = requests.post(f"{WP_URL}/wp-json/wp/v2/media",
                      headers=hdrs, data=img_bytes, timeout=60)
    if not r.ok:
        raise Exception(f"Image upload failed {r.status_code}: {r.text[:200]}")
    mid = r.json()["id"]
    requests.post(f"{WP_URL}/wp-json/wp/v2/media/{mid}", headers=HEADERS,
                  json={"alt_text": title,
                        "caption": f"Photo by {photographer} on Pexels"}, timeout=15)
    return mid


# ============================================================
#  📂  CATEGORIES & TAGS
# ============================================================

def fetch_wp_categories():
    cat_map, page = {}, 1
    while True:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/categories", headers=HEADERS,
                         params={"per_page": 100, "page": page, "_fields": "id,name"},
                         timeout=20)
        if r.status_code == 400: break
        r.raise_for_status()
        for c in r.json(): cat_map[c["name"].lower()] = c["id"]
        if page >= int(r.headers.get("X-WP-TotalPages", 1)): break
        page += 1
    return cat_map


def resolve_cats(chosen, cat_map):
    ids = []
    for name in chosen:
        nl = name.lower()
        if nl in cat_map:
            ids.append(cat_map[nl]); continue
        best_s, best_k = 0, None
        for k in cat_map:
            s = SequenceMatcher(None, nl, k).ratio()
            if s > best_s: best_s, best_k = s, k
        if best_k and best_s >= 0.60: ids.append(cat_map[best_k])
    if not ids and "living in germany" in cat_map:
        ids.append(cat_map["living in germany"])
    return ids


def sync_tags(names):
    ids = []
    for name in names:
        try:
            ids.append(wp_request("POST", "tags", json={"name": name})["id"])
        except Exception:
            s = requests.get(f"{WP_URL}/wp-json/wp/v2/tags", headers=HEADERS,
                             params={"search": name, "per_page": 1}, timeout=15).json()
            if s: ids.append(s[0]["id"])
    return ids


# ============================================================
#  🚀  PUBLISH
# ============================================================

def publish_post(article, featured_id, cat_ids, tag_ids, photographer):
    footer = (
        f'<hr/><p><em>Featured image by <strong>{photographer}</strong> via '
        f'<a href="https://www.pexels.com" target="_blank" rel="nofollow">Pexels</a>.'
        f'</em></p>'
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
        "lang":           "en",
        "meta": {
            "rank_math_focus_keyword": article["focus_keyword"],
            "rank_math_description":   article["meta_description"],
            "rank_math_title":         article["title"],
        },
    })


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport AutoBlogger")
    parser.add_argument("--topic", type=str, default=None,
                        help="Override topic (skip pool selection)")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info(f"GermanySupport AutoBlogger — {CURRENT_YEAR}")
    log.info("=" * 60)

    # Warm up referral links cache
    log.info("[1/7] Fetching referral links from WordPress...")
    fetch_referral_links(WP_URL)
    log.info("[2/7] Fetching WordPress categories...")
    cat_map = fetch_wp_categories()

    log.info("[3/7] Fetching existing posts for duplicate check...")
    all_posts = fetch_all_post_data()
    log.info(f"      Found {len(all_posts)} existing posts.")

    log.info("[4/7] Selecting topic...")
    chosen_topic, source = pick_fresh_topic(all_posts, args.topic)
    log.info(f"      Source : {source}")
    log.info(f"      Topic  : {chosen_topic}")

    log.info("[5/7] Generating article with Claude...")
    rel_links = get_relevant_links(chosen_topic, "", WP_URL)
    log.info(f"      Using {len(rel_links)} relevant affiliate links.")
    article   = generate_article(chosen_topic, rel_links)
    log.info(f"      Title    : {article['title']}")
    log.info(f"      Focus KW : {article['focus_keyword']}")
    log.info(f"      Words    : ~{len(article['content'].split())}")

    log.info(f"[6/7] Fetching Pexels image: '{article['image_search_query']}'...")
    img_bytes, photographer, img_url = fetch_pexels_image(article["image_search_query"])
    featured_id = upload_image(img_bytes, article["slug"], article["title"], photographer)
    log.info(f"      Photographer : {photographer}")
    log.info(f"      Media ID     : {featured_id}")

    log.info("[7/7] Publishing post to WordPress...")
    tag_ids = sync_tags(article["tags"])
    cat_ids = resolve_cats(article.get("categories", ["Living in Germany"]), cat_map)
    post    = publish_post(article, featured_id, cat_ids, tag_ids, photographer)

    log.info("=" * 60)
    log.info("PUBLISHED SUCCESSFULLY")
    log.info("=" * 60)
    log.info(f"  Title  : {post['title']['rendered']}")
    log.info(f"  URL    : {post['link']}")
    log.info(f"  ID     : {post['id']}")
    log.info(f"  Source : {source}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()