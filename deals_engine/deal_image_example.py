"""
deals_engine/deal_image_example.py

Example: How to use ImageGenerationService inside the deals engine.

Pattern is identical to all other modules — only the prompt builder differs.
"""
from __future__ import annotations

from typing import Optional

from social.image_generation import ImageGenerationService, build_deal_image_prompt


def get_deal_image(product_name: str, category: str = "product") -> Optional[str]:
    """
    Returns an AI-generated product image URL for a deal post.
    Returns None if generation fails — pipeline must handle gracefully.

    Usage inside DealPublisher:
        image_url = get_deal_image(deal.product_name, deal.category)
        if image_url:
            post_payload["image_url"] = image_url
    """
    prompt = build_deal_image_prompt(product=product_name, category=category)
    return ImageGenerationService.generate(prompt)
