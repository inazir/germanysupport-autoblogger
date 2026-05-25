"""
Replicate AI image provider.

Supports multiple image generation models hosted on Replicate.
Requires: REPLICATE_API_TOKEN
"""
from __future__ import annotations

import os
from typing import Optional

from social.image_generation.base import BaseImageProvider


class ReplicateProvider(BaseImageProvider):
    """
    Generic Replicate image generation provider.
    Uses configurable model endpoint.
    """

    def __init__(
        self,
        model: str = "stability-ai/sdxl",
        width: int = 1024,
        height: int = 1024,
    ):
        self.model = model
        self.width = width
        self.height = height

    @property
    def provider_name(self) -> str:
        return "replicate"

    def is_available(self) -> bool:
        return bool(os.getenv("REPLICATE_API_TOKEN", "").strip())

    def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        if not self.is_available():
            return None

        prompt = prompt.strip()
        if not prompt:
            return None

        try:
            import replicate

            client = replicate.Client(api_token=os.getenv("REPLICATE_API_TOKEN"))

            model = kwargs.get("model", self.model)

            output = client.run(
                model,
                input={
                    "prompt": prompt,
                    "width": kwargs.get("width", self.width),
                    "height": kwargs.get("height", self.height),
                },
            )

            if not output:
                return None

            # replicate usually returns list of URLs
            if isinstance(output, list):
                return output[0]

            return output

        except Exception:
            return None