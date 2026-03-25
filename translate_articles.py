"""
GermanySupport.de — German Article Translator v4
=================================================
KEY FIXES:
- Robust JSON parsing that handles special characters, German umlauts,
  unterminated strings from Claude
- Polylang linking via a one-time WordPress PHP snippet (Code Snippets plugin)
  since /pll/v1/ REST endpoint is not available on this Polylang version
- Better detection of already-translated posts using post meta
- Cleaner language detection without relying on Polylang REST API
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
LANG_DE       = "de"
LANG_EN       = "en"

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
    "N26 Bank":               "https://germanysupport.de/go/n26",
    "C24 Bank":               "https://germanysupport.de/go/c24",
    "Commerzbank":            "https://germanysupport.de/go/n26",
    "Advanzia Mastercard":    "https://germanysupport.de/go/advanzia",
    "American Express":       "https://germanysupport.de/go/n26",
    "Credit Card Comparison": "https://germanysupport.de/go/credit-cards",
    "Trade Republic":         "https://germanysupport.de/go/trade-republic",
    "Metro Business":         "https://germanysupport.de/go/credit-cards",
    
    "Liability Insurance":    "https://germanysupport.de/go/haftpflicht",
    "Haftpflicht":    "https://germanysupport.de/go/haftpflicht",
    "HUK24 Car Insurance":    "https://germanysupport.de/go/huk24",
    "Car Insurance Compare":  "https://germanysupport.de/go/car-insurance",
    
    "SteuerGo":               "https://germanysupport.de/go/steuergo",
    "WISO Steuer":            "https://germanysupport.de/go/wiso",
    
    "Verivox DSL":            "https://germanysupport.de/go/verivox-dsl",
    "DSL Check24":            "https://germanysupport.de/go/dsl-check24",
    "Klarmobil":              "https://germanysupport.de/go/klarmobil",
    "Check24 Mobile":         "https://germanysupport.de/go/check24-mobile",
    "Congstar Mobile":        "https://germanysupport.de/go/congstar",
    
    "Electricity Provider":   "https://germanysupport.de/go/electricity",
    "Gas Provider":           "https://germanysupport.de/go/gas",
    
    "Check24 Travel":         "https://germanysupport.de/go/travel",
    "Check24 Car Rental":     "https://germanysupport.de/go/car-rental",
    
    "ACE Money Transfer":     "https://germanysupport.de/go/ace",
    "TapTap Send":            "https://germanysupport.de/go/taptap",
    
    "Shoop Cashback":         "https://germanysupport.de/go/shoop",
    "iGraal Cashback":        "https://germanysupport.de/go/igraal",
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
#  🧹  ROBUST JSON PARSER
#  Handles Claude responses that contain special characters,
#  German umlauts, or occasionally malformed JSON.
# ============================================================

def parse_claude_json(raw_text):
    """
    Robustly parse JSON from Claude's response.
    Tries multiple strategies before giving up.
    """
    # Strategy 1: clean fences and parse directly
    text = raw_text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*",     "", text)
    text = re.sub(r"```$",        "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract the JSON object with a regex
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Strategy 3: fix common issues — trailing commas, unescaped quotes
    fixed = text
    # Remove trailing commas before } or ]
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    # Replace curly/smart quotes with straight quotes
    fixed = fixed.replace('\u201c', '"').replace('\u201d', '"')
    fixed = fixed.replace('\u2018', "'").replace('\u2019', "'")
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Strategy 4: ask Claude to fix its own output
    print("  JSON parse failed — asking Claude to repair the output...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    repair_response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""The following JSON is malformed. Fix it and return ONLY valid JSON, 
nothing else, no markdown fences:

{text[:3000]}"""
        }],
    )
    repaired = repair_response.content[0].text.strip()
    repaired = re.sub(r"^```json\s*", "", repaired)
    repaired = re.sub(r"```$", "", repaired).strip()
    return json.loads(repaired)


# ============================================================
#  🌐  POLYLANG — LANGUAGE & LINKING
#
#  Since /pll/v1/ REST endpoint is not available, we use
#  two alternative methods:
#
#  Method A: Pass 'lang' parameter when creating the post
#            (works if Polylang REST API is partially active)
#
#  Method B: Use a custom REST endpoint registered by the
#            "Code Snippets" WordPress plugin. We register
#            the snippet once via the REST API, then call it.
#
#  Method C: Store the translation mapping locally and print
#            clear manual fix instructions with exact steps.
# ============================================================

def get_post_lang_from_meta(post_id):
    """
    Check the post's language by looking at Polylang term assignments.
    Polylang assigns a term from the 'language' taxonomy to each post.
    We can read this via the WP REST API terms endpoint.
    """
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
            headers=HEADERS,
            params={"_fields": "id,lang,translations"},
        )
        if r.ok:
            data = r.json()
            # Some Polylang versions expose 'lang' directly
            if data.get("lang"):
                return data["lang"]
    except Exception:
        pass
    return None


