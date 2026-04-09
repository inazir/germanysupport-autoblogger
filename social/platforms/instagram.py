from __future__ import annotations

import time
from typing import Any, Dict

import requests

from social.formatter import build_instagram_caption
from social.models import SocialPost
from social.platforms.base import BasePlatformPublisher, PlatformError, PublishResult


class InstagramPublisher(BasePlatformPublisher):
    def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        url = f"https://graph.facebook.com/{self.target.api_version}/{endpoint}"
        resp = requests.post(url, data=data, timeout=60)
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}
        if not resp.ok or "error" in payload:
            raise PlatformError(f"Instagram POST failed: {payload}")
        return payload

    def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"https://graph.facebook.com/{self.target.api_version}/{endpoint}"
        resp = requests.get(url, params=params, timeout=60)
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}
        if not resp.ok or "error" in payload:
            raise PlatformError(f"Instagram GET failed: {payload}")
        return payload

    def publish(self, post: SocialPost) -> PublishResult:
        if not self.target.ig_business_account_id:
            raise PlatformError(f"Target '{self.target.key}' is missing ig_business_account_id")

        image_url = post.generated_image_public_url or post.image_url
        if not image_url:
            raise PlatformError(f"Instagram target '{self.target.key}' requires image_url or generated_image_public_url")

        create = self._post(
            f"{self.target.ig_business_account_id}/media",
            {
                "image_url": image_url,
                "caption": build_instagram_caption(post, self.target),
                "access_token": self.target.access_token,
            },
        )
        creation_id = str(create.get("id") or "")
        if not creation_id:
            raise PlatformError("Instagram media container creation failed: missing creation id")

        for _ in range(15):
            status = self._get(
                creation_id,
                {"fields": "status_code", "access_token": self.target.access_token},
            )
            code = status.get("status_code")
            if code == "FINISHED":
                break
            if code in {"ERROR", "EXPIRED"}:
                raise PlatformError(f"Instagram media container failed: {status}")
            time.sleep(3)
        else:
            raise PlatformError("Instagram media container did not become ready in time")

        publish = self._post(
            f"{self.target.ig_business_account_id}/media_publish",
            {"creation_id": creation_id, "access_token": self.target.access_token},
        )
        remote_id = str(publish.get("id") or "")
        if not remote_id:
            raise PlatformError("Instagram publish succeeded but no media id was returned")
        return PublishResult(remote_post_id=remote_id)
