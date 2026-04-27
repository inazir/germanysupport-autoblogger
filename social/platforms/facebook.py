# social/platforms/facebook.py
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import requests

from social.formatter import build_facebook_message
from social.models import SocialPost
from social.platforms.base import BasePlatformPublisher, PlatformError


class FacebookPublisher(BasePlatformPublisher):
    def _post(
        self,
        endpoint: str,
        data: Dict[str, Any],
        files: Dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        url = f"https://graph.facebook.com/{self.target.api_version}/{endpoint}"
        resp = requests.post(url, data=data, files=files, timeout=timeout)
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}

        if not resp.ok or "error" in payload:
            raise PlatformError(f"Facebook POST failed: {payload}")
        return payload

    def _normalize_public_image_url(self, image_url: str) -> str:
        return (image_url or "").strip()

    def _build_message(self, post: SocialPost) -> str:
        return build_facebook_message(post, self.target)

    def _create_feed_post(self, post: SocialPost) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        payload = self._post(
            f"{self.target.page_id}/feed",
            {
                "message": self._build_message(post),
                "access_token": self.target.access_token,
            },
        )

        post_id = str(payload.get("id", "")).strip()
        if not post_id:
            raise PlatformError(f"Facebook feed post created but no id returned: {payload}")
        return post_id

    def _create_photo_post_from_url(self, post: SocialPost, image_url: str) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        payload = self._post(
            f"{self.target.page_id}/photos",
            {
                "url": image_url,
                "published": "true",
                "message": self._build_message(post),
                "access_token": self.target.access_token,
            },
        )

        post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
        if not post_id:
            raise PlatformError(f"Facebook photo post created but no post id returned: {payload}")
        return post_id

    def _create_photo_post_from_file(self, post: SocialPost, image_path: str) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        with open(image_path, "rb") as image_file:
            payload = self._post(
                f"{self.target.page_id}/photos",
                {
                    "published": "true",
                    "message": self._build_message(post),
                    "access_token": self.target.access_token,
                },
                files={"source": image_file},
            )

        post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
        if not post_id:
            raise PlatformError(f"Facebook photo upload created but no post id returned: {payload}")
        return post_id

    def _create_video_post_from_file(self, post: SocialPost, video_path: str) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        video_path = (video_path or "").strip()
        if not video_path:
            raise PlatformError("Facebook video upload requires a non-empty video_path")

        with open(video_path, "rb") as video_file:
            payload = self._post(
                f"{self.target.page_id}/videos",
                {
                    "published": "true",
                    "description": self._build_message(post),
                    "access_token": self.target.access_token,
                },
                files={"source": video_file},
                timeout=300,
            )

        video_id = str(payload.get("id") or "").strip()
        if not video_id:
            raise PlatformError(f"Facebook video upload created but no video id returned: {payload}")
        return video_id

    def _post_first_comment(self, object_id: str, message: str) -> str:
        message = (message or "").strip()
        if not message:
            raise PlatformError("Cannot create first comment with empty message")

        payload = self._post(
            f"{object_id}/comments",
            {
                "message": message,
                "access_token": self.target.access_token,
            },
        )
        comment_id = str(payload.get("id", "")).strip()
        if not comment_id:
            raise PlatformError(f"Facebook comment created but no id returned: {payload}")
        return comment_id

    def _upload_unpublished_photo_from_url(self, image_url: str) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        payload = self._post(
            f"{self.target.page_id}/photos",
            {
                "url": image_url,
                "published": "false",
                "access_token": self.target.access_token,
            },
        )
        photo_id = str(payload.get("id") or "").strip()
        if not photo_id:
            raise PlatformError(f"Facebook unpublished photo upload failed: missing photo id: {payload}")
        return photo_id

    def _upload_unpublished_photo_from_file(self, image_path: str) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        with open(image_path, "rb") as image_file:
            payload = self._post(
                f"{self.target.page_id}/photos",
                {
                    "published": "false",
                    "access_token": self.target.access_token,
                },
                files={"source": image_file},
            )

        photo_id = str(payload.get("id") or "").strip()
        if not photo_id:
            raise PlatformError(f"Facebook unpublished local photo upload failed: missing photo id: {payload}")
        return photo_id

    def publish_story(
        self,
        post: SocialPost,
        *,
        image_path: str | None = None,
        image_url: str | None = None,
    ) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        image_url = self._normalize_public_image_url(image_url or "")

        if not image_url:
            raise PlatformError(
                f"Facebook story target '{self.target.key}' requires a public image_url. "
                f"Set SOCIAL_GENERATED_IMAGE_PUBLIC_BASE_URL so generated images are reachable."
            )

        photo_id = self._upload_unpublished_photo_from_url(image_url)

        payload = self._post(
            f"{self.target.page_id}/photo_stories",
            {
                "photo_id": photo_id,
                "access_token": self.target.access_token,
            },
        )
        story_id = str(payload.get("id") or "").strip()
        if not story_id:
            raise PlatformError(f"Facebook story created but no id returned: {payload}")
        return story_id

    def publish(self, post: SocialPost):
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        post_link_in_first_comment = bool(
            getattr(self.target, "post_link_in_first_comment", False)
        )
        comment_fail_is_fatal = bool(
            getattr(self.target, "comment_fail_is_fatal", False)
        )

        video_path = (getattr(post, "generated_video_path", "") or getattr(post, "video_path", "") or "").strip()
        image_url = self._normalize_public_image_url(getattr(post, "image_url", "") or "")
        generated_image_path = (getattr(post, "generated_image_path", "") or "").strip()

        if video_path:
            fb_post_id = self._create_video_post_from_file(post, video_path)
        elif image_url:
            fb_post_id = self._create_photo_post_from_url(post, image_url)
        elif generated_image_path:
            fb_post_id = self._create_photo_post_from_file(post, generated_image_path)
        else:
            fb_post_id = self._create_feed_post(post)

        first_comment_id = None
        if post_link_in_first_comment and post.link:
            try:
                first_comment_id = self._post_first_comment(fb_post_id, post.link)
            except Exception as exc:
                if comment_fail_is_fatal:
                    raise
                print(
                    f"WARNING: Facebook post created ({fb_post_id}) "
                    f"but first comment failed: {exc}"
                )

        return SimpleNamespace(
            remote_post_id=fb_post_id,
            first_comment_id=first_comment_id,
        )
