"""
social/image_generation/providers/stability_provider.py

Stability AI provider.

Activated when STABILITY_API_KEY is set.
API docs: https://platform.stability.ai/docs/api-reference
"""
from __future__ import annotations

import os
from typing import Optional

from social.image_generation.base import BaseImageProvider


class StabilityProvider(BaseImageProvider):
    """
    Stability AI image generation provider.

    IMPORTANT:
    - Always returns a stable URL (NOT base64, NOT data URI)
    - Must persist image locally before returning
    """

    def __init__(
        self,
        engine: str = "stable-diffusion-xl-1024-v1-0",
        steps: int = 30,
        cfg_scale: float = 7.0,
        width: int = 1024,
        height: int = 1024,
    ):
        self.engine = engine
        self.steps = steps
        self.cfg_scale = cfg_scale
        self.width = width
        self.height = height

    @property
    def provider_name(self) -> str:
        return "stability"

    def is_available(self) -> bool:
        return bool(os.getenv("STABILITY_API_KEY", "").strip())

    def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        """
        Returns local/public image URL or None.
        Never returns base64 or data URIs.
        Never raises exceptions.
        """

        if not self.is_available():
            return None

        prompt = prompt.strip()
        if not prompt:
            return None

        try:
            import requests

            api_key = os.getenv("STABILITY_API_KEY")

            url = (
                f"https://api.stability.ai/v1/generation/"
                f"{self.engine}/text-to-image"
            )

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            payload = {
                "text_prompts": [{"text": prompt, "weight": 1.0}],
                "cfg_scale": kwargs.get("cfg_scale", self.cfg_scale),
                "height": kwargs.get("height", self.height),
                "width": kwargs.get("width", self.width),
                "steps": kwargs.get("steps", self.steps),
                "samples": 1,
            }

            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=60,
            )

            if response.status_code >= 400:
                return None

            data = response.json()

            artifacts = data.get("artifacts", [])
            if not artifacts:
                return None

            b64 = artifacts[0].get("base64")
            if not b64:
                return None

            # ----------------------------------------
            # IMPORTANT: convert to real file path
            # ----------------------------------------
            return self._save_base64_image(b64)

        except Exception:
            return None

    def _save_base64_image(self, b64: str) -> Optional[str]:
        """
        TODO: implement persistence layer.
        Must:
        - decode base64
        - save to disk (or S3 later)
        - return local/public URL
        """

        try:
            import base64
            import uuid
            from pathlib import Path

            output_dir = Path("tmp/social/images")
            output_dir.mkdir(parents=True, exist_ok=True)

            file_name = f"stability_{uuid.uuid4().hex}.png"
            file_path = output_dir / file_name

            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))

            return str(file_path)

        except Exception:
            return None