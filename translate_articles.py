"""
GermanySupport.de — German Article Translator v3
=================================================
Translates English articles into German and correctly registers
them in Polylang.

KEY FIXES in v3:
- Duplicate detection now uses Polylang's actual translation data
  instead of slug matching (which was causing false positives)
- Helper plugin install uses correct WP REST API params
- Falls back to lang= query param on post creation
- Clear reporting of what is and isn't linked
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
DELAY_BETWEEN = 8
LANG_EN       = "en"
LANG_DE       = "de"

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
#  🔧  AUTH
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
        headers=HEADERS, params=params or {},
    )
    r.raise_for_status()
    return r.json()


def wp_post_req(endpoint, data):
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/{endpoint}",
        headers=HEADERS, json=data,
    )
    if not r.ok:
        raise Exception(f"WP POST error {r.status_code}: {r.text[:400]}")
    return r.json()


def strip_html(html):
    return re.sub(r"<[^>]+>", " ", html or "")


# ============================================================
#  🌐  POLYLANG — LANGUAGE DETECTION & LINKING
# ============================================================

def get_post_language(post_id):
    """
    Ask Polylang what language a post is in.
    Returns 'en', 'de', or None if unknown.
    """
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/pll/v1/post/{post_id}",
            headers=HEADERS,
        )
        if r.ok:
            data = r.json()
            # Polylang returns {"en": en_id, "de": de_id} — find which key has our post_id
            for lang, pid in data.items():
                if int(pid) == int(post_id):
                    return lang
    except Exception:
        pass
    return None


def get_translation_id(post_id, target_lang="de"):
    """
    Get the ID of the translation of a post in target_lang.
    Returns the translation post ID or None if not translated yet.
    """
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/pll/v1/post/{post_id}",
            headers=HEADERS,
        )
        if r.ok:
            data = r.json()
            de_id = data.get(target_lang)
            # Polylang returns the same post ID if no translation exists
            if de_id and int(de_id) != int(post_id):
                return int(de_id)
    except Exception:
        pass
    return None


def set_language_via_pll_api(post_id, lang):
    """Set language of a post using Polylang REST API."""
    try:
        r = requests.post(
            f"{WP_URL}/wp-json/pll/v1/post/{post_id}",
            headers=HEADERS,
            json={"language": lang},
        )
        return r.ok
    except Exception:
        return False


def link_translations_via_pll_api(en_id, de_id):
    """
    Link EN and DE posts as translations of each other via Polylang REST API.
    Tries both directions to maximise chances of success.
    """
    success = False
    try:
        r1 = requests.post(
            f"{WP_URL}/wp-json/pll/v1/post/{en_id}",
            headers=HEADERS,
            json={
                "language":     "en",
                "translations": {"en": en_id, "de": de_id},
            },
        )
        r2 = requests.post(
            f"{WP_URL}/wp-json/pll/v1/post/{de_id}",
            headers=HEADERS,
            json={
                "language":     "de",
                "translations": {"en": en_id, "de": de_id},
            },
        )
        if r1.ok and r2.ok:
            print(f"  Polylang API: linked EN {en_id} <-> DE {de_id}")
            success = True
        else:
            print(f"  Polylang API link: EN={r1.status_code} DE={r2.status_code}")
            if not r1.ok:
                print(f"  EN response: {r1.text[:150]}")
            if not r2.ok:
                print(f"  DE response: {r2.text[:150]}")
    except Exception as e:
        print(f"  Polylang API error: {e}")
    return success


# ============================================================
#  📥  FETCH POSTS
# ============================================================

def fetch_all_posts_with_language():
    """
    Fetch all published posts and determine their Polylang language.
    Returns two lists: english_posts, german_post_ids
    """
    all_posts = []
    page = 1
    print("  Fetching all published posts...")
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={
                "per_page": 20,
                "page":     page,
                "status":   "publish",
                "_fields":  "id,title,slug,content,excerpt,tags,categories,featured_media",
            },
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        all_posts.extend(batch)
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total_pages} — {len(all_posts)} posts total...")
        if page >= total_pages:
            break
        page += 1

    print(f"  Checking language of each post via Polylang...")
    english_posts  = []
    german_post_ids = set()

    for post in all_posts:
        lang = get_post_language(post["id"])
        post["_detected_lang"] = lang
        if lang == "de":
            german_post_ids.add(post["id"])
        else:
            # Treat as English if lang is 'en' or unknown/None
            english_posts.append(post)

    print(f"  English posts : {len(english_posts)}")
    print(f"  German posts  : {len(german_post_ids)}")
    return english_posts, german_post_ids


def fetch_single_post(post_id):
    return wp_get(f"posts/{post_id}")


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
            t = wp_post_req("tags", {"name": name})
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
    client     = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    en_title   = post["title"]["rendered"]
    en_content = strip_html(post["content"]["rendered"])
    links_str  = "\n".join([f"- {name}: {url}" for name, url in REFERRAL_LINKS.items()])
    cats_str   = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    system_prompt = f"""
