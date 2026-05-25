"""
social/image_generation/__init__.py

Public surface of the image generation package.
All external modules should import from here or from service.py directly.
"""
from social.image_generation.service import ImageGenerationService
from social.image_generation.image_builder import generate_branded_image_v2
from social.image_generation.prompts import (
    build_news_image_prompt,
    build_article_image_prompt,
    build_social_image_prompt,
    build_deal_image_prompt,
    build_generic_prompt,
)

__all__ = [
    "ImageGenerationService",
    "generate_branded_image_v2",
    "build_news_image_prompt",
    "build_article_image_prompt",
    "build_social_image_prompt",
    "build_deal_image_prompt",
    "build_generic_prompt",
]
