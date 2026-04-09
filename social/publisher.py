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


def _prepare_generated_image(post: SocialPost, target: SocialTarget) -> None:
    if not post.generate_image:
        return

    if post.generated_image_path and Path(post.generated_image_path).exists():
        if getattr(post, "generated_image_public_url", None) and not getattr(post, "image_url", None):
            post.image_url = post.generated_image_public_url
        return

    # Try Pexels first as free visual background enrichment.
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

    brand_text = os.getenv("SOCIAL_BRAND_TEXT", "GermanySupport")
    public_base = os.getenv("SOCIAL_GENERATED_IMAGE_PUBLIC_BASE_URL", "").rstrip("/")

    output_path = generate_branded_image(
        post=post,
        brand_text=brand_text,
        filename_prefix=target.key,
    )
    post.generated_image_path = output_path

    if public_base:
        file_name = Path(output_path).name
        public_url = f"{public_base}/{file_name}"
        post.generated_image_public_url = public_url

        # Important: Instagram needs a public URL, and Facebook may also use it.
        if not getattr(post, "image_url", None):
            post.image_url = public_url


def _normalize_publish_result(publish_result):
    """
    Normalize platform publisher outputs so the rest of the pipeline
    can work even if a platform still returns a plain string or dict.
    """
    if isinstance(publish_result, str):
        return SimpleNamespace(
            remote_post_id=publish_result,
            first_comment_id=None,
        )

    if isinstance(publish_result, dict):
        return SimpleNamespace(
            remote_post_id=publish_result.get("remote_post_id")
            or publish_result.get("id")
            or "",
            first_comment_id=publish_result.get("first_comment_id")
            or publish_result.get("remote_comment_id"),
        )

    remote_post_id = getattr(publish_result, "remote_post_id", None)
    first_comment_id = (
        getattr(publish_result, "first_comment_id", None)
        or getattr(publish_result, "remote_comment_id", None)
    )

    if remote_post_id:
        return SimpleNamespace(
            remote_post_id=remote_post_id,
            first_comment_id=first_comment_id,
        )

    raise PlatformError(
        f"Unsupported publish result type from platform publisher: {type(publish_result).__name__}"
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
            result["skipped"].append(
                {"target": key, "platform": target.platform, "reason": "disabled"}
            )
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
            result["skipped"].append(
                {"target": key, "platform": target.platform, "reason": "already_posted"}
            )
            continue

        try:
            if post.generate_image:
                _prepare_generated_image(post, target)

            has_image = bool(
                getattr(post, "generated_image_public_url", None)
                or getattr(post, "image_url", None)
                or getattr(post, "generated_image_path", None)
            )

            if target.require_image and not has_image:
                raise PlatformError(f"Target '{target.key}' requires an image")

            if dry_run:
                result["skipped"].append(
                    {
                        "target": key,
                        "platform": target.platform,
                        "reason": "dry_run",
                        "generated_image_path": getattr(post, "generated_image_path", None),
                        "generated_image_public_url": getattr(post, "generated_image_public_url", None),
                        "image_url": getattr(post, "image_url", None),
                        "background_image_path": getattr(post, "background_image_path", None),
                        "background_image_photographer": getattr(post, "background_image_photographer", None),
                    }
                )
                continue

            publisher = get_platform_publisher(target)
            raw_publish_result = publisher.publish(post)
            publish_result = _normalize_publish_result(raw_publish_result)

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
                    "first_comment_id": publish_result.first_comment_id,
                    "generated_image_path": getattr(post, "generated_image_path", None),
                    "generated_image_public_url": getattr(post, "generated_image_public_url", None),
                    "image_url": getattr(post, "image_url", None),
                    "background_image_path": getattr(post, "background_image_path", None),
                    "background_image_photographer": getattr(post, "background_image_photographer", None),
                }
            )

        except Exception as exc:
            image_missing = not (
                getattr(post, "generated_image_path", None)
                or getattr(post, "generated_image_public_url", None)
                or getattr(post, "image_url", None)
            )

            if target.skip_if_image_generation_fails and post.generate_image and image_missing:
                result["skipped"].append(
                    {
                        "target": key,
                        "platform": target.platform,
                        "reason": f"image_generation_failed:{exc}",
                    }
                )
                continue

            store.mark_failed(
                target_key=target.key,
                platform=target.platform,
                external_id=post.external_id,
                content_type=post.content_type,
                wp_post_id=post.wp_post_id,
                error_message=str(exc),
            )
            result["failed"].append(
                {"target": key, "platform": target.platform, "error": str(exc)}
            )

    return result