"""
GermanySupport.de — German Article Translator v2
=================================================
Translates English articles into German and correctly registers
them in Polylang using the WordPress wpdb approach via a
temporary helper plugin that we install, use, and remove.

WHY THIS APPROACH:
  Polylang free does not fully expose its language/translation
  linking via the standard REST API. The most reliable way to
  set the language and link translations is through WordPress
  directly using a small temporary REST endpoint that calls
  Polylang's internal PHP functions (pll_set_post_language,
  pll_save_post_translations).

WHAT THIS SCRIPT DOES:
  1. Installs a tiny helper plugin on your WordPress site
     (one PHP file, ~30 lines) via the REST API + WP filesystem
  2. Uses that helper to correctly set language + link translations
  3. Translates articles with Claude
  4. Removes the helper plugin when done

ALTERNATIVE (if plugin install fails):
  The script falls back to setting the `language` parameter
  directly in the post creation call, which works on some
  Polylang configurations.
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
#  🔧  HELPER PLUGIN PHP CODE
#  This tiny plugin adds a secure REST endpoint that calls
#  Polylang's internal functions to set language + link posts.
#  It is installed before the run and deleted after.
# ============================================================
HELPER_PLUGIN_SLUG = "pll-rest-helper"
HELPER_PLUGIN_PHP  = '''<?php
/**
 * Plugin Name: PLL REST Helper
 * Description: Temporary helper for setting Polylang languages via REST API. Delete after use.
 * Version: 1.0
 */
add_action('rest_api_init', function () {
    register_rest_route('pll-helper/v1', '/set-language', [
        'methods'             => 'POST',
        'callback'            => 'pll_helper_set_language',
        'permission_callback' => function () {
            return current_user_can('edit_posts');
        },
    ]);
});

function pll_helper_set_language(WP_REST_Request $request) {
    if (!function_exists('pll_set_post_language') || !function_exists('pll_save_post_translations')) {
        return new WP_Error('no_polylang', 'Polylang not active', ['status' => 500]);
    }

    $en_id = intval($request->get_param('en_id'));
    $de_id = intval($request->get_param('de_id'));

    if (!$en_id || !$de_id) {
        return new WP_Error('missing_params', 'en_id and de_id are required', ['status' => 400]);
    }

    pll_set_post_language($en_id, 'en');
    pll_set_post_language($de_id, 'de');
    pll_save_post_translations(['en' => $en_id, 'de' => $de_id]);

    return [
        'success' => true,
        'en_id'   => $en_id,
        'de_id'   => $de_id,
        'message' => "Linked EN $en_id <-> DE $de_id",
    ];
}
'''

# ============================================================
#  🔧  AUTH HEADERS
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


def wp_post(endpoint, data):
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
#  🔌  HELPER PLUGIN — INSTALL / USE / REMOVE
# ============================================================

def install_helper_plugin():
    """
    Upload the helper plugin PHP file to WordPress via the REST API.
    Uses the WP REST API file upload endpoint available to admins.
    """
    print("  Installing PLL REST helper plugin...")
    php_bytes = HELPER_PLUGIN_PHP.encode("utf-8")

    upload_headers = {
        "Authorization":      HEADERS["Authorization"],
        "Content-Type":       "application/php",
        "Content-Disposition": f'attachment; filename="{HELPER_PLUGIN_SLUG}.php"',
    }

    # Try uploading as a media file first (some hosts allow this)
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/media",
        headers=upload_headers,
        data=php_bytes,
    )

    if r.ok:
        print("  Helper plugin uploaded via media endpoint.")
        return True

    # Fallback: try the WP CLI REST endpoint if available
    print(f"  Media upload failed ({r.status_code}) — trying alternative method...")
    return False


def call_helper_plugin(en_id, de_id):
    """
    Call our helper plugin endpoint to link EN/DE posts in Polylang.
    Returns True on success, False on failure.
    """
    try:
        r = requests.post(
            f"{WP_URL}/wp-json/pll-helper/v1/set-language",
            headers=HEADERS,
            json={"en_id": en_id, "de_id": de_id},
            timeout=15,
        )
        if r.ok:
            data = r.json()
            print(f"  Polylang linked: {data.get('message', 'OK')}")
            return True
        else:
            print(f"  Helper plugin call failed: {r.status_code} {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  Helper plugin call error: {e}")
        return False


def install_plugin_via_wporg(slug="pll-rest-helper"):
    """
    Alternative: install plugin by uploading ZIP via WordPress plugins API.
    We create the plugin ZIP in memory and upload it.
    """
    import io
    import zipfile

    print("  Creating and uploading helper plugin ZIP...")
    try:
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                f"{HELPER_PLUGIN_SLUG}/{HELPER_PLUGIN_SLUG}.php",
                HELPER_PLUGIN_PHP
            )
        zip_buffer.seek(0)
        zip_bytes = zip_buffer.read()

        # Upload via WP REST API plugin install endpoint (WP 5.5+)
        upload_headers = {
            "Authorization":       HEADERS["Authorization"],
            "Content-Type":        "application/zip",
            "Content-Disposition": f'attachment; filename="{HELPER_PLUGIN_SLUG}.zip"',
        }
        r = requests.post(
            f"{WP_URL}/wp-json/wp/v2/plugins",
            headers=upload_headers,
            data=zip_bytes,
        )
        if r.ok:
            plugin_data = r.json()
            print(f"  Plugin installed: {plugin_data.get('name', HELPER_PLUGIN_SLUG)}")
            # Activate it
            activate = requests.put(
                f"{WP_URL}/wp-json/wp/v2/plugins/{HELPER_PLUGIN_SLUG}/{HELPER_PLUGIN_SLUG}",
                headers=HEADERS,
                json={"status": "active"},
            )
            if activate.ok:
                print("  Plugin activated.")
                return True
            else:
                print(f"  Plugin activation failed: {activate.status_code}")
                return False
        else:
            print(f"  Plugin ZIP upload failed: {r.status_code} {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  Plugin install error: {e}")
        return False


def deactivate_and_delete_helper_plugin():
    """Remove the helper plugin after we're done."""
    try:
        plugin_file = f"{HELPER_PLUGIN_SLUG}/{HELPER_PLUGIN_SLUG}"
        # Deactivate
        requests.put(
            f"{WP_URL}/wp-json/wp/v2/plugins/{plugin_file}",
            headers=HEADERS,
            json={"status": "inactive"},
        )
        # Delete
        requests.delete(
            f"{WP_URL}/wp-json/wp/v2/plugins/{plugin_file}",
            headers=HEADERS,
        )
        print("  Helper plugin removed.")
    except Exception as e:
        print(f"  Warning: could not remove helper plugin: {e}")


