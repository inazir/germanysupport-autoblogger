from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from social.env_loader import load_env_file
from social.models import SocialTarget


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOTENV = REPO_ROOT / ".env"
load_env_file(DEFAULT_DOTENV)


def _to_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(str(value).strip())


def _to_list(value: str | None, default: List[str] | None = None) -> List[str]:
    if value is None or str(value).strip() == "":
        return list(default or [])
    return [x.strip().lower() for x in str(value).split(",") if x.strip()]


def get_social_targets() -> Dict[str, SocialTarget]:
    raw = os.getenv("SOCIAL_TARGETS", "").strip()
    if not raw:
        return {}

    targets: Dict[str, SocialTarget] = {}

    for key in [x.strip() for x in raw.split(",") if x.strip()]:
        env_key = key.upper()

        platform = os.getenv(f"SOCIAL__{env_key}__PLATFORM", "").strip().lower()
        enabled = _to_bool(os.getenv(f"SOCIAL__{env_key}__ENABLED", "false"))
        name = os.getenv(f"SOCIAL__{env_key}__NAME", key)
        access_token = os.getenv(f"SOCIAL__{env_key}__ACCESS_TOKEN", "").strip()
        page_id = os.getenv(f"SOCIAL__{env_key}__PAGE_ID", "").strip() or None
        ig_id = os.getenv(f"SOCIAL__{env_key}__IG_BUSINESS_ACCOUNT_ID", "").strip() or None
        api_version = os.getenv(f"SOCIAL__{env_key}__API_VERSION", "v25.0").strip()

        allowed = _to_list(
            os.getenv(f"SOCIAL__{env_key}__ALLOWED_CONTENT_TYPES"),
            ["article", "deal"],
        )

        post_link_in_first_comment = _to_bool(
            os.getenv(f"SOCIAL__{env_key}__POST_LINK_IN_FIRST_COMMENT", "false")
        )
        comment_fail_is_fatal = _to_bool(
            os.getenv(f"SOCIAL__{env_key}__COMMENT_FAIL_IS_FATAL", "false")
        )
        require_image = _to_bool(
            os.getenv(f"SOCIAL__{env_key}__REQUIRE_IMAGE", "false")
        )
        publish_story = _to_bool(
            os.getenv(f"SOCIAL__{env_key}__PUBLISH_STORY", "false")
        )

        template = os.getenv(f"SOCIAL__{env_key}__TEMPLATE", "default").strip()
        image_style = os.getenv(
            f"SOCIAL__{env_key}__IMAGE_STYLE",
            "main_brand",
        ).strip()

        utm_source = os.getenv(f"SOCIAL__{env_key}__UTM_SOURCE", "").strip() or None
        utm_campaign = os.getenv(f"SOCIAL__{env_key}__UTM_CAMPAIGN", "").strip() or None
        max_caption_chars = _to_int(
            os.getenv(f"SOCIAL__{env_key}__MAX_CAPTION_CHARS")
        )
        skip_if_image_generation_fails = _to_bool(
            os.getenv(
                f"SOCIAL__{env_key}__SKIP_IF_IMAGE_GENERATION_FAILS",
                "false",
            )
        )

        if not platform:
            raise RuntimeError(f"Missing SOCIAL__{env_key}__PLATFORM")

        if not access_token:
            raise RuntimeError(f"Missing SOCIAL__{env_key}__ACCESS_TOKEN")

        print(
            "DEBUG TARGET",
            {
                "key": key,
                "env_key": env_key,
                "platform": platform,
                "enabled": enabled,
                "post_link_in_first_comment": post_link_in_first_comment,
                "comment_fail_is_fatal": comment_fail_is_fatal,
                "require_image": require_image,
                "publish_story": publish_story,
                "image_style": image_style,
            },
        )

        targets[key] = SocialTarget(
            key=key,
            platform=platform,
            enabled=enabled,
            name=name,
            access_token=access_token,
            api_version=api_version,
            page_id=page_id,
            ig_business_account_id=ig_id,
            allowed_content_types=allowed,
            post_link_in_first_comment=post_link_in_first_comment,
            comment_fail_is_fatal=comment_fail_is_fatal,
            require_image=require_image,
            template=template,
            image_style=image_style,
            utm_source=utm_source,
            utm_campaign=utm_campaign,
            max_caption_chars=max_caption_chars,
            skip_if_image_generation_fails=skip_if_image_generation_fails,
            publish_story=publish_story,
        )

    return targets


def resolve_target_keys(requested: str | None, available_keys: List[str]) -> List[str]:
    if not requested or requested.strip().lower() == "all":
        return available_keys
    return [x.strip() for x in requested.split(",") if x.strip()]


def get_default_hashtags(language: str, content_type: str) -> str:
    language = (language or "de").lower()
    content_type = (content_type or "article").lower()

    key = f"SOCIAL_DEFAULT_HASHTAGS_{language.upper()}_{content_type.upper()}"
    value = os.getenv(key, "").strip()
    if value:
        return value

    if language in {"bn", "bengali", "bangla"}:
        return os.getenv(
            "SOCIAL_DEFAULT_HASHTAGS_BN",
            "#germanysupport #জার্মানি #প্রবাসী #জার্মানিজীবন",
        )

    if language == "en":
        return os.getenv(
            "SOCIAL_DEFAULT_HASHTAGS_EN",
            "#germanysupport #germany #guides #deals",
        )

    return os.getenv(
        "SOCIAL_DEFAULT_HASHTAGS_DE",
        "#germanysupport #deutschland #tipps #angebote",
    )


def append_utm(
    url: str,
    source: str | None = None,
    campaign: str | None = None,
    medium: str = "social",
) -> str:
    if not source and not campaign:
        return url

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if source:
        query.setdefault("utm_source", source)
    if medium:
        query.setdefault("utm_medium", medium)
    if campaign:
        query.setdefault("utm_campaign", campaign)

    return urlunparse(parsed._replace(query=urlencode(query)))