Du bist ein professioneller SEO-Texter und Übersetzer, spezialisiert auf
praktische Ratgeber für Expats und Einwanderer in Deutschland.

Übersetze den englischen Artikel ins Deutsche und optimiere ihn für deutsche SEO.

REGELN:
1. Natürliche, flüssige deutsche Sprache — kein maschineller Stil
2. Deutsche SEO-Keywords verwenden
3. Alle HTML-Tags beibehalten (<h2>, <h3>, <p>, <ul>, <li>, <strong>, <a>)
4. Affiliate-Links beibehalten — nur Linktext übersetzen, URLs nicht ändern
5. Deutsche Meta-Description von GENAU 150-155 Zeichen
6. 10-15 deutsche SEO-Tags
7. Fokus-Keyword im ersten Absatz und in mindestens 2 H2-Überschriften
8. FAQ-Sektion am Ende übersetzen falls vorhanden
9. Ton: hilfreich, freundlich, informativ

KATEGORIE-REGELN — wähle NUR aus dieser Liste (exakte Namen):
{cats_str}

Ausgabe NUR als gültiges JSON, keine Markdown-Fence:
{{
  "title": "Deutscher Artikeltitel",
  "slug": "deutscher-url-slug",
  "meta_description": "Genau 150-155 Zeichen",
  "focus_keyword": "deutscher SEO-Begriff",
  "tags": ["tag1", "tag2"],
  "categories": ["Exact Category Name"],
  "content": "Vollständiger HTML-Inhalt auf Deutsch"
}}
"""

    user_prompt = f"""
Übersetze und optimiere diesen englischen Artikel:

TITEL: {en_title}

INHALT:
{en_content[:6000]}

