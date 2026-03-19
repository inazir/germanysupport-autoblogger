"""
GermanySupport.de — German Article Translator
==============================================
Translates all published English articles into German using Claude,
then creates linked German posts in WordPress via the Polylang REST API.

Requirements:
  - Polylang (free) plugin installed and activated on WordPress
  - German language added in Polylang settings
  - Same GitHub Secrets as autoblogger (no new secrets needed)

Usage:
  python translate_articles.py                  # translate all untranslated articles
  python translate_articles.py --limit 5        # translate first 5 only (test)
  python translate_articles.py --post-id 123    # translate one specific post by ID
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
DELAY_BETWEEN  = 8      # seconds between articles (rate limit safety)
LANG_EN        = "en"   # Polylang language slug for English
LANG_DE        = "de"   # Polylang language slug for German

# ============================================================
#  📂  ALLOWED CATEGORIES (same as autoblogger)
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
#  🔧  HELPERS
# ============================================================

def build_auth_headers():
    credentials = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type":  "application/json",
    }

HEADERS = build_auth_headers()


def wp_get(endpoint, params=None):
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/{endpoint}",
        headers=HEADERS,
        params=params or {},
    )
    r.raise_for_status()
    return r.json()


def wp_post(endpoint, data):
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/{endpoint}",
        headers=HEADERS,
        json=data,
    )
    if not r.ok:
        raise Exception(f"WP POST error {r.status_code}: {r.text[:400]}")
    return r.json()


def strip_html(html):
    return re.sub(r"<[^>]+>", " ", html or "")


# ============================================================
#  🌐  POLYLANG HELPERS
# ============================================================

def get_polylang_translations(post_id):
    """
    Get existing translations for a post via Polylang REST API.
    Returns dict like {"en": 123, "de": 456} or just {"en": 123} if no German yet.
    Returns empty dict if Polylang is not installed or post not found.
    """
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/pll/v1/post/{post_id}",
            headers=HEADERS,
        )
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()  # e.g. {"en": 123, "de": 456}
    except Exception:
        return {}


def set_polylang_language(post_id, lang):
    """Set the language of a post in Polylang."""
    try:
        requests.post(
            f"{WP_URL}/wp-json/pll/v1/post/{post_id}",
            headers=HEADERS,
            json={"language": lang},
        )
    except Exception as e:
        print(f"      Warning: could not set Polylang language: {e}")


def link_translations(en_post_id, de_post_id):
    """
    Link the English and German posts as translations of each other in Polylang.
    """
    try:
        requests.post(
            f"{WP_URL}/wp-json/pll/v1/post/{en_post_id}",
            headers=HEADERS,
            json={
                "language": LANG_EN,
                "translations": {LANG_DE: de_post_id},
            },
        )
        print(f"      Linked EN post {en_post_id} ↔ DE post {de_post_id} in Polylang.")
    except Exception as e:
        print(f"      Warning: could not link translations in Polylang: {e}")


def already_translated(post_id):
    """Check if a German translation already exists for this post."""
    translations = get_polylang_translations(post_id)
    return LANG_DE in translations and translations[LANG_DE] != post_id


# ============================================================
#  📥  FETCH POSTS
# ============================================================

def fetch_all_english_posts():
    """Fetch all published English posts with full content."""
    posts = []
    page  = 1
    print("  Fetching all published English posts...")
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={
                "per_page": 20,
                "page":     page,
                "status":   "publish",
                "lang":     LANG_EN,   # Polylang filter
                "_fields":  "id,title,slug,content,excerpt,tags,categories",
            },
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total_pages} — {len(posts)} posts fetched...")
        if page >= total_pages:
            break
        page += 1
    return posts


def fetch_single_post(post_id):
    return wp_get(f"posts/{post_id}")


# ============================================================
#  📂  CATEGORY & TAG HELPERS
# ============================================================

def fetch_wp_categories():
    """Fetch all WP categories → {name_lower: id}"""
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
    """Match Claude's category choices to WordPress IDs."""
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
            print(f"      WARNING: Could not match category '{name}' — skipping.")
    if not ids:
        fallback = "living in germany"
        if fallback in wp_cat_map:
            ids.append(wp_cat_map[fallback])
    return ids


