# social/share_existing_articles.py
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


def load_env_file() -> None:
    """
    Minimal .env loader.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file()


@dataclass
class ArticleCandidate:
    post_id: int
    title: str
    link: str
    excerpt: str
    date_gmt: Optional[datetime]
    image_url: Optional[str]
    categories: List[str]
    tags: List[str]
    slug: str


class ShareExistingArticlesError(RuntimeError):
    pass


def env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ShareExistingArticlesError(f"Missing required env var: {name}")
    return value


def get_wp_api_base() -> str:
    base = (
        os.getenv("WP_URL", "").strip()
        or os.getenv("WORDPRESS_URL", "").strip()
        or os.getenv("SITE_URL", "").strip()
    )
    if not base:
        raise ShareExistingArticlesError(
            "Missing WP_URL/WORDPRESS_URL/SITE_URL in environment"
        )
    return base.rstrip("/") + "/wp-json/wp/v2"


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split()).strip()


def strip_html(value: str) -> str:
    import re

    value = value or ""
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"</p\s*>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("&amp;", "&").replace("&quot;", '"').replace("&#8211;", "-")
    value = value.replace("&#8217;", "'").replace("&nbsp;", " ")
    return normalize_text(value)


def parse_wp_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def parse_http_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def extract_featured_image(post: Dict[str, Any]) -> Optional[str]:
    embedded = post.get("_embedded") or {}
    media_items = embedded.get("wp:featuredmedia") or []
    if not media_items:
        return None

    media = media_items[0]
    if not isinstance(media, dict):
        return None

    source_url = media.get("source_url")
    if source_url:
        return str(source_url)

    media_details = media.get("media_details") or {}
    sizes = media_details.get("sizes") or {}
    for preferred in ("large", "medium_large", "medium", "full"):
        size_obj = sizes.get(preferred)
        if isinstance(size_obj, dict) and size_obj.get("source_url"):
            return str(size_obj["source_url"])

    return None


def extract_terms(post: Dict[str, Any]) -> tuple[list[str], list[str]]:
    embedded = post.get("_embedded") or {}
    term_groups = embedded.get("wp:term") or []

    categories: List[str] = []
    tags: List[str] = []

    for group in term_groups:
        if not isinstance(group, list):
            continue
        for term in group:
            if not isinstance(term, dict):
                continue
            taxonomy = term.get("taxonomy")
            name = term.get("name")
            if not name:
                continue
            if taxonomy == "category":
                categories.append(str(name))
            elif taxonomy == "post_tag":
                tags.append(str(name))

    return categories, tags


def build_candidate(post: Dict[str, Any]) -> ArticleCandidate:
    title = strip_html((post.get("title") or {}).get("rendered", ""))
    excerpt = strip_html((post.get("excerpt") or {}).get("rendered", ""))

    categories, tags = extract_terms(post)

    return ArticleCandidate(
        post_id=int(post["id"]),
        title=title,
        link=str(post["link"]),
        excerpt=excerpt,
        date_gmt=parse_wp_date(post.get("date_gmt")),
        image_url=extract_featured_image(post),
        categories=categories,
        tags=tags,
        slug=str(post.get("slug", "")),
    )


def fetch_posts(api_base: str, per_page: int, max_pages: int) -> List[Dict[str, Any]]:
    posts: List[Dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        url = f"{api_base}/posts"
        params = {
            "status": "publish",
            "per_page": per_page,
            "page": page,
            "_embed": "wp:featuredmedia,wp:term",
            "_fields": ",".join(
                [
                    "id",
                    "slug",
                    "date_gmt",
                    "link",
                    "title",
                    "excerpt",
                    "_embedded",
                ]
            ),
        }

        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 400:
            break
        resp.raise_for_status()

        page_items = resp.json()
        if not page_items:
            break

        posts.extend(page_items)

        total_pages = int(resp.headers.get("X-WP-TotalPages", str(page)))
        if page >= total_pages:
            break

    return posts


def filter_candidates(
    candidates: List[ArticleCandidate],
    *,
    min_age_days: int,
    max_age_days: Optional[int],
    exclude_ids: set[int],
    include_categories: Optional[set[str]],
    exclude_categories: set[str],
    require_image: bool,
    exclude_slugs: set[str],
) -> List[ArticleCandidate]:
    now = datetime.now(timezone.utc)
    out: List[ArticleCandidate] = []

    for c in candidates:
        if c.post_id in exclude_ids:
            continue

        if c.slug and c.slug in exclude_slugs:
            continue

        if require_image and not c.image_url:
            continue

        if c.date_gmt:
            post_dt = c.date_gmt
            if post_dt.tzinfo is None:
                post_dt = post_dt.replace(tzinfo=timezone.utc)
            age_days = (now - post_dt).days
            if age_days < min_age_days:
                continue
            if max_age_days is not None and age_days > max_age_days:
                continue

        lower_categories = {x.strip().lower() for x in c.categories}
        if include_categories and not (lower_categories & include_categories):
            continue
        if exclude_categories and (lower_categories & exclude_categories):
            continue

        out.append(c)

    return out


def get_social_history_path() -> Path:
    default_path = Path("social/cache/shared_articles_history.json")
    configured = os.getenv("SOCIAL_SHARED_HISTORY_PATH", "").strip()
    if configured:
        return Path(configured)
    return default_path


def load_history(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_history(path: Path, history: Dict[str, Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def was_shared_recently(
    history: Dict[str, Dict[str, str]],
    *,
    target_key: str,
    post_id: int,
    cooldown_days: int,
) -> bool:
    target_history = history.get(target_key, {})
    ts_raw = target_history.get(str(post_id))
    if not ts_raw:
        return False

    ts = parse_http_datetime(ts_raw) or parse_wp_date(ts_raw)
    if ts is None:
        try:
            ts = datetime.fromisoformat(ts_raw)
        except Exception:
            return False

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    threshold = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
    return ts >= threshold


def update_history(
    history: Dict[str, Dict[str, str]],
    *,
    target_keys: List[str],
    post_id: int,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    for key in target_keys:
        history.setdefault(key, {})
        history[key][str(post_id)] = now_iso


def summarize_excerpt(excerpt: str, title: str, max_chars: int) -> str:
    excerpt = normalize_text(excerpt)
    if not excerpt:
        return title

    if len(excerpt) <= max_chars:
        return excerpt

    clipped = excerpt[:max_chars].rsplit(" ", 1)[0].strip()
    return (clipped or excerpt[:max_chars]).rstrip(" .,!?:;") + "..."


def build_social_command(
    *,
    article: ArticleCandidate,
    content_type: str,
    summary: str,
    target_keys: List[str],
    language: str,
    generate_image: bool,
    hashtags: Optional[str],
    merchant: Optional[str],
    new_price: Optional[str],
    old_price: Optional[str],
    promo_text: Optional[str],
) -> List[str]:
    cmd = [
        sys.executable,
        "-m",
        "social.cli",
        "--external-id",
        f"existing:{article.post_id}:{content_type}:{language}",
        "--content-type",
        content_type,
        "--title",
        article.title,
        "--summary",
        summary,
        "--link",
        article.link,
        "--language",
        language,
        "--targets",
        ",".join(target_keys),
        "--wp-post-id",
        str(article.post_id),
    ]

    if generate_image:
        cmd.append("--generate-image")

    if article.image_url:
        cmd.extend(["--image-url", article.image_url])

    if hashtags:
        cmd.extend(["--hashtags", hashtags])

    if merchant:
        cmd.extend(["--merchant", merchant])

    if new_price:
        cmd.extend(["--new-price", new_price])

    if old_price:
        cmd.extend(["--old-price", old_price])

    if promo_text:
        cmd.extend(["--promo-text", promo_text])

    return cmd


def run_social_publish(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def csv_to_set(value: str) -> set[str]:
    return {x.strip().lower() for x in value.split(",") if x.strip()}


def csv_to_int_set(value: str) -> set[int]:
    out = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.add(int(item))
        except ValueError:
            pass
    return out


def get_target_reshare_after_days(target_key: str, cli_value: Optional[int]) -> int:
    """
    Precedence:
    1. CLI --cooldown-days (if provided)
    2. SOCIAL__<TARGET>__RESHARE_AFTER_DAYS
    3. SOCIAL_RESHARE_AFTER_DAYS
    4. default 45
    """
    if cli_value is not None:
        return cli_value

    env_key = target_key.upper()
    target_specific = os.getenv(f"SOCIAL__{env_key}__RESHARE_AFTER_DAYS", "").strip()
    if target_specific:
        try:
            return int(target_specific)
        except ValueError:
            pass

    global_value = os.getenv("SOCIAL_RESHARE_AFTER_DAYS", "").strip()
    if global_value:
        try:
            return int(global_value)
        except ValueError:
            pass

    return 45


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pick and share one existing WordPress article randomly to social targets."
    )

    parser.add_argument("--targets", required=True, help="Comma-separated target keys")
    parser.add_argument(
        "--content-type",
        default="article",
        choices=["article", "deal", "guide", "news"],
        help="Social content type passed through to social.cli",
    )
    parser.add_argument(
        "--language",
        default="de",
        help="Language passed to social.cli (default: de)",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=50,
        help="How many WP posts to request per page",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=4,
        help="How many pages of WP posts to fetch at most",
    )
    parser.add_argument(
        "--min-age-days",
        type=int,
        default=7,
        help="Only consider posts at least this many days old",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=3650,
        help="Only consider posts at most this many days old",
    )
    parser.add_argument(
        "--cooldown-days",
        type=int,
        default=None,
        help="Reshare cooldown in days. If omitted, uses env fallback.",
    )
    parser.add_argument(
        "--summary-max-chars",
        type=int,
        default=220,
        help="Max chars for generated summary from excerpt",
    )
    parser.add_argument(
        "--include-categories",
        default="",
        help="Comma-separated categories to include",
    )
    parser.add_argument(
        "--exclude-categories",
        default="",
        help="Comma-separated categories to exclude",
    )
    parser.add_argument(
        "--exclude-ids",
        default="",
        help="Comma-separated WP post IDs to exclude",
    )
    parser.add_argument(
        "--exclude-slugs",
        default="",
        help="Comma-separated post slugs to exclude",
    )
    parser.add_argument(
        "--require-image",
        action="store_true",
        help="Only choose posts that already have a featured image",
    )
    parser.add_argument(
        "--generate-image",
        action="store_true",
        help="Ask social.cli to generate a branded image",
    )
    parser.add_argument(
        "--hashtags",
        default="",
        help="Optional hashtags override",
    )
    parser.add_argument(
        "--merchant",
        default="",
        help="Optional merchant override, mainly useful for deal resharing",
    )
    parser.add_argument("--new-price", default="")
    parser.add_argument("--old-price", default="")
    parser.add_argument("--promo-text", default="")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print chosen article and command, but do not publish",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Optional random seed for reproducible picking",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    api_base = get_wp_api_base()
    target_keys = [x.strip() for x in args.targets.split(",") if x.strip()]
    if not target_keys:
        raise ShareExistingArticlesError("No targets specified")

    include_categories = csv_to_set(args.include_categories)
    exclude_categories = csv_to_set(args.exclude_categories)
    exclude_ids = csv_to_int_set(args.exclude_ids)
    exclude_slugs = csv_to_set(args.exclude_slugs)

    raw_posts = fetch_posts(
        api_base=api_base,
        per_page=args.per_page,
        max_pages=args.max_pages,
    )
    candidates = [build_candidate(p) for p in raw_posts]

    history_path = get_social_history_path()
    history = load_history(history_path)

    filtered = filter_candidates(
        candidates,
        min_age_days=args.min_age_days,
        max_age_days=args.max_age_days,
        exclude_ids=exclude_ids,
        include_categories=include_categories or None,
        exclude_categories=exclude_categories,
        require_image=args.require_image,
        exclude_slugs=exclude_slugs,
    )

    eligible: List[ArticleCandidate] = []
    for c in filtered:
        recent_for_any_target = False

        for target_key in target_keys:
            cooldown_days = get_target_reshare_after_days(target_key, args.cooldown_days)
            if was_shared_recently(
                history,
                target_key=target_key,
                post_id=c.post_id,
                cooldown_days=cooldown_days,
            ):
                recent_for_any_target = True
                break

        if not recent_for_any_target:
            eligible.append(c)

    if not eligible:
        payload = {
            "status": "no_candidate",
            "fetched_posts": len(raw_posts),
            "filtered_candidates": len(filtered),
            "eligible_candidates": 0,
            "reason": "No eligible existing articles found after filters/cooldown",
            "targets": target_keys,
            "cooldowns": {
                key: get_target_reshare_after_days(key, args.cooldown_days)
                for key in target_keys
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    chosen = random.choice(eligible)
    summary = summarize_excerpt(chosen.excerpt, chosen.title, args.summary_max_chars)

    cmd = build_social_command(
        article=chosen,
        content_type=args.content_type,
        summary=summary,
        target_keys=target_keys,
        language=args.language,
        generate_image=args.generate_image,
        hashtags=args.hashtags or None,
        merchant=args.merchant or None,
        new_price=args.new_price or None,
        old_price=args.old_price or None,
        promo_text=args.promo_text or None,
    )

    preview = {
        "status": "selected",
        "post_id": chosen.post_id,
        "title": chosen.title,
        "link": chosen.link,
        "slug": chosen.slug,
        "image_url": chosen.image_url,
        "categories": chosen.categories,
        "targets": target_keys,
        "summary": summary,
        "cooldowns": {
            key: get_target_reshare_after_days(key, args.cooldown_days)
            for key in target_keys
        },
        "command": cmd,
    }

    if args.dry_run:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    result = run_social_publish(cmd)

    stdout_text = (result.stdout or "").strip()
    stderr_text = (result.stderr or "").strip()

    output = {
        **preview,
        "returncode": result.returncode,
        "social_stdout": stdout_text,
        "social_stderr": stderr_text,
    }

    if result.returncode == 0:
        update_history(history, target_keys=target_keys, post_id=chosen.post_id)
        save_history(history_path, history)
        output["status"] = "posted"
    else:
        output["status"] = "failed"

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())