from __future__ import annotations

from social.config import append_utm, get_default_hashtags
from social.models import SocialPost, SocialTarget


MAX_DEFAULT_SUMMARY = 1000


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _truncate(value: str, max_len: int | None) -> str:
    value = value.strip()
    if not max_len or len(value) <= max_len:
        return value
    if max_len <= 3:
        return value[:max_len]
    return value[: max_len - 3].rstrip() + "..."


def build_link_for_target(post: SocialPost, target: SocialTarget) -> str:
    return append_utm(post.link, source=target.utm_source, campaign=target.utm_campaign)


def build_article_summary(post: SocialPost, max_len: int | None = None) -> str:
    text = _clean(post.summary) or _clean(post.promo_text)
    return text


def build_deal_summary(post: SocialPost, max_len: int | None = None) -> str:
    parts = []
    if post.merchant:
        parts.append(f"🛍️ Händler: {_clean(post.merchant)}")
    if post.new_price:
        parts.append(f"💸 Jetzt: {_clean(post.new_price)}")
    if post.old_price:
        parts.append(f"🏷️ Statt: {_clean(post.old_price)}")
    if post.coupon_code:
        parts.append(f"🎟️ Code: {_clean(post.coupon_code)}")
    if post.promo_text:
        parts.append(_clean(post.promo_text))
    return "\n".join(parts).strip()


def build_facebook_message(post: SocialPost, target: SocialTarget) -> str:
    language = _clean(post.language).lower()
    title = _clean(post.title)
    parts = [] if language in {"bn", "bengali", "bangla"} or not title else [f"🔥 {title}"]
    if post.content_type == "deal":
        body = build_deal_summary(post)
    else:
        body = build_article_summary(post, target.max_caption_chars)
    if body:
        parts.append(body)

    hashtags = _clean(post.hashtags) or get_default_hashtags(post.language, post.content_type)
    if hashtags:
        parts.append(hashtags)
    message = "\n\n".join([p for p in parts if p])

    max_len = target.max_caption_chars or 5000  # safe FB baseline
    return _truncate(message, max_len)


def build_instagram_caption(post: SocialPost, target: SocialTarget) -> str:
    parts = [f"🔥 {_clean(post.title)}"]
    if post.content_type == "deal":
        body = build_deal_summary(post)
    else:
        body = build_article_summary(post, target.max_caption_chars)
    if body:
        parts.append(body)
    parts.append("🔗 Mehr Details auf der Website")
    hashtags = _clean(post.hashtags) or get_default_hashtags(post.language, post.content_type)
    if hashtags:
        parts.append(hashtags)
    message = "\n\n".join([p for p in parts if p])

    max_len = target.max_caption_chars or 2200  # IG practical limit
    return _truncate(message, max_len)
