"""
social/image_generation/prompts.py

Shared prompt builders for image generation across all modules.

Rules for all prompts:
  - Short and descriptive (under 200 chars recommended)
  - No logos, trademarks, brand names, or watermarks
  - Editorial / professional photography style
  - Cross-domain compatible (work for any AI image provider)
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# News / editorial
# ---------------------------------------------------------------------------

def build_news_image_prompt(
    topic: str,
    location: str = "Germany",
    style: str = "editorial news",
) -> str:
    """
    Build a prompt for a news article or daily news update image.

    Parameters
    ----------
    topic    : main subject, e.g. "housing costs", "train strikes", "visa changes"
    location : geographic context (default: Germany)
    style    : visual style hint

    Example output:
        "Editorial news photo of housing costs in Germany, realistic journalism
         style, professional lighting, high detail, no logos or watermarks"
    """
    prompt = (
        f"Editorial news photo of {topic} in {location}, "
        f"realistic {style} style, professional lighting, "
        f"high detail, no logos no watermarks no text"
    )
    return prompt[:400]  # hard cap for URL safety


def build_article_image_prompt(
    title: str,
    category: str = "expat life",
    location: str = "Germany",
) -> str:
    """
    Build a prompt for a blog article featured image.
    """
    prompt = (
        f"Professional editorial photo illustrating '{title}', "
        f"{category} theme, set in {location}, "
        f"clean composition, natural lighting, no text no logos"
    )
    return prompt[:400]


# ---------------------------------------------------------------------------
# Social / lifestyle
# ---------------------------------------------------------------------------

def build_social_image_prompt(
    topic: str,
    mood: str = "friendly and informative",
) -> str:
    """
    Build a prompt for a generic social media post image.
    """
    prompt = (
        f"Social media lifestyle photo about {topic}, "
        f"{mood} mood, vibrant colors, modern aesthetic, "
        f"no text no watermarks no logos"
    )
    return prompt[:400]


# ---------------------------------------------------------------------------
# Deals / e-commerce
# ---------------------------------------------------------------------------

def build_deal_image_prompt(
    product: str,
    category: str = "product",
) -> str:
    """
    Build a prompt for a deal or product offer image.
    """
    prompt = (
        f"Clean product photography of {product}, "
        f"{category} category, white or neutral background, "
        f"professional studio lighting, sharp focus, no watermarks no logos no price tags"
    )
    return prompt[:400]


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

def build_generic_prompt(subject: str) -> str:
    """Minimal prompt when no specific builder applies."""
    return (
        f"Professional high-quality photo of {subject}, "
        f"clean composition, natural lighting, no text no logos"
    )[:400]