def sync_tags(tag_names):
    """Create or find tags, return list of IDs."""
    tag_ids = []
    for name in tag_names:
        try:
            t = wp_post("tags", {"name": name})
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
#  🤖  CLAUDE TRANSLATION
# ============================================================

def translate_article(post):
    """
    Send the English article to Claude for German translation + SEO localization.
    Returns a dict with all German fields ready for WordPress.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    en_title   = post["title"]["rendered"]
    en_content = strip_html(post["content"]["rendered"])
    en_excerpt = strip_html(post.get("excerpt", {}).get("rendered", ""))
    links_str  = "\n".join([f"- {name}: {url}" for name, url in REFERRAL_LINKS.items()])
    cats_str   = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    system_prompt = f"""
Du bist ein professioneller SEO-Texter und Übersetzer, spezialisiert auf
praktische Ratgeber für Expats und Einwanderer in Deutschland.

Deine Aufgabe ist es, einen englischen Artikel ins Deutsche zu übersetzen
und dabei vollständig für die deutsche SEO zu optimieren.

ÜBERSETZUNGSREGELN:
1. Übersetze natürlich und flüssig — kein maschineller Stil
2. Passe Beispiele, Begriffe und Formulierungen für deutschsprachige Leser an
3. Verwende deutsche SEO-Keywords (nicht wörtliche Übersetzungen der englischen Keywords)
4. Behalte alle HTML-Tags bei (<h2>, <h3>, <p>, <ul>, <li>, <strong>, <a>)
5. Behalte alle Affiliate-Links bei — übersetze nur den Linktext, nicht die URL
6. Schreibe eine deutsche Meta-Description von GENAU 150-155 Zeichen
7. Generiere 10-15 deutsche SEO-Tags
8. Der Fokus-Keyword muss im ersten Absatz und in mindestens 2 H2-Überschriften vorkommen
9. Wähle 1-2 Kategorien aus der erlaubten Liste (exakte Namen)
10. Der Ton soll hilfreich, freundlich und informativ sein — wie ein Ratgeber von Freund zu Freund

KATEGORIE-REGELN:
- Wähle NUR aus dieser Liste — erfinde keine neuen Namen:
{cats_str}

Ausgabe NUR als gültiges JSON, keine Markdown-Fence, kein zusätzlicher Text:
{{
  "title": "Deutscher Artikeltitel",
  "slug": "url-freundlicher-slug-auf-deutsch",
  "meta_description": "Genau 150-155 Zeichen deutsche Meta-Description",
  "focus_keyword": "deutscher SEO-Suchbegriff",
  "tags": ["tag1", "tag2", "..."],
  "categories": ["Exact Category Name"],
  "content": "Vollständiger übersetzter HTML-Inhalt"
}}
"""

    user_prompt = f"""
Übersetze und optimiere diesen englischen Artikel für deutschsprachige Expats in Deutschland:

ENGLISCHER TITEL: {en_title}

ENGLISCHER INHALT:
{en_content[:6000]}

Verfügbare Affiliate-Links (Linktext übersetzen, URLs beibehalten):
{links_str}