# ============================================================
#  🌐  POLYLANG LANGUAGE LINKING
# ============================================================

def set_language_and_link(en_id, de_id, helper_available):
    """
    Set Polylang language for both posts and link them as translations.
    Tries multiple methods in order of reliability.
    """
    # Method 1: Use our helper plugin (most reliable)
    if helper_available:
        success = call_helper_plugin(en_id, de_id)
        if success:
            return True

    # Method 2: Use the official Polylang REST API (works on some setups)
    print("  Trying Polylang REST API directly...")
    try:
        # Set EN language
        r1 = requests.post(
            f"{WP_URL}/wp-json/pll/v1/post/{en_id}",
            headers=HEADERS,
            json={"language": "en", "translations": {"de": de_id}},
        )
        # Set DE language
        r2 = requests.post(
            f"{WP_URL}/wp-json/pll/v1/post/{de_id}",
            headers=HEADERS,
            json={"language": "de", "translations": {"en": en_id}},
        )
        if r1.ok and r2.ok:
            print("  Polylang REST API: language set successfully.")
            return True
        else:
            print(f"  Polylang REST API failed: EN={r1.status_code} DE={r2.status_code}")
    except Exception as e:
        print(f"  Polylang REST API error: {e}")

    # Method 3: Set via post meta directly
    # Polylang stores language in term relationships and translations in post meta
    print("  Trying post meta method...")
    try:
        # Get the term ID for the 'de' language in Polylang's taxonomy
        terms = requests.get(
            f"{WP_URL}/wp-json/wp/v2/categories",
            headers=HEADERS,
            params={"taxonomy": "language", "slug": "de", "per_page": 1},
        ).json()

        # Update post meta for the German post
        requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{de_id}",
            headers=HEADERS,
            json={
                "meta": {
                    "_pll_post_language":     "de",
                    "_pll_translations_de":   str(de_id),
                    "_pll_translations_en":   str(en_id),
                }
            },
        )
        print("  Post meta method applied (partial — manual verification recommended).")
        return False  # Partial — still needs verification
    except Exception as e:
        print(f"  Post meta method error: {e}")

    return False


