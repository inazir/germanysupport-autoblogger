"""
GermanySupport.de — German Article Translator v5
=================================================
Imports shared config from config.py (single source of truth).
Translates English articles into German with SEO optimization.

Requires: Polylang plugin installed and German language added.
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

# ============================================================
#  ⚙️  SETTINGS
# ============================================================
DELAY_BETWEEN = 8
LANG_EN       = "en"
LANG_DE       = "de"

# ============================================================
#  🔧  AUTH
# ============================================================

def build_auth_headers():
    credentials = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

HEADERS = build_auth_headers()


def wp_get(endpoint, params=None):
    r = requests.get(f"{WP_URL}/wp-json/wp/v2/{endpoint}",
                     headers=HEADERS, params=params or {})
    r.raise_for_status()
    return r.json()


def wp_post_req(endpoint, data):
    r = requests.post(f"{WP_URL}/wp-json/wp/v2/{endpoint}",
                      headers=HEADERS, json=data)
    if not r.ok:
        raise Exception(f"WP POST error {r.status_code}: {r.text[:400]}")
    return r.json()


def strip_html(html):
    return re.sub(r"<[^>]+>", " ", html or "")


# ============================================================
#  🧹  ROBUST JSON PARSER
# ============================================================

def parse_claude_json(raw_text):
    text = raw_text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*",     "", text)
    text = re.sub(r"```$",        "", text).strip()
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
#  🌐  POLYLANG HELPERS
# ============================================================

def get_existing_de_translation(en_post_id):
    try:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts/{en_post_id}",
                         headers=HEADERS, params={"_fields": "id,translations,lang"})
        if r.ok:
            data = r.json()
            translations = data.get("translations", {})
            de_id = translations.get("de")
            if de_id and int(de_id) != int(en_post_id):
                return int(de_id)
    except Exception:
        pass
    return None


def try_link_translations(en_id, de_id):
    try:
        r1 = requests.post(f"{WP_URL}/wp-json/wp/v2/posts/{en_id}",
                           headers=HEADERS,
                           json={"lang": "en", "translations": {"en": en_id, "de": de_id}})
        r2 = requests.post(f"{WP_URL}/wp-json/wp/v2/posts/{de_id}",
                           headers=HEADERS,
                           json={"lang": "de", "translations": {"en": en_id, "de": de_id}})
        if r1.ok and r2.ok:
            print(f"  Polylang: linked EN {en_id} <-> DE {de_id} ✓")
            return True
        print(f"  Polylang link: EN={r1.status_code} DE={r2.status_code}")
        return False
    except Exception as e:
        print(f"  Polylang error: {e}")
        return False


# ============================================================
#  📥  FETCH POSTS
# ============================================================

def fetch_all_posts():
    posts, page = [], 1
    print("  Fetching all published posts...")
    while True:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts", headers=HEADERS,
                         params={"per_page": 20, "page": page, "status": "publish",
                                 "_fields": "id,title,slug,content,excerpt,tags,"
                                            "categories,featured_media,lang,translations,link"})
        if r.status_code == 400: break
        r.raise_for_status()
        batch = r.json()
        if not batch: break
        posts.extend(batch)
        total = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total} — {len(posts)} posts...")
        if page >= total: break
        page += 1
    return posts


def classify_posts(all_posts):
    english_posts, german_posts = [], []
    for post in all_posts:
        lang  = post.get("lang", "")
        link  = post.get("link", "")
        trans = post.get("translations", {})

        if lang == "de" or "/de/" in link:
            german_posts.append(post); continue
        if lang == "en":
            english_posts.append(post); continue

        en_id = trans.get("en")
        de_id = trans.get("de")
        if en_id and de_id:
            if int(de_id) == int(post["id"]) and int(en_id) != int(post["id"]):
                german_posts.append(post); continue
            if int(en_id) == int(post["id"]) and int(de_id) != int(post["id"]):
                english_posts.append(post); continue

        english_posts.append(post)
    return english_posts, german_posts


def fetch_single_post(post_id):
    r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts/{post_id}", headers=HEADERS,
                     params={"_fields": "id,title,slug,content,excerpt,tags,"
                                        "categories,featured_media,lang,translations"})
    r.raise_for_status()
    return r.json()


# ============================================================
#  📂  CATEGORIES & TAGS
# ============================================================

def fetch_wp_categories():
    cat_map, page = {}, 1
    while True:
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/categories", headers=HEADERS,
                         params={"per_page": 100, "page": page, "_fields": "id,name"})
        if r.status_code == 400: break
        r.raise_for_status()
        for cat in r.json(): cat_map[cat["name"].lower()] = cat["id"]
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
            t = wp_post_req("tags", {"name": name})
            ids.append(t["id"])
        except Exception:
            s = requests.get(f"{WP_URL}/wp-json/wp/v2/tags", headers=HEADERS,
                             params={"search": name, "per_page": 1}).json()
            if s: ids.append(s[0]["id"])
    return ids


# ============================================================
#  🤖  CLAUDE TRANSLATION
# ============================================================

def translate_article(post):
    client    = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    en_title  = post["title"]["rendered"]
    en_content = strip_html(post["content"]["rendered"])

    # Get relevant links for this article topic
    rel_links = get_relevant_links(en_title, en_content)
    links_str = format_links_for_prompt(rel_links)
    cats_str  = "\n".join(f"- {c}" for c in ALLOWED_CATEGORIES)

    system_prompt = f"""
