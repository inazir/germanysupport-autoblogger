"""
social/daily_news/news_comments.py

Phase 2: Post additional news items as comments under the main published post.

Reuses without modification:
  - social.platforms.facebook.FacebookPublisher._post_first_comment()
  - social.platforms.base.PlatformError
  - social.config.get_social_targets()

Strategy:
  - After main post succeeds, get the post_id from publish result
  - For each additional news item, build a short comment text
  - Call the platform's comment endpoint
  - Each failure is logged but does NOT affect the main post result
  - Instagram comment API is not supported in current project — skipped gracefully
"""
from __future__ import annotations

import time
from typing import List, Optional

from social.daily_news.news_fetcher import NewsItem
from social.models import SocialTarget
from social.platforms.base import PlatformError


# ---------------------------------------------------------------------------
# Comment text builder
# ---------------------------------------------------------------------------

_COMMENT_EMOJIS = ["4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]


def _build_comment_text(item: NewsItem, index: int) -> str:
    """
    Format a single news item as a comment.
    Keeps it concise and readable.
    """
    emoji = _COMMENT_EMOJIS[index] if index < len(_COMMENT_EMOJIS) else "▶️"
    text = f"{emoji} {item.title}"
    if item.summary:
        # Short excerpt — first sentence or first 120 chars
        excerpt = item.summary.split(".")[0].strip()
        if len(excerpt) > 10:
            if len(excerpt) > 120:
                excerpt = excerpt[:117].rstrip() + "..."
            text += f"\n{excerpt}"
    text += f"\n🔗 {item.url}"
    return text


# ---------------------------------------------------------------------------
# Platform-specific comment posting
# ---------------------------------------------------------------------------

def _post_facebook_comments(
    post_id: str,
    items: List[NewsItem],
    target: SocialTarget,
    delay_seconds: float = 2.0,
) -> List[dict]:
    """
    Post news items as comments on a Facebook post.
    Returns list of result dicts.
    """
    from social.platforms.facebook import FacebookPublisher

    publisher = FacebookPublisher(target)
    results = []

    for i, item in enumerate(items):
        comment_text = _build_comment_text(item, i)
        try:
            # Small delay between comments to avoid rate limiting
            if i > 0:
                time.sleep(delay_seconds)

            comment_id = publisher._post_first_comment(post_id, comment_text)
            print(f"  [news_comments] Comment {i+1} posted: {comment_id}")
            results.append({"index": i + 1, "comment_id": comment_id, "error": None})
        except PlatformError as exc:
            print(f"  [news_comments] Comment {i+1} failed: {exc}")
            results.append({"index": i + 1, "comment_id": None, "error": str(exc)})
        except Exception as exc:
            print(f"  [news_comments] Comment {i+1} unexpected error: {exc}")
            results.append({"index": i + 1, "comment_id": None, "error": str(exc)})

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def post_news_comments(
    post_id: str,
    platform: str,
    items: List[NewsItem],
    target: SocialTarget,
    top_n: int = 4,
) -> List[dict]:
    """
    Post additional news items as comments under the main post.

    Parameters
    ----------
    post_id  : ID of the main published post (from publish result)
    platform : "facebook" or "instagram"
    items    : all fetched news items (first top_n after main post items are used)
    target   : the SocialTarget that was used to publish the main post
    top_n    : how many comment items to post

    Returns
    -------
    List of result dicts with keys: index, comment_id, error
    Empty list if platform doesn't support comments or no items available.
    """
    if not post_id or not items:
        return []

    comment_items = items[:top_n]

    if platform == "facebook":
        print(f"  [news_comments] Posting {len(comment_items)} comments on Facebook post {post_id}")
        return _post_facebook_comments(post_id, comment_items, target)

    elif platform == "instagram":
        # Instagram comment API (reply to own post) requires additional
        # permissions not currently configured in this project.
        # Skip gracefully rather than error.
        print(f"  [news_comments] Instagram comments not supported — skipping gracefully")
        return []

    else:
        print(f"  [news_comments] Comments not implemented for platform '{platform}' — skipping")
        return []
