from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from social.formatter import build_instagram_caption
from social.models import SocialPost
from social.platforms.base import BasePlatformPublisher, PlatformError, PublishResult


class InstagramPublisher(BasePlatformPublisher):

    # -------------------------
    # HTTP helpers
    # -------------------------
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

    # -------------------------
    # Wait helper
    # -------------------------
    def _wait(self, creation_id: str):
        for _ in range(15):
            status = self._get(
                creation_id,
                {"fields": "status_code", "access_token": self.target.access_token},
            )
            code = status.get("status_code")

            if code == "FINISHED":
                return
            if code in {"ERROR", "EXPIRED"}:
                raise PlatformError(f"Container failed: {status}")

            time.sleep(3)

        raise PlatformError("Container timeout")

    def _publish(self, creation_id: str) -> str:
        result = self._post(
            f"{self.target.ig_business_account_id}/media_publish",
            {
                "creation_id": creation_id,
                "access_token": self.target.access_token,
            },
        )

        return str(result.get("id") or "")

    # -------------------------
    # FEED POST
    # -------------------------
    def publish(self, post: SocialPost) -> PublishResult:
        image_url = post.generated_image_public_url or post.image_url
        if not image_url:
            raise PlatformError("Missing image for feed post")

        create = self._post(
            f"{self.target.ig_business_account_id}/media",
            {
                "image_url": image_url,
                "caption": build_instagram_caption(post, self.target),
                "access_token": self.target.access_token,
            },
        )

        cid = create.get("id")
        if not cid:
            raise PlatformError("Feed creation failed")

        self._wait(cid)
        media_id = self._publish(cid)

        return PublishResult(remote_post_id=media_id)

    # -------------------------
    # REEL (VIDEO ONLY)
    # -------------------------
    def publish_reel(self, post: SocialPost, video_url: str) -> PublishResult:
        if not video_url:
            raise PlatformError("Reel requires video_url")

        create = self._post(
            f"{self.target.ig_business_account_id}/media",
            {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": build_instagram_caption(post, self.target),
                "access_token": self.target.access_token,
            },
        )

        cid = create.get("id")
        if not cid:
            raise PlatformError("Reel creation failed")

        self._wait(cid)
        media_id = self._publish(cid)

        return PublishResult(remote_post_id=media_id)

    # -------------------------
    # STORY (IMAGE ONLY)
    # -------------------------
    def publish_story(
        self,
        post: SocialPost,
        *,
        image_url: Optional[str] = None,
        video_path: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> str:

        if video_path:
            raise PlatformError("Stories do NOT support video_path. Use image story or Reel.")

        final_image = (
            image_url
            or post.generated_image_public_url
            or post.image_url
            or ""
        ).strip()

        if not final_image:
            raise PlatformError("Story requires image_url")

        create = self._post(
            f"{self.target.ig_business_account_id}/media",
            {
                "image_url": final_image,
                "media_type": "STORIES",
                "access_token": self.target.access_token,
            },
        )

        cid = create.get("id")
        if not cid:
            raise PlatformError("Story creation failed")

        self._wait(cid)
        return self._publish(cid)