Du bist ein professioneller SEO-Texter und Übersetzer für Expats in Deutschland.
Übersetze den englischen Artikel ins Deutsche und optimiere ihn für deutsche SEO.
Jahr: {CURRENT_YEAR}.

WICHTIG — JSON-AUSGABE-REGELN:
- Alle Anführungszeichen im Content MÜSSEN escaped sein: \\" nicht "
- Keine typografischen Anführungszeichen
- Vollständiges gültiges JSON
- Keine Zeilenumbrüche in JSON-Strings

ÜBERSETZUNGSREGELN:
1. Natürliche, flüssige deutsche Sprache
2. Deutsche SEO-Keywords verwenden
3. Alle HTML-Tags beibehalten
4. Affiliate-Links beibehalten — nur Linktext übersetzen, URLs NICHT ändern
5. Deutsche Meta-Description von GENAU 150-155 Zeichen
6. 10-15 deutsche SEO-Tags
7. Fokus-Keyword im ersten Absatz und in 2+ H2-Überschriften

SPEZIALREGEL für TapTap Send:
Immer Promo-Code IQBAL12 erwähnen: "{TAPTAP_PROMO_TEXT}"

KATEGORIE — 1-2, NUR aus dieser Liste (exakte Namen):
{cats_str}

Ausgabe NUR als gültiges JSON:
{{
  "title": "Deutscher Titel {CURRENT_YEAR}",
  "slug": "deutscher-url-slug",
  "meta_description": "Genau 150-155 Zeichen",
  "focus_keyword": "deutscher SEO-Begriff",
  "tags": ["tag1", "tag2"],
  "categories": ["Category Name"],
  "content": "Vollständiger HTML-Inhalt auf Deutsch"
}}
"""

    user_prompt = f"""
Übersetze und optimiere diesen englischen Artikel für deutschsprachige Expats.

TITEL: {en_title}
INHALT:
{en_content[:5000]}

Affiliate-Links (Linktext übersetzen, URLs NICHT ändern):
{links_str}

Ausgabe NUR als rohes JSON-Objekt.
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}])
    return parse_claude_json(response.content[0].text)


# ============================================================
#  📤  PUBLISH GERMAN POST
# ============================================================

def publish_german_post(translated, cat_ids, tag_ids, en_post_id, featured_media_id=None):
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
            "rank_math_focus_keyword": translated["focus_keyword"],
            "rank_math_description":   translated["meta_description"],
        },
    }
    if featured_media_id:
        data["featured_media"] = featured_media_id
    return wp_post_req("posts", data)


