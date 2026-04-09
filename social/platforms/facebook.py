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
    ) -> Dict[str, Any]:
        url = f"https://graph.facebook.com/{self.target.api_version}/{endpoint}"
        resp = requests.post(url, data=data, files=files, timeout=60)
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}

        if not resp.ok or "error" in payload:
            raise PlatformError(f"Facebook POST failed: {payload}")
        return payload

    def _normalize_public_image_url(self, image_url: str) -> str:
        """
        Meta is happier with http(s) URLs and common image extensions.
        Leave the URL unchanged here; validation should happen elsewhere.
        """
        return (image_url or "").strip()

    def _build_message(self, post: SocialPost) -> str:
        """
        Central wrapper so all Facebook message generation consistently passes target.
        """
        return build_facebook_message(post, self.target)

    def _create_feed_post(self, post: SocialPost) -> str:
        """
        Standard text/link feed post.
        """
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
        """
        Photo-first Facebook post using a public image URL.
        """
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
        """
        Photo-first Facebook post using a locally generated image file.
        """
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

    def _post_first_comment(self, object_id: str, message: str) -> str:
        """
        Add the article/deal URL as the first comment.
        Commenting works on PagePost/Photo object comments edge.
        """
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

    def publish(self, post: SocialPost):
        """
        Returns a structured publish result.

        Behavior:
        - if image_url is present => create photo post from URL
        - elif generated_image_path is present => upload local file to /photos
        - else => create feed post
        - if target requests first comment link => try comment after post creation
        """
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        post_link_in_first_comment = bool(
            getattr(self.target, "post_link_in_first_comment", False)
        )
        comment_fail_is_fatal = bool(
            getattr(self.target, "comment_fail_is_fatal", False)
        )

        image_url = self._normalize_public_image_url(getattr(post, "image_url", "") or "")
        generated_image_path = (getattr(post, "generated_image_path", "") or "").strip()

        if image_url:
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