from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

from social.image_builder import DEFAULT_OUTPUT_DIR, generate_branded_image
from social.models import SocialPost, SocialTarget
from social.pexels_client import fetch_pexels_background
from social.platforms.base import PlatformError
from social.platforms.facebook import FacebookPublisher
from social.platforms.instagram import InstagramPublisher
from social.store import SocialStore


REPO_ROOT = Path(__file__).resolve().parents[1]


def get_platform_publisher(target: SocialTarget):
    if target.platform == "facebook":
        return FacebookPublisher(target)
    if target.platform == "instagram":
        return InstagramPublisher(target)
    raise PlatformError(f"Unsupported platform '{target.platform}' for target '{target.key}'")


def _build_generated_image_public_url(output_path: str | os.PathLike[str]) -> str | None:
    public_base = os.getenv("SOCIAL_GENERATED_IMAGE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_base:
        return None

    output_path_obj = Path(output_path)
    file_name = output_path_obj.name
    parent_name = output_path_obj.parent.name

    if parent_name == "generated_images":
        return f"{public_base}/generated_images/{file_name}"

    return f"{public_base}/{file_name}"


def _build_generated_video_public_url(output_path: str | os.PathLike[str]) -> str | None:
    public_base = os.getenv("SOCIAL_GENERATED_VIDEO_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_base:
        return None

    output_path_obj = Path(output_path)
    file_name = output_path_obj.name
    parent_name = output_path_obj.parent.name

    if parent_name == "generated_videos":
        return f"{public_base}/generated_videos/{file_name}"

    return f"{public_base}/{file_name}"


def _ensure_background_image(post: SocialPost, target: SocialTarget) -> None:
    if getattr(post, "background_image_path", None):
        return

    try:
        bg = fetch_pexels_background(
            external_id=post.external_id,
            title=post.title,
            summary=post.summary or post.promo_text or "",
            category_label=getattr(post, "category_label", "") or "",
            content_type=post.content_type,
            output_dir=DEFAULT_OUTPUT_DIR,
            filename_prefix=target.key,
        )
        if bg:
            post.background_image_path = bg.get("local_path")
            post.background_image_photographer = bg.get("photographer")
            post.background_image_source_url = bg.get("photo_url")
    except Exception as exc:
        print(f"WARNING: Pexels background fetch failed: {exc}")


def _prepare_generated_image(post: SocialPost, target: SocialTarget) -> None:
    if not post.generate_image:
        return

    brand_text = os.getenv("SOCIAL_BRAND_TEXT", "GermanySupport")

    _ensure_background_image(post, target)

    existing_path = (getattr(post, "generated_image_path", None) or "").strip()
    if existing_path and Path(existing_path).exists():
        if not getattr(post, "generated_image_public_url", None):
            post.generated_image_public_url = _build_generated_image_public_url(existing_path)
    else:
        output_path = generate_branded_image(
            post=post,
            brand_text=brand_text,
            filename_prefix=target.key,
            cta_text="Check the link in the comments or visit the website!",
        )
        post.generated_image_path = output_path
        post.generated_image_public_url = _build_generated_image_public_url(output_path)

    if getattr(post, "generated_image_public_url", None):
        post.image_url = post.generated_image_public_url


def _normalize_publish_result(publish_result):
    if isinstance(publish_result, str):
        return SimpleNamespace(remote_post_id=publish_result, first_comment_id=None)

    if isinstance(publish_result, dict):
        return SimpleNamespace(
            remote_post_id=publish_result.get("remote_post_id")
            or publish_result.get("id")
            or "",
            first_comment_id=publish_result.get("first_comment_id")
            or publish_result.get("remote_comment_id"),
        )

    remote_post_id = getattr(publish_result, "remote_post_id", None)
    reel_id = getattr(publish_result, "reel_id", None)

    first_comment_id = (
        getattr(publish_result, "first_comment_id", None)
        or getattr(publish_result, "remote_comment_id", None)
    )

    if remote_post_id or reel_id:
        return SimpleNamespace(
            remote_post_id=remote_post_id or reel_id,
            reel_id=reel_id,
            first_comment_id=first_comment_id,
        )

    raise PlatformError(f"Unsupported publish result type: {type(publish_result).__name__}")


# ---------------- VIDEO URL LOGIC ----------------
def _get_video_url(post: SocialPost) -> str | None:
    # 1. Use an already-resolved public URL if upstream set it directly.
    #    This is the common path: share_existing_articles.py constructs the
    #    public URL and passes it via --generated-video-public-url, which
    #    cli.py stores on post.generated_video_public_url.  Checking this
    #    first avoids a dependency on SOCIAL_GENERATED_VIDEO_PUBLIC_BASE_URL
    #    being configured, which was causing _get_video_url to return None
    #    for gs_ig_main and silently skip Reel publishing for Instagram.
    direct_url = (
        getattr(post, "generated_video_public_url", None)
        or getattr(post, "video_url", None)
    )
    if direct_url:
        return direct_url

    # 2. Fallback: derive public URL from a local path using the env-var base.
    #    Only reached if no pre-built URL was provided.
    video_path = getattr(post, "generated_video_path", None) or getattr(post, "video_path", None)
    if video_path:
        return _build_generated_video_public_url(video_path)

    return None


def _publish_story_if_enabled(post: SocialPost, target: SocialTarget, publisher):
    if not getattr(target, "publish_story", False):
        return None

    image_path = (
        getattr(post, "story_generated_image_path", None)
        or getattr(post, "generated_image_path", None)
        or ""
    ).strip() or None

    image_url = (
        getattr(post, "story_generated_image_public_url", None)
        or getattr(post, "generated_image_public_url", None)
        or getattr(post, "image_url", None)
        or ""
    ).strip() or None

    if target.platform == "instagram":
        return publisher.publish_story(post, image_path=image_path, image_url=image_url)

    video_path = (
        getattr(post, "generated_video_path", None)
        or getattr(post, "video_path", None)
        or ""
    ).strip() or None

    return publisher.publish_story(
        post,
        image_path=image_path,
        image_url=image_url,
        video_path=video_path,
    )


def publish_to_targets(
    post: SocialPost,
    targets: Dict[str, SocialTarget],
    target_keys: List[str],
    store: SocialStore,
    dry_run: bool = False,
) -> dict:
    result = {"posted": [], "skipped": [], "failed": []}

    for key in target_keys:
        if key not in targets:
            result["failed"].append({"target": key, "error": f"Unknown target '{key}'"})
            continue

        target = targets[key]

        if not target.enabled:
            result["skipped"].append({"target": key, "platform": target.platform, "reason": "disabled"})
            continue

        if post.content_type.lower() not in target.allowed_content_types:
            result["skipped"].append(
                {
                    "target": key,
                    "platform": target.platform,
                    "reason": f"content_type_not_allowed:{post.content_type.lower()}",
                }
            )
            continue

        if store.already_posted(target.key, post.external_id):
            result["skipped"].append({"target": key, "platform": target.platform, "reason": "already_posted"})
            continue

        try:
            if post.generate_image:
                _prepare_generated_image(post, target)

            has_image = bool(
                getattr(post, "generated_image_public_url", None)
                or getattr(post, "image_url", None)
                or getattr(post, "generated_image_path", None)
            )

            has_video = bool(
                getattr(post, "generated_video_path", None)
                or getattr(post, "video_path", None)
                or getattr(post, "generated_video_url", None)
                or getattr(post, "video_url", None)
            )

            if target.require_image and not has_image and not has_video:
                raise PlatformError(f"Target '{target.key}' requires an image or video")

            if dry_run:
                result["skipped"].append({"target": key, "platform": target.platform, "reason": "dry_run"})
                continue

            publisher = get_platform_publisher(target)

            raw_publish_result = publisher.publish(post)
            publish_result = _normalize_publish_result(raw_publish_result)

            video_url = _get_video_url(post)
            reel_id = None

            # Reel upload is Instagram-only. Facebook uses a separate video
            # upload flow (publish_story / 3-step resumable upload) and does
            # not implement publish_reel — calling it raised AttributeError.
            if video_url and target.platform == "instagram":
                try:
                    print(f"INFO: Uploading Reel for {target.platform}: {video_url}")

                    reel_result = publisher.publish_reel(post, video_url=video_url)
                    reel_result = _normalize_publish_result(reel_result)

                    reel_id = (
                        getattr(reel_result, "reel_id", None)
                        or getattr(reel_result, "remote_post_id", None)
                        or getattr(reel_result, "id", None)
                    )

                    print(f"INFO: Reel created: {reel_id}")

                except Exception as e:
                    print(f"WARNING: Reel publish failed on {target.platform}: {e}")

            story_id = None
            story_error = None

            if getattr(target, "publish_story", False):
                try:
                    story_id = _publish_story_if_enabled(post, target, publisher)
                except Exception as exc:
                    story_error = str(exc)
                    print(f"WARNING: Story publish failed: {exc}")

            store.mark_posted(
                target_key=target.key,
                platform=target.platform,
                external_id=post.external_id,
                content_type=post.content_type,
                wp_post_id=post.wp_post_id,
                remote_post_id=publish_result.remote_post_id,
                first_comment_id=publish_result.first_comment_id,
            )

            result["posted"].append(
                {
                    "target": key,
                    "platform": target.platform,
                    "id": publish_result.remote_post_id,
                    "reel_id": reel_id,
                    "first_comment_id": publish_result.first_comment_id,
                    "story_id": story_id,
                    "story_error": story_error,
                    "generated_image_path": getattr(post, "generated_image_path", None),
                    "generated_image_public_url": getattr(post, "generated_image_public_url", None),
                    "story_generated_image_path": getattr(post, "story_generated_image_path", None),
                    "story_generated_image_public_url": getattr(post, "story_generated_image_public_url", None),
                    "image_url": getattr(post, "image_url", None),
                }
            )

        except Exception as exc:
            store.mark_failed(
                target_key=target.key,
                platform=target.platform,
                external_id=post.external_id,
                content_type=post.content_type,
                wp_post_id=post.wp_post_id,
                error_message=str(exc),
            )

            result["failed"].append({"target": key, "platform": target.platform, "error": str(exc)})

    return result