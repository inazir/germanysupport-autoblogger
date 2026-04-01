"""GermanySupport.de — Multi Link + Anchor Text Replacer
====================================================
Scans published WordPress articles and replaces multiple internal /go/ links
and visible anchor text values in one run.

This version is designed for the current setup:
- no bit.ly handling
- no Claude/OpenAI calls
- direct replacements passed via CLI

Examples:
  python update_links.py \
    --replace steuergo:wiso \
    --replace taptap:wise \
    --dry-run

  python update_links.py \
    --replace steuergo:wiso:SteuerGo:WISO\ Steuer \
    --replace advanzia:credit-cards:Advanzia\ Mastercard:Credit\ Card\ Comparison

Replacement format:
  --replace old_slug:new_slug
  --replace old_slug:new_slug:old_text:new_text

If old_text/new_text are omitted, the script defaults to old_slug/new_slug.
Only anchor text inside <a>...</a> tags is changed. Normal body text outside links
is left untouched.

Requires env vars:
  WP_URL
  WP_USER
  WP_APP_PASS
"""

import os
import re
import sys
import base64
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import requests

WP_URL = os.environ["WP_URL"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_APP_PASS = os.environ["WP_APP_PASS"]


class ReplacementSpecError(ValueError):
    pass


def build_auth_headers() -> Dict[str, str]:
    credentials = f"{WP_USER}:{WP_APP_PASS}"
    token = base64.b64encode(credentials.encode()).decode("utf-8")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


HEADERS = build_auth_headers()


def normalize_slug(value: str) -> str:
    return value.strip().strip("/").lower()


def variants_for_slug(slug: str) -> List[str]:
    slug = normalize_slug(slug)
    return [
        f"/go/{slug}",
        f"https://germanysupport.de/go/{slug}",
        f"https://www.germanysupport.de/go/{slug}",
        f"http://germanysupport.de/go/{slug}",
        f"http://www.germanysupport.de/go/{slug}",
    ]


def parse_replace_spec(spec: str) -> Dict[str, str]:
    parts = spec.split(":")
    if len(parts) not in (2, 4):
        raise ReplacementSpecError(
            "Each --replace must be in one of these formats: "
            "old_slug:new_slug OR old_slug:new_slug:old_text:new_text"
        )

    old_slug = normalize_slug(parts[0])
    new_slug = normalize_slug(parts[1])

    if not old_slug or not new_slug:
        raise ReplacementSpecError("old_slug and new_slug must not be empty")

    if len(parts) == 2:
        old_text = parts[0]
        new_text = parts[1]
    else:
        old_text = parts[2]
        new_text = parts[3]

    return {
        "old_slug": old_slug,
        "new_slug": new_slug,
        "old_text": old_text,
        "new_text": new_text,
    }


def parse_replace_file(path: str) -> List[Dict[str, str]]:
    specs: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                specs.append(parse_replace_spec(line))
            except ReplacementSpecError as exc:
                raise ReplacementSpecError(f"{path}:{line_no}: {exc}") from exc
    return specs


def dedupe_specs(specs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    deduped = []
    for spec in specs:
        key = (spec["old_slug"], spec["new_slug"], spec["old_text"], spec["new_text"])
        if key not in seen:
            seen.add(key)
            deduped.append(spec)
    return deduped


def replace_href_variants(html: str, old_slug: str, new_slug: str) -> Tuple[str, int]:
    count = 0
    updated = html
    for old_variant, new_variant in zip(variants_for_slug(old_slug), variants_for_slug(new_slug)):
        occurrences = updated.count(old_variant)
        if occurrences:
            updated = updated.replace(old_variant, new_variant)
            count += occurrences
    return updated, count


ANCHOR_PATTERN = re.compile(r"(<a\b[^>]*>)(.*?)(</a>)", flags=re.IGNORECASE | re.DOTALL)


def replace_anchor_text(html: str, old_text: str, new_text: str) -> Tuple[str, int]:
    text_pattern = re.compile(re.escape(old_text), flags=re.IGNORECASE)
    replacements = 0

    def repl(match):
        nonlocal replacements
        open_tag, inner_html, close_tag = match.groups()
        new_inner, local_count = text_pattern.subn(new_text, inner_html)
        replacements += local_count
        return f"{open_tag}{new_inner}{close_tag}"

    updated = ANCHOR_PATTERN.sub(repl, html)
    return updated, replacements


def replace_plain_url_text(html: str, old_slug: str, new_slug: str) -> Tuple[str, int]:
    count = 0
    updated = html
    for old_variant, new_variant in zip(variants_for_slug(old_slug), variants_for_slug(new_slug)):
        occurrences = updated.count(old_variant)
        if occurrences:
            updated = updated.replace(old_variant, new_variant)
            count += occurrences
    return updated, count


def empty_stats() -> Dict[str, int]:
    return {
        "href_replacements": 0,
        "anchor_text_replacements": 0,
        "plain_url_text_replacements": 0,
        "total_replacements": 0,
    }


def add_stats(target: Dict[str, int], source: Dict[str, int]) -> None:
    for key in target:
        target[key] += source[key]


def apply_one_replacement(html: str, spec: Dict[str, str]) -> Tuple[str, Dict[str, int]]:
    updated = html
    stats = empty_stats()

    updated, href_count = replace_href_variants(updated, spec["old_slug"], spec["new_slug"])
    updated, anchor_count = replace_anchor_text(updated, spec["old_text"], spec["new_text"])
    updated, plain_url_count = replace_plain_url_text(updated, spec["old_slug"], spec["new_slug"])

    stats["href_replacements"] = href_count
    stats["anchor_text_replacements"] = anchor_count
    stats["plain_url_text_replacements"] = plain_url_count
    stats["total_replacements"] = href_count + anchor_count + plain_url_count
    return updated, stats


def replace_post_content(html: str, specs: List[Dict[str, str]]) -> Tuple[str, Dict[str, int], List[Dict[str, object]]]:
    if not html:
        return html, empty_stats(), []

    updated = html
    grand_stats = empty_stats()
    spec_results: List[Dict[str, object]] = []

    for spec in specs:
        updated, stats = apply_one_replacement(updated, spec)
        add_stats(grand_stats, stats)
        if stats["total_replacements"] > 0:
            spec_results.append({"spec": spec, "stats": stats})

    return updated, grand_stats, spec_results


def fetch_all_posts(days=None):
    posts = []
    page = 1
    params_base = {
        "per_page": 20,
        "status": "publish",
        "context": "edit",
        "_fields": "id,title,content,link,date",
    }

    if days is not None:
        after_dt = datetime.now(timezone.utc) - timedelta(days=days)
        params_base["after"] = after_dt.isoformat()
        print(f"  Filter: posts after {after_dt.isoformat()}")

    print("  Fetching published posts...")
    while True:
        params = dict(params_base)
        params["page"] = page
        r = requests.get(f"{WP_URL}/wp-json/wp/v2/posts", headers=HEADERS, params=params, timeout=60)
        if r.status_code == 400:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        total_pages = int(r.headers.get("X-WP-TotalPages", 1))
        print(f"  Page {page}/{total_pages} — {len(posts)} posts collected...")
        if page >= total_pages:
            break
        page += 1
    return posts


def fetch_single_post(post_id):
    r = requests.get(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        params={"context": "edit"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def update_post_content(post_id, new_content):
    r = requests.post(
        f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
        headers=HEADERS,
        json={"content": new_content},
        timeout=60,
    )
    if not r.ok:
        raise Exception(f"Update failed: {r.status_code} {r.text[:300]}")
    return r.json()


def load_specs(args) -> List[Dict[str, str]]:
    specs: List[Dict[str, str]] = []
    if args.replace:
        for spec in args.replace:
            specs.append(parse_replace_spec(spec))
    if args.replace_file:
        specs.extend(parse_replace_file(args.replace_file))

    specs = dedupe_specs(specs)

    if not specs:
        raise ReplacementSpecError("Provide at least one --replace or --replace-file")
    return specs


def main():
    parser = argparse.ArgumentParser(description="Replace multiple internal /go/ links and anchor text values")
    parser.add_argument(
        "--replace",
        action="append",
        help=(
            "Replacement spec. Use multiple times. Formats: "
            "old_slug:new_slug OR old_slug:new_slug:old_text:new_text"
        ),
    )
    parser.add_argument(
        "--replace-file",
        help="Optional text file with one replacement spec per line",
    )
    parser.add_argument("--post-id", type=int, default=None, help="Only process one post ID")
    parser.add_argument("--days", type=int, default=None, help="Only scan posts from the last N days")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not save")
    args = parser.parse_args()

    try:
        specs = load_specs(args)
    except ReplacementSpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    print("=" * 78)
    print("  GermanySupport.de — Multi Link + Anchor Text Replacer")
    print("=" * 78)
    print(f"  Replacements   : {len(specs)}")
    for idx, spec in enumerate(specs, start=1):
        print(
            f"  [{idx}] /go/{spec['old_slug']} -> /go/{spec['new_slug']} | "
            f"text: {spec['old_text']!r} -> {spec['new_text']!r}"
        )
    if args.dry_run:
        print("  MODE           : DRY RUN (nothing will be saved)")
    if args.post_id:
        print(f"  Scope          : single post {args.post_id}")
    elif args.days is not None:
        print(f"  Scope          : published posts from last {args.days} days")
    else:
        print("  Scope          : all published posts")
    print("=" * 78)
    print()

    if args.post_id:
        posts = [fetch_single_post(args.post_id)]
    else:
        posts = fetch_all_posts(days=args.days)

    print(f"  Found {len(posts)} post(s) to scan.")
    print("\n" + "=" * 78)

    updated_posts = []
    no_change_posts = []
    failed_posts = []
    grand_total = empty_stats()

    for idx, post in enumerate(posts, 1):
        post_id = post["id"]
        title = post.get("title", {}).get("rendered", f"Post {post_id}")
        content_obj = post.get("content", {})
        content = content_obj.get("raw", "") or content_obj.get("rendered", "") or ""

        new_content, stats, spec_results = replace_post_content(content, specs)

        if stats["total_replacements"] == 0:
            no_change_posts.append(post_id)
            continue

        print(f"  [{idx}] Post {post_id}: {title[:70]}")
        for result in spec_results:
            spec = result["spec"]
            spec_stats = result["stats"]
            print(
                f"       {spec['old_slug']} -> {spec['new_slug']} | "
                f"href={spec_stats['href_replacements']}, "
                f"anchor={spec_stats['anchor_text_replacements']}, "
                f"plain={spec_stats['plain_url_text_replacements']}, "
                f"total={spec_stats['total_replacements']}"
            )
        print(f"       post total              : {stats['total_replacements']}")

        if args.dry_run:
            print("       (dry run — not saved)")
            updated_posts.append({"id": post_id, "title": title, "stats": stats})
        else:
            try:
                update_post_content(post_id, new_content)
                print("       ✓ Saved")
                updated_posts.append({"id": post_id, "title": title, "stats": stats})
            except Exception as exc:
                print(f"       ✗ ERROR: {exc}")
                failed_posts.append({"id": post_id, "title": title, "error": str(exc)})
                continue

        add_stats(grand_total, stats)

    print("\n" + "=" * 78)
    print("  COMPLETE")
    print("=" * 78)
    print(f"  Total posts scanned          : {len(posts)}")
    print(f"  Posts updated                : {len(updated_posts)}")
    print(f"  Posts with no change         : {len(no_change_posts)}")
    print(f"  Failed posts                 : {len(failed_posts)}")
    print(f"  href replacements            : {grand_total['href_replacements']}")
    print(f"  anchor text replacements     : {grand_total['anchor_text_replacements']}")
    print(f"  plain URL text replacements  : {grand_total['plain_url_text_replacements']}")
    print(f"  total replacements           : {grand_total['total_replacements']}")

    if args.dry_run and updated_posts:
        print("\n  Dry run finished. Re-run without --dry-run to save changes.")

    if failed_posts:
        print("\n  Failed posts:")
        for item in failed_posts:
            print(f"  [{item['id']}] {item['title'][:55]}: {item['error'][:120]}")
        sys.exit(1)

    print("=" * 78)


if __name__ == "__main__":
    main()