Ausgabe NUR als rohes JSON-Objekt.
"""

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


# ============================================================
#  📤  PUBLISH GERMAN POST
# ============================================================

def publish_german_post(translated, cat_ids, tag_ids, featured_media_id=None):
    """Create the German post in WordPress."""
    data = {
        "title":      translated["title"],
        "slug":       translated["slug"],
        "content":    translated["content"],
        "excerpt":    translated["meta_description"],
        "status":     "publish",
        "categories": cat_ids,
        "tags":       tag_ids,
        "meta": {
            "_yoast_wpseo_metadesc": translated["meta_description"],
            "_yoast_wpseo_focuskw":  translated["focus_keyword"],
            "_aioseop_description":  translated["meta_description"],
            "_aioseop_keywords":     ", ".join(translated["tags"]),
        },
    }
    # Re-use the same featured image as the English post
    if featured_media_id:
        data["featured_media"] = featured_media_id

    return wp_post("posts", data)


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport German Translator")
    parser.add_argument("--limit",   type=int, default=None, help="Max articles to translate")
    parser.add_argument("--post-id", type=int, default=None, help="Translate a single post by ID")
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — German Translator")
    print("=" * 62)

    # 1. Fetch WordPress categories
    print("\n[1] Fetching WordPress categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 2. Fetch posts to translate
    print("\n[2] Fetching English posts...")
    if args.post_id:
        posts = [fetch_single_post(args.post_id)]
        print(f"    Single post mode: Post ID {args.post_id}")
    else:
        posts = fetch_all_english_posts()
        if args.limit:
            posts = posts[:args.limit]
        print(f"    Found {len(posts)} English posts to process.")

    # 3. Filter out already-translated posts
    print("\n[3] Checking which posts already have a German translation...")
    to_translate = []
    already_done = []
    for post in posts:
        if already_translated(post["id"]):
            already_done.append(post)
        else:
            to_translate.append(post)

    print(f"    Already translated : {len(already_done)}")
    print(f"    Need translation   : {len(to_translate)}")

    if not to_translate:
        print("\n    All posts are already translated into German!")
        return

    # 4. Translate each article
    print(f"\n[4] Starting translation loop...")
    print("=" * 62)

    results = {"success": [], "failed": [], "skipped": []}
    total   = len(to_translate)

    for i, post in enumerate(to_translate, 1):
        post_id = post["id"]
        en_title = post["title"]["rendered"]
        featured_media_id = post.get("featured_media") or None

        print(f"\n[{i}/{total}] Post ID {post_id}")
        print(f"  EN title : {en_title[:70]}")

        try:
            # Translate with Claude
            print(f"  Translating with Claude...")
            translated = translate_article(post)

            print(f"  DE title : {translated['title'][:70]}")
            print(f"  Focus KW : {translated['focus_keyword']}")
            print(f"  Category : {translated['categories']}")

            # Resolve categories and tags
            cat_ids = resolve_category_ids(translated["categories"], wp_cat_map)
            tag_ids = sync_tags(translated["tags"])

            # Publish German post
            de_post = publish_german_post(translated, cat_ids, tag_ids, featured_media_id)
            de_post_id = de_post["id"]
            print(f"  DE post created: ID {de_post_id} — {de_post['link']}")

            # Set Polylang language on both posts and link them
            set_polylang_language(post_id, LANG_EN)
            set_polylang_language(de_post_id, LANG_DE)
            link_translations(post_id, de_post_id)

            results["success"].append({
                "en_id":    post_id,
                "de_id":    de_post_id,
                "en_title": en_title,
                "de_title": translated["title"],
                "de_url":   de_post["link"],
            })

        except Exception as e:
            print(f"  ERROR: {e}")
            results["failed"].append({
                "id":    post_id,
                "title": en_title,
                "error": str(e),
            })

        # Polite delay
        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s...")
            time.sleep(DELAY_BETWEEN)

    # 5. Summary
    print("\n" + "=" * 62)
    print("  TRANSLATION COMPLETE — SUMMARY")
    print("=" * 62)
    print(f"  Total processed    : {total}")
    print(f"  Already translated : {len(already_done)}")
    print(f"  Translated now     : {len(results['success'])}")
    print(f"  Failed             : {len(results['failed'])}")

    if results["success"]:
        print("\n  Successfully translated:")
        for r in results["success"]:
            print(f"    EN [{r['en_id']}] {r['en_title'][:45]}")
            print(f"    DE [{r['de_id']}] {r['de_title'][:45]}")
            print(f"           {r['de_url']}")

    if results["failed"]:
        print("\n  Failed:")
        for r in results["failed"]:
            print(f"    [{r['id']}] {r['title'][:55]}")
            print(f"           {r['error'][:100]}")

    print("=" * 62)

    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