# ============================================================
#  🚀  MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="GermanySupport German Translator v5")
    parser.add_argument("--limit",   type=int, default=None)
    parser.add_argument("--post-id", type=int, default=None)
    args = parser.parse_args()

    print("=" * 62)
    print(f"  GermanySupport.de — German Translator v5 ({CURRENT_YEAR})")
    print("=" * 62)

    print("\n[1] Fetching WordPress categories...")
    wp_cat_map = fetch_wp_categories()
    print(f"    Found {len(wp_cat_map)} categories.")

    if args.post_id:
        print(f"\n[2] Single post mode: ID {args.post_id}")
        post = fetch_single_post(args.post_id)
        english_posts = [post]
    else:
        print("\n[2] Fetching and classifying posts...")
        all_posts = fetch_all_posts()
        english_posts, german_posts = classify_posts(all_posts)
        print(f"    English: {len(english_posts)} | German: {len(german_posts)}")

    print("\n[3] Checking which posts need translation...")
    to_translate = []
    for post in english_posts:
        pid   = post["id"]
        trans = post.get("translations", {})
        de_id = trans.get("de")
        if de_id and int(de_id) != int(pid):
            print(f"    SKIP [{pid}] already has DE (ID {de_id}): "
                  f"{post['title']['rendered'][:50]}")
            continue
        existing = get_existing_de_translation(pid)
        if existing:
            print(f"    SKIP [{pid}] verified DE (ID {existing})")
            continue
        to_translate.append(post)

    if args.limit:
        to_translate = to_translate[:args.limit]

    print(f"\n    Need translation: {len(to_translate)}")

    if not to_translate:
        print("\n    All posts already have German translations!")
        return

    print(f"\n[4] Translating {len(to_translate)} articles...")
    print("=" * 62)

    results = {"success": [], "failed": [], "needs_manual": []}
    total   = len(to_translate)

    for i, post in enumerate(to_translate, 1):
        pid      = post["id"]
        en_title = post["title"]["rendered"]
        media_id = post.get("featured_media") or None

        print(f"\n[{i}/{total}] Post ID {pid}")
        print(f"  EN: {en_title[:65]}")

        try:
            print("  Translating with Claude...")
            translated = translate_article(post)
            print(f"  DE: {translated['title'][:65]}")
            print(f"  KW: {translated['focus_keyword']}")

            cat_ids = resolve_category_ids(translated["categories"], wp_cat_map)
            tag_ids = sync_tags(translated["tags"])

            de_post    = publish_german_post(translated, cat_ids, tag_ids, pid, media_id)
            de_post_id = de_post["id"]
            print(f"  DE post: ID {de_post_id} — {de_post['link']}")

            linked = try_link_translations(pid, de_post_id)

            entry = {
                "en_id": pid, "de_id": de_post_id,
                "en_title": en_title, "de_title": translated["title"],
                "de_url": de_post["link"], "linked": linked,
            }
            results["success"].append(entry)
            if not linked:
                results["needs_manual"].append(entry)

        except Exception as e:
            print(f"  ERROR: {e}")
            results["failed"].append({"id": pid, "title": en_title, "error": str(e)})

        if i < total:
            print(f"  Waiting {DELAY_BETWEEN}s...")
            time.sleep(DELAY_BETWEEN)

    print("\n" + "=" * 62)
    print("  TRANSLATION COMPLETE")
    print("=" * 62)
    print(f"  Translated     : {len(results['success'])}")
    print(f"  Auto-linked    : {len([r for r in results['success'] if r['linked']])}")
    print(f"  Needs manual   : {len(results['needs_manual'])}")
    print(f"  Failed         : {len(results['failed'])}")

    if results["success"]:
        print("\n  Translated:")
        for r in results["success"]:
            icon = "✓" if r["linked"] else "✗"
            print(f"  {icon} EN[{r['en_id']}] → DE[{r['de_id']}] {r['de_url']}")

    if results["needs_manual"]:
        print("\n" + "=" * 62)
        print("  MANUAL FIX: Link these in WP editor (Languages box)")
        print("=" * 62)
        for r in results["needs_manual"]:
            print(f"  EN ID: {r['en_id']}  DE ID: {r['de_id']}")
            print(f"  {r['de_url']}")

    if results["failed"]:
        print("\n  Failed:")
        for r in results["failed"]:
            print(f"  [{r['id']}] {r['title'][:55]}: {r['error'][:80]}")
        sys.exit(1)


if __name__ == "__main__":
    main()