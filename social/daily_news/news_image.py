"""
social/daily_news/news_image.py

Generate a branded news image for the daily news post.

Correct image pipeline
----------------------
1. Try to get a background photo:
   a. AI image (Pollinations via ImageGenerationService) — downloaded locally
   b. Pexels photo — downloaded locally
   c. No background — PIL uses built-in dark gradient fallback

2. Pass background to generate_branded_image() which draws on top:
   - GermanySupport.de logo + brand text (header bar)
   - Glass panel with top 3 news headlines (1️⃣ 2️⃣ 3️⃣)
   - CTA button at the bottom

3. Return the branded PNG path + public URL.

The AI/Pexels image is ALWAYS just the background layer.
The PIL branded image is ALWAYS the final output posted to Facebook.

Previous bug: when AI image succeeded, it was returned directly as the
final image — skipping the PIL branding step entirely. The post showed
a raw unbranded photo with no logo, no headlines, no CTA.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from social.image_generation.service import ImageGenerationService
from social.image_generation.prompts import build_news_image_prompt
from social.image_generation.image_builder import (
    DEFAULT_OUTPUT_DIR,
    generate_branded_image_v2,
)
from social.models import SocialPost
from social.daily_news.news_fetcher import NewsItem

from social.daily_news.news_ai import (
    _try_claude,
    _try_deepseek,
    _try_openai,
)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_ai_image_prompt(items: List[NewsItem]) -> str:
    if not items:
        return build_news_image_prompt("daily news Germany")
    topic = items[0].title
    if len(topic) > 80:
        topic = topic[:77] + "..."
    return build_news_image_prompt(topic)


# ---------------------------------------------------------------------------
# Background fetchers
# Returns a local file path or None — never raises
# ---------------------------------------------------------------------------

def _fetch_ai_background(items: List[NewsItem], external_id: str) -> Optional[str]:
    """
    Download an AI-generated image and return the local file path.
    Used as background for the PIL branded image — NOT as the final image.
    """
    try:
        prompt = _build_ai_image_prompt(items)
        print(f"  [news_image] Attempting AI background (prompt: {prompt[:80]}...)")

        ai_url = ImageGenerationService.generate(prompt)
        if not ai_url:
            return None

        print(f"  [news_image] AI background URL: {ai_url[:80]}...")
        local_path = ImageGenerationService.download_to_cache(
            ai_url,
            filename_prefix="news_bg_ai",
        )
        if local_path:
            print(f"  [news_image] AI background cached: {local_path}")
        return local_path

    except Exception as exc:
        print(f"  [news_image] AI background fetch failed: {exc}")
        return None


def _fetch_pexels_background(external_id: str) -> Optional[str]:
    """
    Fetch a Pexels photo and return the local file path.
    Used as background for the PIL branded image — NOT as the final image.
    """
    try:
        from social.pexels_client import fetch_pexels_background
        bg = fetch_pexels_background(
            external_id=external_id,
            title="Germany news Berlin city",
            summary="Germany daily news update expats",
            category_label="news",
            content_type="article",
            output_dir=DEFAULT_OUTPUT_DIR,
            filename_prefix="news_bg",
        )
        if bg:
            return bg.get("local_path")
    except Exception as exc:
        print(f"  [news_image] Pexels background unavailable: {exc}")
    return None


# ---------------------------------------------------------------------------
# Image summary for the PIL overlay
# ---------------------------------------------------------------------------

def _build_image_title(items: List[NewsItem], language: str = "en") -> str:
    """
    Generate a short image-friendly title from the first news item.

    Uses the same AI provider routing strategy as caption generation:
    primary -> fallback -> remaining providers.

    Returns a safe truncated fallback if all providers fail.
    """

    if not items:
        return "Germany Daily News"

    headline = (items[0].title or "").strip()

    if not headline:
        return "Germany Daily News"

    primary = os.getenv("NEWS_AI_PROVIDER", "claude").strip().lower()
    fallback = os.getenv("NEWS_AI_FALLBACK_PROVIDER", "deepseek").strip().lower()

    language_instruction = (
        "Write the title entirely in Bengali (Bangla script)."
        if language.lower().strip() in {"bn", "bengali", "bangla"}
        else "Write the title in English."
    )
    prompt = f"""
Rewrite this news headline into a SHORT title for a square social media image.

