"""
Flux (Black Forest Labs) image provider.

High-quality text-to-image model family.
Requires API access via hosted endpoint or SDK.

Environment:
- FLUX_API_KEY
"""
from __future__ import annotations

import os
from typing import Optional

from social.image_generation.base import BaseImageProvider


class FluxProvider(BaseImageProvider):
    """
    Flux image generation provider (premium quality output).
    """

    def __init__(
        self,
        model: str = "flux-1.1-pro",
        width: int = 1024,
        height: int = 1024,
    ):
        self.model = model
        self.width = width
        self.height = height

    @property
    def provider_name(self) -> str:
        return "flux"

    def is_available(self) -> bool:
        return bool(os.getenv("FLUX_API_KEY", "").strip())

    def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        if not self.is_available():
            return None

        prompt = prompt.strip()
        if not prompt:
            return None

        try:
            import requests

            api_key = os.getenv("FLUX_API_KEY")

            url = "https://api.flux.example/v1/generate"  # placeholder endpoint

            payload = {
                "model": kwargs.get("model", self.model),
                "prompt": prompt,
                "width": kwargs.get("width", self.width),
                "height": kwargs.get("height", self.height),
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            response = requests.post(url, json=payload, headers=headers, timeout=60)

            if response.status_code >= 400:
                return None

            data = response.json()

            # expected: {"image_url": "..."}
            return data.get("image_url")

        except Exception:
            return None