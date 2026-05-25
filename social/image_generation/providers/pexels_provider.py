"""
social/image_generation/providers/pexels_provider.py

Pexels image provider.

Wraps the existing social/pexels_client.py so Pexels can be used
as a standard image provider in the provider chain.

Requires: PEXELS_KEY in .env
"""
from __future__ import annotations

import os
from typing import Optional

from social.image_generation.base import BaseImageProvider


class PexelsProvider(BaseImageProvider):
    """
    Fetches a relevant stock photo from Pexels.
    Returns the direct image URL (large2x size).
    """

    def __init__(self, orientation: str = "landscape", per_page: int = 5):
        self.orientation = orientation
        self.per_page    = per_page

    @property
    def provider_name(self) -> str:
        return "pexels"

    def is_available(self) -> bool:
        return bool(os.getenv("PEXELS_KEY", "").strip())

    def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        """
        Uses the prompt as the Pexels search query.
        Returns the first result's large2x URL, or None.
        """
        if not self.is_available():
            return None
    
        prompt = (prompt or "").strip()
        if not prompt:
            return None
    
        try:
            from social.pexels_client import search_photo
    
            api_key = os.getenv("PEXELS_KEY", "").strip()
    
            photo = search_photo(
                query=prompt,
                api_key=api_key,
                per_page=kwargs.get("per_page", self.per_page),
                orientation=kwargs.get("orientation", self.orientation),
            )
    
            if not photo:
                return None
    
            src = photo.get("src") or {}
    
            url = (
                src.get("large2x")
                or src.get("large")
                or src.get("original")
                or src.get("medium")
            )
    
            if not url:
                return None
    
            return {
                "url": url,
                "photographer": photo.get("photographer"),
                "photographer_url": photo.get("photographer_url"),
                "source": "pexels",
            }
    
        except Exception as e:
            print(f"  [PexelsProvider] Failed: {e}")
            return None