# ============================================================
#  📥  FETCH POSTS
# ============================================================

def fetch_all_english_posts():
    posts = []
    page  = 1
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

        # Only include posts that appear to be in English
        # (filter out posts with German slugs or titles that are already translations)
        for post in batch:
            slug = post.get("slug", "")
            # German slugs typically don't start with common English words
            # We keep posts unless they have a /de/ prefix or german-looking slug
            if not slug.startswith("de-") and "-german-" not in slug[:20]:
                posts.append(post)

        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total_pages} — {len(posts)} EN posts found...")
        if page >= total_pages:
            break
        page += 1
    return posts


def fetch_single_post(post_id):
    return wp_get(f"posts/{post_id}")


def get_all_de_post_slugs():
    """Get slugs of all existing German posts to detect already-translated articles."""
    slugs = set()
    page  = 1
    while True:
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=HEADERS,
            params={
                "per_page": 100,
                "page":     page,
                "status":   "publish",
                "lang":     "de",
                "_fields":  "slug",
            },
        )
        if r.status_code == 400:
            break
        if not r.ok:
            break
        batch = r.json()
        if not batch:
            break
        for post in batch:
            slugs.add(post["slug"])
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break
        page += 1
    return slugs


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
            print(f"      WARNING: Could not match category '{name}'")
    if not ids:
        fallback = "living in germany"
        if fallback in wp_cat_map:
            ids.append(wp_cat_map[fallback])
    return ids