Affiliate-Links (Linktext übersetzen, URLs beibehalten):
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
    """
    Create the German post. Pass lang=de so Polylang registers
    it as German immediately on creation.
    """
    data = {
        "title":      translated["title"],
        "slug":       translated["slug"],
        "content":    translated["content"],
        "excerpt":    translated["meta_description"],
        "status":     "publish",
        "categories": cat_ids,
        "tags":       tag_ids,
        "lang":       "de",
        "meta": {
            "_yoast_wpseo_metadesc": translated["meta_description"],
            "_yoast_wpseo_focuskw":  translated["focus_keyword"],
            "_aioseop_description":  translated["meta_description"],
            "_aioseop_keywords":     ", ".join(translated["tags"]),
        },
    }
    if featured_media_id:
        data["featured_media"] = featured_media_id
    return wp_post_req("posts", data)


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport German Translator v3")
    parser.add_argument("--limit",   type=int, default=None,
                        help="Max number of articles to translate")
    parser.add_argument("--post-id", type=int, default=None,
                        help="Translate a single post by WordPress ID")
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — German Translator v3")
    print("=" * 62)

    # 1. Fetch categories
    print("\n[1] Fetching WordPress categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 2. Fetch and classify all posts by language
    if args.post_id:
        print(f"\n[2] Single post mode: ID {args.post_id}")
        post = fetch_single_post(args.post_id)
        lang = get_post_language(args.post_id)
        post["_detected_lang"] = lang
        if lang == "de":
            print(f"    Post {args.post_id} is already in German — nothing to do.")
            return
        english_posts   = [post]
        german_post_ids = set()
    else:
        print("\n[2] Fetching and classifying all posts by language...")
        english_posts, german_post_ids = fetch_all_posts_with_language()

    # 3. Filter to only posts that don't have a German translation yet
    print("\n[3] Identifying posts that need translation...")
    to_translate = []
    for post in english_posts:
        existing_de_id = get_translation_id(post["id"], "de")
        if existing_de_id:
            print(f"    SKIP [{post['id']}] already has DE translation "
                  f"(ID {existing_de_id}): {post['title']['rendered'][:50]}")
        else:
            to_translate.append(post)

    if args.limit:
        to_translate = to_translate[:args.limit]

    print(f"\n    Need translation: {len(to_translate)}")

    if not to_translate:
        print("\n    All English posts already have German translations!")
        return

    # 4. Translate loop
    print(f"\n[4] Translating {len(to_translate)} articles...")
    print("=" * 62)

    results = {"success": [], "failed": [], "needs_manual": []}
    total   = len(to_translate)

    for i, post in enumerate(to_translate, 1):
        post_id           = post["id"]
        en_title          = post["title"]["rendered"]
        featured_media_id = post.get("featured_media") or None

        print(f"\n[{i}/{total}] Post ID {post_id}")
        print(f"  EN: {en_title[:65]}")

        try:
            # Translate with Claude
            print("  Translating with Claude...")
            translated = translate_article(post)
            print(f"  DE: {translated['title'][:65]}")
            print(f"  KW: {translated['focus_keyword']}")
            print(f"  Cat: {translated['categories']}")

            # Resolve categories + tags
            cat_ids = resolve_category_ids(translated["categories"], wp_cat_map)
            tag_ids = sync_tags(translated["tags"])

            # Publish German post (with lang=de)
            de_post    = publish_german_post(
                translated, cat_ids, tag_ids, featured_media_id
            )
            de_post_id = de_post["id"]
            print(f"  DE post created: ID {de_post_id}")
            print(f"  URL: {de_post['link']}")

            # Verify Polylang picked up the language
            time.sleep(2)  # brief pause to let WP process
            de_lang = get_post_language(de_post_id)
            print(f"  DE post language detected as: {de_lang or 'unknown'}")

            # Ensure EN post is set to English
            set_language_via_pll_api(post_id, "en")

            # Link EN <-> DE in Polylang
            linked = link_translations_via_pll_api(post_id, de_post_id)

            # Verify the link worked
            time.sleep(1)
            verify_de = get_translation_id(post_id, "de")
            if verify_de == de_post_id:
                print(f"  Verified: EN {post_id} <-> DE {de_post_id} correctly linked.")
                linked = True
            else:
                print(f"  Link not verified — manual fix needed.")
                linked = False

            entry = {
                "en_id":    post_id,
                "de_id":    de_post_id,
                "en_title": en_title,
                "de_title": translated["title"],
                "de_url":   de_post["link"],
                "linked":   linked,
            }
            results["success"].append(entry)
            if not linked:
                results["needs_manual"].append(entry)

        except Exception as e:
            print(f"  ERROR: {e}")
            results["failed"].append({
                "id":    post_id,
                "title": en_title,
                "error": str(e),
            })

        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s...")
            time.sleep(DELAY_BETWEEN)

    # 5. Summary
    print("\n" + "=" * 62)
    print("  TRANSLATION COMPLETE")
    print("=" * 62)
    print(f"  Translated     : {len(results['success'])}")
    print(f"  Auto-linked    : {len([r for r in results['success'] if r['linked']])}")
    print(f"  Need manual fix: {len(results['needs_manual'])}")
    print(f"  Failed         : {len(results['failed'])}")

    if results["success"]:
        print("\n  Translated:")
        for r in results["success"]:
            status = "✓ linked" if r["linked"] else "✗ needs manual fix"
            print(f"    EN[{r['en_id']}] → DE[{r['de_id']}] {status}")
            print(f"    {r['de_url']}")

    # Manual fix instructions
    if results["needs_manual"]:
        print("\n" + "=" * 62)
        print("  MANUAL FIX NEEDED in WordPress editor:")
        print("=" * 62)
        print("  For each pair:")
        print("  1. Open the ENGLISH post in WP editor")
        print("  2. Right sidebar → Languages box")
        print("  3. Next to German → click pencil icon")
        print("  4. Enter the German post ID shown below")
        print("  5. Click Update")
        print()
        for r in results["needs_manual"]:
            print(f"  EN post ID : {r['en_id']}  ({r['en_title'][:45]})")
            print(f"  DE post ID : {r['de_id']}  ({r['de_title'][:45]})")
            print()

    if results["failed"]:
        print("\n  Failed:")
        for r in results["failed"]:
            print(f"    [{r['id']}] {r['title'][:55]}")
            print(f"    Error: {r['error'][:100]}")

    print("=" * 62)

    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