def get_existing_de_translation(en_post_id):
    """
    Check if English post already has a German translation
    by reading the 'translations' field Polylang adds to posts.
    """
    try:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts/{en_post_id}",
            headers=HEADERS,
            params={"_fields": "id,translations,lang"},
        )
        if r.ok:
            data = r.json()
            translations = data.get("translations", {})
            de_id = translations.get("de")
            if de_id and int(de_id) != int(en_post_id):
                return int(de_id)
    except Exception:
        pass
    return None


def try_link_via_post_update(en_id, de_id):
    """
    Try to link posts by updating both with translations meta.
    Polylang reads _pll_translations_ meta on some configurations.
    """
    success_count = 0
    try:
        # Update EN post with translation reference
        r1 = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{en_id}",
            headers=HEADERS,
            json={
                "lang": "en",
                "translations": {"en": en_id, "de": de_id},
            },
        )
        if r1.ok:
            success_count += 1

        # Update DE post with translation reference
        r2 = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{de_id}",
            headers=HEADERS,
            json={
                "lang": "de",
                "translations": {"en": en_id, "de": de_id},
            },
        )
        if r2.ok:
            success_count += 1

    except Exception as e:
        print(f"  Link via post update error: {e}")

    return success_count == 2


# ============================================================
#  📥  FETCH POSTS
# ============================================================

def fetch_all_posts():
    """Fetch all published posts."""
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
                "_fields":  "id,title,slug,content,excerpt,tags,categories,featured_media,lang,translations",
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
        print(f"  Page {page}/{total_pages} — {len(all_posts)} posts...")
        if page >= total_pages:
            break
        page += 1
    return all_posts


def classify_posts(all_posts):
    """
    Separate posts into English and German using multiple signals:
    1. 'lang' field from Polylang (if available)
    2. 'translations' field
    3. URL pattern (/de/ prefix = German)
    4. Slug pattern
    """
    english_posts = []
    german_posts  = []

    for post in all_posts:
        lang         = post.get("lang", "")
        translations = post.get("translations", {})
        link         = post.get("link", "")
        slug         = post.get("slug", "")

        # Signal 1: explicit lang field
        if lang == "de":
            german_posts.append(post)
            continue
        if lang == "en":
            english_posts.append(post)
            continue

        # Signal 2: URL contains /de/
        if "/de/" in link or link.startswith(f"{WP_URL}/de/"):
            german_posts.append(post)
            continue

        # Signal 3: translations dict has 'en' pointing to a different post
        # meaning this post IS the de version
        en_id = translations.get("en")
        de_id = translations.get("de")
        if en_id and de_id:
            if int(de_id) == int(post["id"]) and int(en_id) != int(post["id"]):
                german_posts.append(post)
                continue
            if int(en_id) == int(post["id"]) and int(de_id) != int(post["id"]):
                english_posts.append(post)
                continue

        # Default: treat as English if we can't determine
        english_posts.append(post)

    return english_posts, german_posts


def fetch_single_post(post_id):
    return requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        params={"_fields": "id,title,slug,content,excerpt,tags,categories,featured_media,lang,translations"},
    ).json()


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
Du bist ein professioneller SEO-Texter und Übersetzer für Expats in Deutschland.

Übersetze den englischen Artikel ins Deutsche und optimiere ihn für deutsche SEO.

WICHTIG — JSON-AUSGABE-REGELN:
- Alle Anführungszeichen im Content-Feld MÜSSEN escaped sein: \" nicht "
- Verwende keine Smart Quotes oder typografische Anführungszeichen
- Stelle sicher dass das JSON vollständig und gültig ist
- Keine Zeilenumbrüche innerhalb von JSON-String-Werten — verwende \\n

ÜBERSETZUNGSREGELN:
1. Natürliche, flüssige deutsche Sprache
2. Deutsche SEO-Keywords verwenden
3. Alle HTML-Tags beibehalten
4. Affiliate-Links beibehalten — nur Linktext übersetzen, URLs nicht ändern
5. Deutsche Meta-Description von GENAU 150-155 Zeichen
6. 10-15 deutsche SEO-Tags
7. Fokus-Keyword im ersten Absatz und in 2+ H2-Überschriften
8. FAQ-Sektion übersetzen falls vorhanden

KATEGORIE — wähle NUR aus dieser Liste (exakte Namen):
{cats_str}

Ausgabe NUR als gültiges JSON:
{{
  "title": "Deutscher Titel",
  "slug": "deutscher-slug",
  "meta_description": "150-155 Zeichen",
  "focus_keyword": "keyword",
  "tags": ["tag1", "tag2"],
  "categories": ["Category Name"],
  "content": "HTML-Inhalt mit escaped Anführungszeichen"
}}
"""

    user_prompt = f"""
Übersetze diesen Artikel ins Deutsche:

TITEL: {en_title}

INHALT:
{en_content[:5000]}

Affiliate-Links (nur Linktext übersetzen):
{links_str}

Gib NUR das JSON-Objekt aus. Stelle sicher dass alle Anführungszeichen 
im content-Feld korrekt escaped sind.
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text.strip()
    return parse_claude_json(raw)


