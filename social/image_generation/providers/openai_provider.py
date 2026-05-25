"""
social/image_generation/providers/openai_provider.py

OpenAI image provider (DALL-E 3).

Activated when OPENAI_API_KEY is set in .env.

Note: OpenAI image URLs expire (~1 hour).
      Use ImageGenerationService.generate_to_file() if you need a persistent file.
"""
from __future__ import annotations

import os
from typing import Optional

from social.image_generation.base import BaseImageProvider


class OpenAIProvider(BaseImageProvider):
    """
    OpenAI DALL-E image generation.
    Returns a temporary CDN URL valid for ~1 hour.
    """

    def __init__(
        self,
        model:   str = "dall-e-3",
        size:    str = "1792x1024",
        quality: str = "standard",
    ):
        self.model   = model
        self.size    = size
        self.quality = quality

    @property
    def provider_name(self) -> str:
        return "openai"

    def is_available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY", "").strip())

    def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        if not self.is_available():
            return None

        prompt = (prompt or "").strip()
        if not prompt:
            return None

        model   = kwargs.get("model",   self.model)
        size    = kwargs.get("size",    self.size)
        quality = kwargs.get("quality", self.quality)

        try:
            from openai import OpenAI

            client   = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                size=size,
                quality=quality,
            )

            if not response or not response.data:
                return None

            return response.data[0].url

        except ImportError:
            print("  [OpenAIProvider] openai package not installed")
            return None
        except Exception as e:
            print(f"  [OpenAIProvider] Failed: {e}")
            return None


# Backward-compat alias (old code used OpenAIImageProvider)
OpenAIImageProvider = OpenAIProvider
