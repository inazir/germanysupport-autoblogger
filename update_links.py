"""
GermanySupport.de — Referral Link Updater
==========================================
Scans ALL published articles (English + German) and replaces
old bit.ly links with new /go/ redirect links.

No Claude needed — pure find-and-replace via WordPress REST API.
Fast: processes all articles in 2-3 minutes.

Usage:
  python update_links.py                  # update all articles
  python update_links.py --dry-run        # preview changes without saving
  python update_links.py --post-id 123   # single post only
"""

import os
import re
import base64
import sys
import argparse
import requests

# ============================================================
#  🔑  CREDENTIALS
# ============================================================
WP_URL      = os.environ["WP_URL"].rstrip("/")
WP_USER     = os.environ["WP_USER"]
WP_APP_PASS = os.environ["WP_APP_PASS"]

# ============================================================
#  🔄  LINK REPLACEMENT MAP
#  old url → new url
#  Add/edit as needed to match your Redirection plugin setup
# ============================================================
LINK_MAP = {
    # BANKING
    "https://bit.ly/3IXPFSh": "https://germanysupport.de/go/n26",
    "https://bit.ly/3EED0Uc": "https://germanysupport.de/go/c24",
    "https://bit.ly/4hKu4ul": "https://germanysupport.de/go/advanzia",
    "https://bit.ly/41xi8Ht": "https://germanysupport.de/go/credit-cards",
    "https://bit.ly/gscrdt":  "https://germanysupport.de/go/credit-cards",
    "https://bit.ly/3Z5B13n": "https://germanysupport.de/go/trade-republic",
    # INSURANCE
    "https://bit.ly/3ik93KM": "https://germanysupport.de/go/haftpflicht",
    "https://bit.ly/3IBfR1l": "https://germanysupport.de/go/haftpflicht",
    "https://bit.ly/3tveWdm": "https://germanysupport.de/go/huk24",
    "https://bit.ly/3IXJxXD": "https://germanysupport.de/go/car-insurance",
    # TAX
    "https://bit.ly/3XDNBW8": "https://germanysupport.de/go/steuergo",
    "https://bit.ly/3NLm1BE": "https://germanysupport.de/go/wiso",
    # INTERNET & MOBILE
    "https://bit.ly/474daFa": "https://germanysupport.de/go/verivox-dsl",
    "https://bit.ly/3MFz9WH": "https://germanysupport.de/go/dsl-check24",
    "https://bit.ly/4paMQ2e": "https://germanysupport.de/go/klarmobil",
    "https://bit.ly/3BVAAiI": "https://germanysupport.de/go/check24-mobile",
    "https://bit.ly/3iVS0mb": "https://germanysupport.de/go/congstar",
    # UTILITIES
    "https://bit.ly/chk24strm": "https://germanysupport.de/go/electricity",
    "https://bit.ly/gasbgg":    "https://germanysupport.de/go/gas",
    # TRAVEL
    "https://bit.ly/bgstrip": "https://germanysupport.de/go/travel",
    "https://bit.ly/mtwgn":   "https://germanysupport.de/go/car-rental",
    # MONEY TRANSFER
    "https://bit.ly/3qq18Ab": "https://germanysupport.de/go/ace",
    "https://bit.ly/3qj6JYG": "https://germanysupport.de/go/taptap",
    # CASHBACK
    "https://bit.ly/3r3tW1p": "https://germanysupport.de/go/shoop",
    "https://bit.ly/38lWA7P": "https://germanysupport.de/go/igraal",
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


def replace_links(html):
    """Replace all old bit.ly links with new /go/ links."""
    if not html:
        return html, 0
    count = 0
    for old_url, new_url in LINK_MAP.items():
        if old_url in html:
            occurrences = html.count(old_url)
            html  = html.replace(old_url, new_url)
            count += occurrences
    return html, count


def fetch_all_posts():
    """Fetch ALL published posts (both EN and DE)."""
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
                "context":  "edit",
                "_fields":  "id,title,content,link",
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
        print(f"  Page {page}/{total_pages} — {len(posts)} posts...")
        if page >= total_pages:
            break
        page += 1
    return posts


def fetch_single_post(post_id):
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        params={"context": "edit"},
    )
    r.raise_for_status()
    return r.json()


def update_post_content(post_id, new_content):
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        json={"content": new_content},
    )
    if not r.ok:
        raise Exception(f"Update failed: {r.status_code} {r.text[:200]}")
    return r.json()


def main():
    parser = argparse.ArgumentParser(description="GermanySupport Link Updater")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Preview changes without saving")
    parser.add_argument("--post-id", type=int, default=None,
                        help="Update a single post by ID")
    args = parser.parse_args()

    print("=" * 62)
    print("  GermanySupport.de — Referral Link Updater")
    if args.dry_run:
        print("  MODE: DRY RUN — no changes will be saved")
    print("=" * 62)
    print(f"\n  Replacing {len(LINK_MAP)} old bit.ly links with /go/ links")

    # Fetch posts
    print()
    if args.post_id:
        posts = [fetch_single_post(args.post_id)]
        print(f"  Single post mode: ID {args.post_id}")
    else:
        posts = fetch_all_posts()
        print(f"  Found {len(posts)} posts to scan.")

    print("\n" + "=" * 62)

    results = {
        "updated":  [],
        "no_links": [],
        "failed":   [],
    }
    total_replacements = 0

    for i, post in enumerate(posts, 1):
        post_id = post["id"]
        title   = post["title"]["rendered"]
        content = post.get("content", {}).get("raw", "") or \
                  post.get("content", {}).get("rendered", "")

        new_content, count = replace_links(content)

        if count == 0:
            results["no_links"].append(post_id)
            continue

        total_replacements += count
        print(f"  [{i}] Post {post_id}: {count} link(s) replaced")
        print(f"       {title[:60]}")

        if not args.dry_run:
            try:
                update_post_content(post_id, new_content)
                print(f"       ✓ Saved")
                results["updated"].append({
                    "id":    post_id,
                    "title": title,
                    "count": count,
                    "url":   post.get("link", ""),
                })
            except Exception as e:
                print(f"       ✗ ERROR: {e}")
                results["failed"].append({
                    "id":    post_id,
                    "title": title,
                    "error": str(e),
                })
        else:
            print(f"       (dry run — not saved)")
            results["updated"].append({
                "id":    post_id,
                "title": title,
                "count": count,
                "url":   post.get("link", ""),
            })

    # Summary
    print("\n" + "=" * 62)
    print("  LINK UPDATE COMPLETE")
    print("=" * 62)
    print(f"  Total posts scanned      : {len(posts)}")
    print(f"  Posts with links updated : {len(results['updated'])}")
    print(f"  Posts with no old links  : {len(results['no_links'])}")
    print(f"  Total replacements made  : {total_replacements}")
    print(f"  Failed                   : {len(results['failed'])}")

    if args.dry_run and results["updated"]:
        print("\n  (DRY RUN — run without --dry-run to save changes)")

    if results["failed"]:
        print("\n  Failed posts:")
        for r in results["failed"]:
            print(f"  [{r['id']}] {r['title'][:55]}: {r['error'][:80]}")
        sys.exit(1)

    print("=" * 62)


if __name__ == "__main__":
    main()