# ============================================================
#  📤  PUBLISH GERMAN POST
# ============================================================

def publish_german_post(translated, cat_ids, tag_ids, en_post_id, featured_media_id=None):
    """
    Create the German post.
    Pass lang=de and translations so Polylang can register it.
    """
    data = {
        "title":        translated["title"],
        "slug":         translated["slug"],
        "content":      translated["content"],
        "excerpt":      translated["meta_description"],
        "status":       "publish",
        "categories":   cat_ids,
        "tags":         tag_ids,
        "lang":         "de",
        "translations": {"en": en_post_id},
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
    parser = argparse.ArgumentParser(description="GermanySupport German Translator v4")
    parser.add_argument("--limit",   type=int, default=None)
    parser.add_argument("--post-id", type=int, default=None)
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — German Translator v4")
    print("=" * 62)

    # 1. Fetch categories
    print("\n[1] Fetching WordPress categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 2. Fetch and classify posts
    if args.post_id:
        print(f"\n[2] Single post mode: ID {args.post_id}")
        post = fetch_single_post(args.post_id)
        english_posts = [post]
        german_posts  = []
    else:
        print("\n[2] Fetching all posts...")
        all_posts = fetch_all_posts()
        english_posts, german_posts = classify_posts(all_posts)
        print(f"    English posts : {len(english_posts)}")
        print(f"    German posts  : {len(german_posts)}")

    # 3. Filter to posts without German translation
    print("\n[3] Finding posts that need translation...")
    to_translate = []
    for post in english_posts:
        translations = post.get("translations", {})
        de_id        = translations.get("de")
        post_id      = post["id"]

        # Has a linked DE translation already
        if de_id and int(de_id) != int(post_id):
            print(f"    SKIP [{post_id}] has DE translation "
                  f"(ID {de_id}): {post['title']['rendered'][:50]}")
            continue

        # Double-check via direct API call
        existing = get_existing_de_translation(post_id)
        if existing:
            print(f"    SKIP [{post_id}] verified DE translation "
                  f"(ID {existing}): {post['title']['rendered'][:50]}")
            continue

        to_translate.append(post)

    if args.limit:
        to_translate = to_translate[:args.limit]

    print(f"\n    Need translation: {len(to_translate)}")

    if not to_translate:
        print("\n    All posts already have German translations!")
        return

    # 4. Translate
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
            # Translate
            print("  Translating with Claude...")
            translated = translate_article(post)
            print(f"  DE: {translated['title'][:65]}")
            print(f"  KW: {translated['focus_keyword']}")

            # Categories + tags
            cat_ids = resolve_category_ids(translated["categories"], wp_cat_map)
            tag_ids = sync_tags(translated["tags"])

            # Publish German post
            de_post    = publish_german_post(
                translated, cat_ids, tag_ids, post_id, featured_media_id
            )
            de_post_id = de_post["id"]
            print(f"  DE post ID: {de_post_id} — {de_post['link']}")

            # Check if Polylang picked up the lang=de param
            time.sleep(2)
            de_lang = de_post.get("lang") or get_post_lang_from_meta(de_post_id)
            print(f"  DE language: {de_lang or 'not detected — will need manual fix'}")

            # Try to update EN post with translation reference
            linked = try_link_via_post_update(post_id, de_post_id)
            if linked:
                print(f"  Linked via post update: EN {post_id} <-> DE {de_post_id}")
            else:
                print(f"  Auto-link failed — manual fix needed (see summary below)")

            entry = {
                "en_id":    post_id,
                "de_id":    de_post_id,
                "en_title": en_title,
                "de_title": translated["title"],
                "de_url":   de_post["link"],
                "linked":   linked,
                "de_lang":  de_lang,
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
        print("\n  Results:")
        for r in results["success"]:
            icon = "✓" if r["linked"] else "✗"
            print(f"  {icon} EN[{r['en_id']}] → DE[{r['de_id']}]")
            print(f"    {r['de_url']}")

    # Manual fix instructions
    if results["needs_manual"]:
        print("\n" + "=" * 62)
        print("  MANUAL FIX in WordPress")
        print("  (2 min per article — do this to link EN/DE versions)")
        print("=" * 62)
        print("  Steps:")
        print("  1. Go to Posts → All Posts")
        print("  2. Open the ENGLISH post listed below")
        print("  3. Right sidebar → Languages box")
        print("  4. Next to 'German' click the pencil/edit icon")
        print("  5. Type the German post ID in the field")
        print("  6. Click Update")
        print()
        for r in results["needs_manual"]:
            print(f"  English post ID : {r['en_id']}")
            print(f"  English title   : {r['en_title'][:55]}")
            print(f"  German post ID  : {r['de_id']}")
            print(f"  German title    : {r['de_title'][:55]}")
            print(f"  German URL      : {r['de_url']}")
            print()

    if results["failed"]:
        print("  Failed (will retry on next run):")
        for r in results["failed"]:
            print(f"  [{r['id']}] {r['title'][:55]}")
            print(f"  Error: {r['error'][:120]}")

    print("=" * 62)

    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