Requirements:
- Preserve the core meaning
- Make it visually clean
- Maximum 8-10 words
- Maximum 60 characters
- Professional tone
- No quotes
- No emojis
- No hashtags
- No clickbait
- {language_instruction}
- Output ONLY the final rewritten title

Headline:
{headline}
""".strip()

    provider_map = {
        "claude": _try_claude,
        "deepseek": _try_deepseek,
        "openai": _try_openai,
    }

    # Build provider order
    order = [primary, fallback]

    for p in ["claude", "deepseek", "openai"]:
        if p not in order:
            order.append(p)

    for provider in order:
        fn = provider_map.get(provider)

        if fn is None:
            continue

        try:
            print(f"  [news_ai] Trying image title provider: {provider}")

            result = fn(prompt)

            if not result:
                continue

            # cleanup
            result = result.strip()

            # remove quotes
            result = result.replace('"', "").replace("'", "")

            # first line only
            result = result.split("\n")[0].strip()

            # remove bullets / numbering
            result = result.lstrip("-•123456789. ")

            # hard character safety limit
            if len(result) > 60:
                result = result[:57].rstrip() + "..."

            if result:
                print(
                    f"  [news_ai] Image title generated via "
                    f"{provider} ({len(result)} chars)"
                )
                return result

        except Exception as exc:
            print(
                f"  [news_ai] Image title generation failed via "
                f"{provider}: {exc}"
            )

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    print("  [news_ai] All image title providers failed — using fallback")

    fallback_title = headline

    if len(fallback_title) > 60:
        fallback_title = fallback_title[:57].rstrip() + "..."

    return fallback_title

# ---------------------------------------------------------------------------
# Public URL builder
# ---------------------------------------------------------------------------

def _build_image_public_url(output_path: str) -> Optional[str]:
    public_base = os.getenv("SOCIAL_GENERATED_IMAGE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not public_base:
        return None
    p = Path(output_path)
    parent_name = p.parent.name
    if parent_name == "generated_images":
        return f"{public_base}/generated_images/{p.name}"
    return f"{public_base}/{p.name}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_news_image(
    items: List[NewsItem],
    external_id: str,
    top_n: int = 3,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Generate a branded news image.

    Returns (local_path, public_url) on success.
    Returns (None, None) if even the PIL fallback fails.

    The PIL branded image is ALWAYS the final output.
    AI/Pexels images are used only as backgrounds.
    """
    if not items:
        return None, None

    brand_text = os.getenv("SOCIAL_BRAND_TEXT", "GermanySupport.de")
    today      = datetime.now().strftime("%B %d, %Y")

    # ------------------------------------------------------------------
    # Step 1: Get background image (AI first, Pexels fallback, then None)
    # ------------------------------------------------------------------
    bg_path: Optional[str] = None

    bg_path = _fetch_ai_background(items, external_id)

    if not bg_path:
        print("  [news_image] AI background unavailable — trying Pexels...")
        bg_path = _fetch_pexels_background(external_id)

    if not bg_path:
        print("  [news_image] No background available — using built-in dark gradient")

    # ------------------------------------------------------------------
    # Step 2: Build SocialPost for the PIL image builder
    # ------------------------------------------------------------------
    news_post = SocialPost(
        external_id=external_id,
        content_type="article",
        #title=f"Germany Daily Update\n{today}",
        title=_build_image_title(items, os.getenv("NEWS_LANGUAGE", "en")),
        link="https://germanysupport.de",
        #summary=_build_image_summary(items, top_n),
        summary="",
        language="en",
        generate_image=False,
    )

    if bg_path:
        news_post.background_image_path = bg_path  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Step 3: Render branded image with PIL
    # This ALWAYS runs — logo, glass panel, headlines, CTA are always drawn
    # ------------------------------------------------------------------
    try:
        output_path = generate_branded_image_v2(
            layout="news",
            show_summary=False,
            post=news_post,
            brand_text=brand_text,
            filename_prefix="news",
            cta_text="Check the comments for more daily Germany updates",
        )
        public_url = _build_image_public_url(output_path)
        print(f"  [news_image] Branded image ready: {output_path}")
        return output_path, public_url

    except Exception as exc:
        print(f"  [news_image] PIL branded image generation failed: {exc}")
        return None, None