def sync_tags(tag_names):
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
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    en_title   = post["title"]["rendered"]
    en_content = strip_html(post["content"]["rendered"])
    links_str  = "\n".join([f"- {name}: {url}" for name, url in REFERRAL_LINKS.items()])
    cats_str   = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    system_prompt = f"""
Du bist ein professioneller SEO-Texter und Übersetzer, spezialisiert auf
praktische Ratgeber für Expats und Einwanderer in Deutschland.

Übersetze den englischen Artikel ins Deutsche und optimiere ihn vollständig für
die deutsche Suchmaschinenoptimierung.

REGELN:
1. Natürliche, flüssige deutsche Sprache — kein maschineller Stil
2. Deutsche SEO-Keywords verwenden (keine wörtlichen Übersetzungen)
3. Alle HTML-Tags beibehalten (<h2>, <h3>, <p>, <ul>, <li>, <strong>, <a>)
4. Affiliate-Links beibehalten — nur den Linktext übersetzen, nicht die URL
5. Deutsche Meta-Description von GENAU 150-155 Zeichen
6. 10-15 deutsche SEO-Tags generieren
7. Fokus-Keyword im ersten Absatz und in mindestens 2 H2-Überschriften
8. FAQ-Sektion am Ende beibehalten und ins Deutsche übersetzen
9. Ton: hilfreich, freundlich, informativ

KATEGORIE-REGELN:
Wähle NUR aus dieser Liste (exakte Namen):
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
    Create the German post in WordPress.
    Passes lang=de so Polylang can pick it up if the REST param is supported.
    """
    data = {
        "title":      translated["title"],
        "slug":       translated["slug"],
        "content":    translated["content"],
        "excerpt":    translated["meta_description"],
        "status":     "publish",
        "categories": cat_ids,
        "tags":       tag_ids,
        "lang":       "de",          # Polylang REST param (works on some versions)
        "meta": {
            "_yoast_wpseo_metadesc": translated["meta_description"],
            "_yoast_wpseo_focuskw":  translated["focus_keyword"],
            "_aioseop_description":  translated["meta_description"],
            "_aioseop_keywords":     ", ".join(translated["tags"]),
        },
    }
    if featured_media_id:
        data["featured_media"] = featured_media_id

    return wp_post("posts", data)


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport German Translator v2")
    parser.add_argument("--limit",   type=int, default=None)
    parser.add_argument("--post-id", type=int, default=None)
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — German Translator v2")
    print("=" * 62)

    # 1. Fetch categories
    print("\n[1] Fetching WordPress categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    # 2. Try to install helper plugin
    print("\n[2] Setting up Polylang helper...")
    helper_available = install_plugin_via_wporg()
    if not helper_available:
        print("    Helper plugin could not be installed — will use fallback methods.")
        print("    NOTE: You may need to manually fix language flags after this run.")
        print("    See end of script output for manual fix instructions.")

    # 3. Fetch posts
    print("\n[3] Fetching English posts to translate...")
    if args.post_id:
        posts = [fetch_single_post(args.post_id)]
        print(f"    Single post mode: ID {args.post_id}")
    else:
        posts = fetch_all_english_posts()
        if args.limit:
            posts = posts[:args.limit]
        print(f"    Found {len(posts)} posts to process.")

    # 4. Get existing German slugs to skip already-translated posts
    print("\n[4] Checking existing German translations...")
    existing_de_slugs = get_all_de_post_slugs()
    print(f"    Found {len(existing_de_slugs)} existing German posts.")

    to_translate = []
    for post in posts:
        en_slug = post.get("slug", "")
        # Check if a German version likely exists (same slug or slug with -de suffix)
        if en_slug in existing_de_slugs or f"{en_slug}-de" in existing_de_slugs:
            print(f"    SKIP (already translated): {post['title']['rendered'][:50]}")
        else:
            to_translate.append(post)

    print(f"    Need translation: {len(to_translate)}")

    if not to_translate:
        print("\n    All posts already have German versions!")
        if helper_available:
            deactivate_and_delete_helper_plugin()
        return

    # 5. Translate loop
    print(f"\n[5] Translating {len(to_translate)} articles...")
    print("=" * 62)

    results        = {"success": [], "failed": [], "needs_manual": []}
    total          = len(to_translate)

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

            # Resolve categories + tags
            cat_ids = resolve_category_ids(translated["categories"], wp_cat_map)
            tag_ids = sync_tags(translated["tags"])

            # Publish German post
            de_post    = publish_german_post(translated, cat_ids, tag_ids, featured_media_id)
            de_post_id = de_post["id"]
            print(f"  DE post created: ID {de_post_id}")
            print(f"  URL: {de_post['link']}")

            # Link in Polylang
            linked = set_language_and_link(post_id, de_post_id, helper_available)

            result_entry = {
                "en_id":    post_id,
                "de_id":    de_post_id,
                "en_title": en_title,
                "de_title": translated["title"],
                "de_url":   de_post["link"],
                "linked":   linked,
            }
            results["success"].append(result_entry)
            if not linked:
                results["needs_manual"].append(result_entry)

        except Exception as e:
            print(f"  ERROR: {e}")
            results["failed"].append({"id": post_id, "title": en_title, "error": str(e)})

        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s...")
            time.sleep(DELAY_BETWEEN)

    # 6. Cleanup helper plugin
    if helper_available:
        print("\n[6] Removing helper plugin...")
        deactivate_and_delete_helper_plugin()

    # 7. Summary
    print("\n" + "=" * 62)
    print("  TRANSLATION COMPLETE")
    print("=" * 62)
    print(f"  Translated : {len(results['success'])}")
    print(f"  Failed     : {len(results['failed'])}")
    print(f"  Auto-linked: {len(results['success']) - len(results['needs_manual'])}")
    print(f"  Need manual fix: {len(results['needs_manual'])}")

    if results["success"]:
        print("\n  Translated articles:")
        for r in results["success"]:
            status = "linked" if r["linked"] else "NEEDS MANUAL FIX"
            print(f"    EN[{r['en_id']}] → DE[{r['de_id']}] [{status}]")
            print(f"    {r['de_url']}")

    # Manual fix instructions if linking failed
    if results["needs_manual"]:
        print("\n" + "=" * 62)
        print("  MANUAL FIX NEEDED for these posts")
        print("  (Polylang auto-linking failed — do this in WordPress):")
        print("=" * 62)
        print("  For each pair below:")
        print("  1. Go to the ENGLISH post in WP editor")
        print("  2. In right sidebar find 'Languages' box")
        print("  3. Next to 'German' click the pencil icon")
        print("  4. Type the German post ID in the field")
        print("  5. Click Update")
        print()
        for r in results["needs_manual"]:
            print(f"  EN post ID {r['en_id']} ({r['en_title'][:40]})")
            print(f"  DE post ID {r['de_id']} ({r['de_title'][:40]})")
            print()

    if results["failed"]:
        print("\n  Failed:")
        for r in results["failed"]:
            print(f"    [{r['id']}] {r['title'][:55]}: {r['error'][:80]}")

    print("=" * 62)

    if results["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
