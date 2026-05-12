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
    def _wait(self, creation_id: str, max_attempts: int = 40, interval: int = 5):
        """
        Poll until the media container reaches FINISHED status.

        Default: 40 × 5s = 200s (~3.3 min).  Image containers finish in
        seconds; Reels can take 2-3 minutes.  Callers that know they are
        waiting on an image can pass max_attempts=15, interval=3 (same as
        the old hard-coded values) to keep image posts fast.
        """
        for attempt in range(max_attempts):
            status = self._get(
                creation_id,
                {"fields": "status_code", "access_token": self.target.access_token},
            )
            code = status.get("status_code")

            if code == "FINISHED":
                return
            if code in {"ERROR", "EXPIRED"}:
                raise PlatformError(f"Container failed: {status}")

            time.sleep(interval)

        raise PlatformError(
            f"Container timeout after {max_attempts * interval}s "
            f"(container_id={creation_id}, last status={status})"
        )
    def _wait_until_video_ready(self, url: str, max_checks: int = 12, interval: int = 5) -> str:
        """
        Ensures Instagram can fetch the video (prevents 404 / race condition).
        """
        for i in range(max_checks):
            try:
                r = requests.head(url, timeout=10, allow_redirects=True)
                if r.status_code == 200 and "video" in (r.headers.get("content-type", "")):
                    return url
            except Exception:
                pass
    
            print(f"INFO: Video not ready yet (check {i+1}/{max_checks})")
            time.sleep(interval)
    
        raise PlatformError(f"Video URL not stable after wait: {url}")

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
    
        if not video_url.startswith("http"):
            raise PlatformError(f"Invalid video_url: {video_url}")
    
        print(f"[IG] Reel start | URL={video_url}")
    
        video_url = self._wait_until_video_ready(video_url)
    
        try:
            create_payload = {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": build_instagram_caption(post, self.target),
                "access_token": self.target.access_token,
            }
    
            create = self._post(
                f"{self.target.ig_business_account_id}/media",
                create_payload,
            )
    
            cid = create.get("id")
            if not cid:
                raise PlatformError(f"Reel creation failed: {create}")
    
            print(f"[IG] Container created | id={cid}")
            print(f"[IG] Waiting for processing...")
    
            # STEP 1: WAIT FOR PROCESSING
            self._wait(cid, max_attempts=40, interval=5)
    
            print(f"[IG] Container ready")
    
            # STEP 2: SAFETY BUFFER
            time.sleep(5)
    
            # STEP 3: OPTIONAL FINAL URL CHECK
            try:
                import requests
                head = requests.head(video_url, timeout=10)
                if head.status_code != 200:
                    print(f"[IG] URL check warning | status={head.status_code}")
            except Exception as ex:
                print(f"[IG] URL check skipped | {ex}")
    
            # STEP 4: PUBLISH
            print(f"[IG] Publishing reel...")
    
            media_id = self._publish(cid)
    
            if not media_id:
                raise PlatformError(f"Reel publish failed for container_id={cid}")
    
            print(f"[IG] Reel published | media_id={media_id}")
    
            return PublishResult(
                remote_post_id=media_id,
                reel_id=media_id,
            )
    
        except Exception as e:
            print(f"[IG] Reel FAILED | {e}")
            raise PlatformError(f"Instagram reel publish error: {str(e)}") from e
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