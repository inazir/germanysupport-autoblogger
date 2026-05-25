"""
social/image_generation/base.py

Abstract base class for all image generation providers.
Every provider must implement generate_image() and return a URL string or None.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BaseImageProvider(ABC):
    """
    All image providers must subclass this.
    Contract: generate_image() NEVER raises — it returns None on any failure.
    """

    @abstractmethod
    def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        """
        Generate an image for the given prompt.

        Parameters
        ----------
        prompt : descriptive text for the image
        **kwargs : provider-specific options (width, height, style, etc.)

        Returns
        -------
        str  : direct image URL (not binary, not base64)
        None : on any failure — callers must handle None gracefully
        """
        ...

    @property
    def provider_name(self) -> str:
        return self.__class__.__name__

    def is_available(self) -> bool:
        """
        Override to check prerequisites (API keys, connectivity, etc.).
        Default assumes always available.
        """
        return True
