"""
Pollinations AI image provider.

API:
https://image.pollinations.ai/prompt/{encoded_prompt}

Optional API key:
POLLINATIONS_API_KEY=pk_xxx
"""
from __future__ import annotations

import os
from typing import Optional
from urllib.parse import quote
import urllib.request

from social.image_generation.base import BaseImageProvider


_BASE_URL = "https://image.pollinations.ai/prompt"
_DEFAULT_TIMEOUT = 30


class PollinationsProvider(BaseImageProvider):

    def __init__(
        self,
        width: int = 1200,
        height: int = 630,
        seed: Optional[int] = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ):
        self.width = width
        self.height = height
        self.seed = seed
        self.timeout = timeout

    @property
    def provider_name(self) -> str:
        return "pollinations"

    def is_available(self) -> bool:
        return os.getenv("POLLINATIONS_ENABLED", "true").strip().lower() not in (
            "false",
            "0",
            "no",
        )

    def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        """
        Returns Pollinations image URL or None.
        """

        if not self.is_available():
            return None

        try:
            # -------------------------
            # Config resolution
            # -------------------------
            width = kwargs.get("width", self.width)
            height = kwargs.get("height", self.height)
            seed = kwargs.get("seed", self.seed)

            prompt = prompt.strip()
            if not prompt:
                return None

            encoded_prompt = quote(prompt, safe="")

            # -------------------------
            # Build URL
            # -------------------------
            url = (
                f"{_BASE_URL}/{encoded_prompt}"
                f"?width={width}"
                f"&height={height}"
                f"&nologo=true"
            )

            if seed is not None:
                url += f"&seed={seed}"

            api_key = os.getenv("POLLINATIONS_API_KEY", "").strip()
            if api_key:
                url += f"&key={api_key}"

            # -------------------------
            # Lightweight validation
            # -------------------------
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if 200 <= resp.status < 300:
                    return url

            return None

        except Exception:
            # intentionally silent failure (contract: never raise)
            return None