"""
social/daily_news/share_news.py

Germany Daily News Auto Poster — Phase 1 + 2.

Phase 1: Fetch RSS → filter → AI caption → publish text post
Phase 2: + branded image generation (reuses image_builder)
         + follow-up comments with additional news items (reuses facebook publisher)

Reuses existing architecture — does NOT modify any existing file:
  - social.config.get_social_targets()
  - social.publisher.publish_to_targets()
  - social.store.SocialStore
  - social.models.SocialPost
  - social.image_builder.generate_branded_image()
  - social.pexels_client.fetch_pexels_background()
  - social.platforms.facebook.FacebookPublisher._post_first_comment()

Run modes:
  python -m social.daily_news.share_news --test          # dry run, no posting
  python -m social.daily_news.share_news --post          # live post
  python -m social.daily_news.share_news --post --no-image
  python -m social.daily_news.share_news --post --no-comments
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from social.env_loader import load_env_file
load_env_file(REPO_ROOT / ".env")

from social.config import get_social_targets, resolve_target_keys
from social.models import SocialPost
from social.daily_news.news_ai import generate_caption
from social.daily_news.news_comments import post_news_comments
from social.daily_news.news_fetcher import NewsItem, fetch_news
from social.daily_news.news_image import generate_news_image
from social.publisher import publish_to_targets
from social.store import SocialStore


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    log_dir = REPO_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"news_{datetime.now().strftime('%Y%m%d')}.log"

    logger = logging.getLogger("share_news")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger


log = _setup_logging()


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)).strip())
    except (ValueError, AttributeError):
        return default


def _get_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


def _get_news_targets() -> str:
    return os.getenv(
        "NEWS_TARGETS",
        os.getenv("SOCIAL_EXISTING_TARGETS", "gs_fb_main"),
    ).strip()


def _build_hashtags(language: str = "bn") -> str:
    default_hashtags = (
        "#Germany #Expats #GermanyNews #GermanySupport"
        if language not in {"bn", "bengali", "bangla"}
        else "#জার্মানি #প্রবাসী #জার্মানিখবর #GermanySupport"
    )
    return os.getenv(
        "NEWS_HASHTAGS",
        default_hashtags,
    ).strip()


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _make_external_id(items: list[NewsItem]) -> str:
    today = datetime.now().strftime("%Y%m%d")
    headline_key = items[0].dedup_key if items else "empty"
    return f"news:{today}:{headline_key[:16]}"


def _build_social_post(
    caption: str,
    items: list[NewsItem],
    hashtags: str,
    image_path: str | None,
    image_public_url: str | None,
) -> SocialPost:
    top_url = "https://germanysupport.de"
    today = datetime.now().strftime("%Y-%m-%d")

    post = SocialPost(
        external_id=_make_external_id(items),
        content_type="article",
        title="",
        link=top_url,
        summary=caption,
        hashtags=hashtags,
        language=os.getenv("NEWS_LANGUAGE", "bn").strip().lower(),
        # Image is already generated — set directly, don't re-trigger generation
        generate_image=False,
        generate_video=False,
    )

    # Attach pre-generated image so publisher.py uses it without re-running
    # Pexels fetch or generate_branded_image
    if image_path:
        post.generated_image_path = image_path          # type: ignore[attr-defined]
    if image_public_url:
        post.generated_image_public_url = image_public_url  # type: ignore[attr-defined]
        post.image_url = image_public_url

    return post


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(dry_run: bool = False, target_names: str | None = None) -> dict:
    top_main     = _get_int("NEWS_TOP_MAIN", 3)
    top_comments = _get_int("NEWS_TOP_COMMENTS", 4)
    top_fetch    = _get_int("NEWS_MAX_FETCH", 40)
    enable_image    = _get_bool("NEWS_ENABLE_IMAGE", True)
    enable_comments = _get_bool("NEWS_ENABLE_COMMENTS", True)
    target_str = target_names or _get_news_targets()

    log.info("=" * 60)
    log.info("Germany Daily News Poster — Phase 1+2")
    log.info(f"Mode          : {'DRY RUN' if dry_run else 'LIVE POST'}")
    log.info(f"Targets       : {target_str}")
    log.info(f"Image enabled : {enable_image}")
    log.info(f"Comments      : {enable_comments}")
    log.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Fetch + filter + dedup news
    # ------------------------------------------------------------------
    log.info("Step 1: Fetching RSS feeds...")
    items = fetch_news(max_fetch=top_fetch)
    log.info(f"  {len(items)} Germany-relevant items after filter+dedup")

    if not items:
        log.warning("No Germany-relevant news found. Aborting.")
        return {"status": "no_news", "posted": [], "failed": []}

    log.info(f"  Top {min(top_main, len(items))} items for main post:")
    for i, item in enumerate(items[:top_main]):
        log.info(f"    {i+1}. [{item.source}] {item.title} (score={item.relevance_score:.2f})")

    if enable_comments:
        comment_items = items[top_main: top_main + top_comments]
        if comment_items:
            log.info(f"  {len(comment_items)} items reserved for comments")

    # ------------------------------------------------------------------
    # Step 2: Generate AI caption
    # ------------------------------------------------------------------
    log.info("Step 2: Generating AI caption...")
    language = os.getenv("NEWS_LANGUAGE", "bn").strip().lower()
    caption = generate_caption(items, top_n=top_main, language=language)
    log.info(f"  Caption ready ({len(caption)} chars)")

    hashtags   = _build_hashtags(language)
    external_id = _make_external_id(items)

    # ------------------------------------------------------------------
    # Step 3: Generate branded image (Phase 2)
    # ------------------------------------------------------------------
    image_path: str | None = None
    image_public_url: str | None = None

    if enable_image:
        log.info("Step 3: Generating branded news image...")
        image_path, image_public_url = generate_news_image(
            items=items,
            external_id=external_id,
            top_n=top_main,
        )
        if image_path:
            log.info(f"  Image : {image_path}")
            log.info(f"  URL   : {image_public_url or '(SOCIAL_GENERATED_IMAGE_PUBLIC_BASE_URL not set)'}")
        else:
            log.warning("  Image generation failed — falling back to text-only post")
    else:
        log.info("Step 3: Image generation skipped (NEWS_ENABLE_IMAGE=false)")

    # ------------------------------------------------------------------
    # Dry run — print preview and exit
    # ------------------------------------------------------------------
    if dry_run:
        preview = {
            "status": "dry_run",
            "external_id": external_id,
            "caption_preview": caption[:400] + ("..." if len(caption) > 400 else ""),
            "hashtags": hashtags,
            "image_path": image_path,
            "image_public_url": image_public_url,
            "top_news": [
                {
                    "source": it.source,
                    "title": it.title,
                    "score": round(it.relevance_score, 2),
                }
                for it in items[:top_main]
            ],
            "comment_news": [
                {"source": it.source, "title": it.title}
                for it in items[top_main: top_main + top_comments]
            ] if enable_comments else [],
        }
        log.info("DRY RUN complete — no posts published.")
        print("\n" + json.dumps(preview, indent=2, ensure_ascii=False))
        return preview

    # ------------------------------------------------------------------
    # Step 4: Publish main post
    # ------------------------------------------------------------------
    log.info("Step 4: Publishing to social targets...")
    targets = get_social_targets()
    if not targets:
        log.error("No social targets configured. Check SOCIAL_TARGETS in .env")
        return {"status": "error", "error": "no_targets", "posted": [], "failed": []}

    target_keys = resolve_target_keys(target_str, list(targets.keys()))
    log.info(f"  Resolved targets: {target_keys}")

    store = SocialStore(str(REPO_ROOT / "social" / "cache" / "social.db"))

    social_post = _build_social_post(
        caption=caption,
        items=items,
        hashtags=hashtags,
        image_path=image_path,
        image_public_url=image_public_url,
    )

    result = publish_to_targets(
        post=social_post,
        targets=targets,
        target_keys=target_keys,
        store=store,
        dry_run=False,
    )

    # ------------------------------------------------------------------
    # Step 5: Post follow-up comments (Phase 2)
    # ------------------------------------------------------------------
    comment_results: dict = {}

    if enable_comments:
        comment_items = items[top_main: top_main + top_comments]

        if not comment_items:
            log.info("Step 5: No additional items available for comments")
        else:
            log.info(f"Step 5: Posting {len(comment_items)} follow-up comments...")

            for posted_entry in result.get("posted", []):
                post_id    = posted_entry.get("id", "")
                target_key = posted_entry.get("target", "")
                platform   = posted_entry.get("platform", "")

                if not post_id or not target_key:
                    continue

                target = targets.get(target_key)
                if not target:
                    continue

                log.info(f"  [{platform}] posting comments on post {post_id} ({target_key})")
                c_results = post_news_comments(
                    post_id=post_id,
                    platform=platform,
                    items=comment_items,
                    target=target,
                    top_n=top_comments,
                )
                comment_results[target_key] = c_results

                success = sum(1 for r in c_results if not r.get("error"))
                failed  = sum(1 for r in c_results if r.get("error"))
                log.info(f"    {success} succeeded, {failed} failed")
    else:
        log.info("Step 5: Comments skipped (NEWS_ENABLE_COMMENTS=false)")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    log.info("Summary:")
    for p in result.get("posted", []):
        log.info(f"  ✅ {p['target']} ({p['platform']}) id={p['id']}")
    for s in result.get("skipped", []):
        log.info(f"  ⏭️  {s['target']}: {s.get('reason', '')}")
    for f in result.get("failed", []):
        log.error(f"  ❌ {f['target']}: {f.get('error', '')}")

    result["comment_results"] = comment_results
    log.info("Done.")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Germany Daily News Auto Poster")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true", help="Dry run — fetch + generate, no posting")
    group.add_argument("--post", action="store_true", help="Live post to social targets")
    parser.add_argument("--targets",     default=None, help="Comma-separated target keys")
    parser.add_argument("--no-image",    action="store_true", help="Skip image generation")
    parser.add_argument("--no-comments", action="store_true", help="Skip comment posting")
    args = parser.parse_args()

    # CLI flags override .env
    if args.no_image:
        os.environ["NEWS_ENABLE_IMAGE"] = "false"
    if args.no_comments:
        os.environ["NEWS_ENABLE_COMMENTS"] = "false"

    result = run(dry_run=args.test, target_names=args.targets)

    sys.exit(1 if result.get("failed") else 0)


if __name__ == "__main__":
    main()
