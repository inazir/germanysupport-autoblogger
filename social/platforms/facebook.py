# social/platforms/facebook.py
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Dict

import requests

from social.formatter import build_facebook_message
from social.models import SocialPost
from social.platforms.base import BasePlatformPublisher, PlatformError


class FacebookPublisher(BasePlatformPublisher):

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------

    def _normalize_public_image_url(self, image_url: str) -> str:
        return (image_url or "").strip()

    def _build_message(self, post: SocialPost) -> str:
        return build_facebook_message(post, self.target)

    def _load_pages(self):
        """
        Load the Facebook page credentials for the CURRENT target only.

        FIX: previously scanned ALL env vars ending in __PAGE_ID, which caused
        every configured Facebook page to receive the post — even pages belonging
        to different targets (e.g. BG_FB_MAIN posted when only GS_FB_MAIN was
        requested by share_news.py).

        Now scoped to self.target.key so each publisher instance only posts
        to its own page. If self.target.key = "gs_fb_main", only reads:
            SOCIAL__GS_FB_MAIN__PAGE_ID
            SOCIAL__GS_FB_MAIN__ACCESS_TOKEN
        """
        env_prefix = f"SOCIAL__{self.target.key.upper()}"
        page_id    = os.getenv(f"{env_prefix}__PAGE_ID",      "").strip()
        token      = os.getenv(f"{env_prefix}__ACCESS_TOKEN", "").strip()

        if (
            page_id
            and token
            and not page_id.upper().startswith("YOUR_")
            and not token.upper().startswith("YOUR_")
        ):
            return [(env_prefix, page_id, token)]

        # Fallback: values already on self.target (set by social/config.py)
        if self.target.page_id and self.target.access_token:
            return [("default", self.target.page_id, self.target.access_token)]

        return []

    # ------------------------------------------------------------------
    # Feed / photo helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Reels upload (3-phase: start → upload → finish)
    # ------------------------------------------------------------------

    def _upload_reels_video(self, post: SocialPost, video_path: str) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        video_path = (video_path or "").strip()
        if not video_path:
            raise PlatformError("Reels upload requires a non-empty video_path")

        file_size = os.path.getsize(video_path)

        init_payload = self._post(
            f"{self.target.page_id}/video_reels",
            {"upload_phase": "start", "access_token": self.target.access_token},
            timeout=30,
        )

        video_id   = str(init_payload.get("video_id")  or "").strip()
        upload_url = str(init_payload.get("upload_url") or "").strip()

        if not video_id or not upload_url:
            raise PlatformError(f"Reels start phase returned unexpected payload: {init_payload}")

        with open(video_path, "rb") as vf:
            upload_resp = requests.post(
                upload_url,
                data=vf,
                headers={
                    "Authorization": f"OAuth {self.target.access_token}",
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(file_size),
                    "offset": "0",
                    "file_size": str(file_size),
                },
                timeout=600,
            )

        try:
            upload_result = upload_resp.json()
        except Exception:
            upload_result = {"raw_text": upload_resp.text}

        if not upload_resp.ok or "error" in upload_result:
            raise PlatformError(f"Reels upload phase (binary POST) failed: {upload_result}")

        import time

        finish_payload = self._post(
            f"{self.target.page_id}/video_reels",
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "published": "true",
                "share_to_feed": "true",
                "description": self._build_message(post),
                "title": (post.title or "")[:255],
                "access_token": self.target.access_token,
            },
            timeout=60,
        )

        if not finish_payload.get("success") and "id" not in finish_payload:
            raise PlatformError(f"Reels finish phase returned unexpected payload: {finish_payload}")

        print(f"INFO: Reel finish response: {finish_payload}")
        time.sleep(15)

        verify_resp = requests.get(
            f"https://graph.facebook.com/{self.target.api_version}/{video_id}",
            params={"fields": "id,status,permalink_url", "access_token": self.target.access_token},
            timeout=30,
        )
        try:
            verify = verify_resp.json()
        except Exception:
            verify = {}

        print(f"INFO: Reel status after 15s: {verify.get('status', {})}")
        return video_id

    # ------------------------------------------------------------------
    # Legacy video helper
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Comment helper
    # ------------------------------------------------------------------

    def _post_first_comment(self, object_id: str, message: str) -> str:
        message = (message or "").strip()
        if not message:
            raise PlatformError("Cannot create first comment with empty message")

        payload = self._post(
            f"{object_id}/comments",
            {"message": message, "access_token": self.target.access_token},
        )
        comment_id = str(payload.get("id", "")).strip()
        if not comment_id:
            raise PlatformError(f"Facebook comment created but no id returned: {payload}")
        return comment_id

    # ------------------------------------------------------------------
    # Story helpers
    # ------------------------------------------------------------------

    def _upload_unpublished_photo_from_url(self, image_url: str) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        payload = self._post(
            f"{self.target.page_id}/photos",
            {"url": image_url, "published": "false", "access_token": self.target.access_token},
        )
        photo_id = str(payload.get("id") or "").strip()
        if not photo_id:
            raise PlatformError(f"Facebook unpublished photo upload failed: {payload}")
        return photo_id

    def _upload_unpublished_photo_from_file(self, image_path: str) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        with open(image_path, "rb") as image_file:
            payload = self._post(
                f"{self.target.page_id}/photos",
                {"published": "false", "access_token": self.target.access_token},
                files={"source": image_file},
            )

        photo_id = str(payload.get("id") or "").strip()
        if not photo_id:
            raise PlatformError(f"Facebook unpublished local photo upload failed: {payload}")
        return photo_id

    def publish_story(
        self,
        post: SocialPost,
        *,
        image_path: str | None = None,
        image_url: str | None = None,
        video_path: str | None = None,
    ) -> str:
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")
    
        # --- PREFER VIDEO STORY ---
        if video_path and os.path.exists(video_path):
            try:
                print(f"INFO: Starting 3-step video story upload for {video_path}")
                return self._upload_video_story(video_path)
            except Exception as ve:
                print(f"WARNING: Video story failed ({ve}), will attempt image story.")
    
        # --- IMAGE STORY via /photo_stories endpoint ---
        image_url = self._normalize_public_image_url(image_url or "")
        if not image_url:
            # No image available — skip silently instead of polluting the feed
            print(f"INFO: No story media available for {self.target.key} — skipping story (no feed fallback).")
            raise PlatformError("Story skipped: no image_url or video_path available")
    
        # Upload as unpublished photo first
        try:
            photo_id = self._upload_unpublished_photo_from_url(image_url)
        except Exception as e:
            print(f"WARNING: Story photo upload failed for {self.target.key}: {e} — skipping story.")
            raise PlatformError(f"Story photo upload failed: {e}")
    
        # Publish as actual story via /photo_stories
        try:
            story_payload = self._post(
                f"{self.target.page_id}/photo_stories",
                {
                    "photo_id": photo_id,
                    "access_token": self.target.access_token,
                },
            )
            story_id = str(story_payload.get("post_id") or story_payload.get("id") or "").strip()
            if not story_id:
                raise PlatformError(f"photo_stories returned no id: {story_payload}")
            print(f"INFO: Story published via photo_stories for {self.target.key}: {story_id}")
            return story_id
        except Exception as e:
            # Story failed — log and skip, do NOT fall back to feed post
            print(f"WARNING: photo_stories failed for {self.target.key}: {e} — skipping story (no feed fallback).")
            raise PlatformError(f"Story publish failed (no feed fallback): {e}")
    def _upload_video_story(self, video_path: str) -> str:
        init_res = self._post(f"{self.target.page_id}/video_stories", {
            "upload_phase": "start", "access_token": self.target.access_token
        })
        video_id   = init_res.get("video_id")
        upload_url = init_res.get("upload_url")

        file_size = os.path.getsize(video_path)
        with open(video_path, "rb") as f:
            binary_data = f.read()

        resp = requests.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {self.target.access_token}",
                "offset": "0", "file_size": str(file_size),
                "Content-Type": "application/octet-stream",
            },
            data=binary_data,
            timeout=120,
        )
        if not resp.ok:
            raise PlatformError(f"Video story binary upload failed: {resp.text}")

        finish_res = self._post(f"{self.target.page_id}/video_stories", {
            "upload_phase": "finish", "video_id": video_id,
            "access_token": self.target.access_token,
        })
        if finish_res.get("success"):
            return str(video_id)
        raise PlatformError(f"Video story finish phase failed: {finish_res}")

    # ------------------------------------------------------------------
    # publish() — main entry point
    # ------------------------------------------------------------------

    def publish(self, post: SocialPost):

        pages = self._load_pages()

        if not pages:
            raise PlatformError(
                f"No valid Facebook page configured for target '{self.target.key}'. "
                f"Check SOCIAL__{self.target.key.upper()}__PAGE_ID in .env"
            )

        primary = None
        results = []

        for name, page_id, token in pages:

            print(f"\nINFO: ===== Posting to {name} ({page_id}) =====")

            # Save → swap → restore pattern.
            # SocialTarget is a dataclass; vars() already has page_id and access_token,
            # so SimpleNamespace(**vars(target), page_id=x) crashes with
            # "multiple values for keyword argument". Save/restore avoids that entirely.
            _orig_page_id      = self.target.page_id
            _orig_access_token = self.target.access_token
            self.target.page_id      = page_id
            self.target.access_token = token

            post_link_in_first_comment = bool(getattr(self.target, "post_link_in_first_comment", False))
            comment_fail_is_fatal      = bool(getattr(self.target, "comment_fail_is_fatal", False))

            video_path           = (getattr(post, "generated_video_path", "") or getattr(post, "video_path", "") or "").strip()
            image_url            = self._normalize_public_image_url(getattr(post, "image_url", "") or "")
            generated_image_path = (getattr(post, "generated_image_path", "") or "").strip()

            fb_post_id       = None
            reel_id          = None
            first_comment_id = None
            story_id         = None  # always initialised so SimpleNamespace never hits NameError

            try:
                # --- STEP 1: FEED POST ---
                try:
                    if image_url:
                        fb_post_id = self._create_photo_post_from_url(post, image_url)
                        print(f"INFO: Timeline Image Post created: {fb_post_id}")
                    elif generated_image_path:
                        fb_post_id = self._create_photo_post_from_file(post, generated_image_path)
                        print(f"INFO: Timeline Image Post created: {fb_post_id}")
                    else:
                        fb_post_id = self._create_feed_post(post)
                        print(f"INFO: Timeline Text Post created: {fb_post_id}")
                except Exception as e:
                    print(f"ERROR: Timeline post failed for {name}: {e}")

                # --- STEP 2: LINK COMMENT ---
                if fb_post_id and post_link_in_first_comment and post.link:
                    try:
                        first_comment_id = self._post_first_comment(fb_post_id, post.link)
                        print(f"INFO: Link comment added: {first_comment_id}")
                    except Exception as exc:
                        if comment_fail_is_fatal:
                            raise
                        print(f"WARNING: Link comment failed for {name}: {exc}")

                # --- STEP 3: REEL ---
                if video_path and os.path.exists(video_path):
                    try:
                        print("INFO: Uploading Reel...")
                        reel_id = self._upload_reels_video(post, video_path)
                        print(f"INFO: Reel created: {reel_id}")
                        if reel_id and post.link:
                            try:
                                self._post_first_comment(reel_id, post.link)
                                print("INFO: Reel first comment added")
                            except Exception as e:
                                print(f"WARNING: Reel comment failed: {e}")
                    except Exception as e:
                        print(f"WARNING: Reel upload failed for {name}: {e}")

                # --- STEP 4: STORY ---
                if getattr(self.target, "publish_story", False):
                    try:
                        image_url_for_story = self._normalize_public_image_url(
                            getattr(post, "story_generated_image_public_url", "")
                            or getattr(post, "generated_image_public_url", "")
                            or getattr(post, "image_url", "")
                            or ""
                        )
                        story_id = self.publish_story(
                            post,
                            image_url=image_url_for_story or None,
                            video_path=video_path or None,
                        )
                        print(f"INFO: Story published for {name}: {story_id}")
                    except Exception as e:
                        print(f"WARNING: Story failed for {name}: {e}")

            finally:
                # Always restore, even if an exception occurred mid-loop
                self.target.page_id      = _orig_page_id
                self.target.access_token = _orig_access_token

            page_result = SimpleNamespace(
                page=name,
                remote_post_id=fb_post_id,
                reel_id=reel_id,
                first_comment_id=first_comment_id,
                story_id=story_id,
            )
            results.append(page_result)

            if primary is None and fb_post_id:
                primary = page_result

        result = primary or results[0]
        result.story_handled = True
        return result