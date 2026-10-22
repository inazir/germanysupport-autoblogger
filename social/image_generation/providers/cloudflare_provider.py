"""Cloudflare Workers AI image provider."""
from __future__ import annotations

import os
from typing import Optional

import requests

from social.image_generation.base import BaseImageProvider


class CloudflareProvider(BaseImageProvider):
    def __init__(self, steps: int = 6):
        self.steps = steps

    @property
    def provider_name(self) -> str:
        return "cloudflare"

    def is_available(self) -> bool:
        return bool(
            os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
            and os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        )

    def generate_image(self, prompt: str, **kwargs) -> Optional[str]:
        if not self.is_available() or not prompt.strip():
            return None

        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        model = os.getenv(
            "CLOUDFLARE_IMAGE_MODEL",
            "@cf/black-forest-labs/flux-1-schnell",
        ).strip()
        steps = max(1, min(int(kwargs.get("steps", self.steps)), 8))

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                json={"prompt": prompt.strip(), "steps": steps},
                timeout=90,
            )
            if not response.ok:
                print(
                    f"  [CloudflareProvider] HTTP {response.status_code}: "
                    f"{response.text[:1000]}"
                )
                return None
            payload = response.json()
            result = payload.get("result") or {}
            image_base64 = result.get("image")
            if not image_base64:
                print(f"  [CloudflareProvider] No image returned: {payload.get('errors', [])}")
                return None
            return f"data:image/jpeg;base64,{image_base64}"
        except Exception as exc:
            print(f"  [CloudflareProvider] Failed: {exc}")
            return None