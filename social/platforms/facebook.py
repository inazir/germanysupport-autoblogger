# social/platforms/facebook.py
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace
from typing import Any, Dict

import requests

from social.formatter import build_facebook_message
from social.models import SocialPost
from social.platforms.base import BasePlatformPublisher, PlatformError


class FacebookPublisher(BasePlatformPublisher):
    """
    Facebook Publisher with CLEAN DEBUG mode.

    Enable debug with env:
        FACEBOOK_DEBUG=1

    Then logs will print:
        FB_DEBUG [...]
    """

    # ------------------------------------------------------------------
    # Debug helpers
    # ------------------------------------------------------------------

    def _is_debug(self) -> bool:
        return str(os.getenv("FACEBOOK_DEBUG", "0")).lower() in {
            "1", "true", "yes", "on"
        }

    def _debug(self, label: str, data: Any = None):
        if not self._is_debug():
            return

        try:
            txt = json.dumps(data, default=str, ensure_ascii=False)
        except Exception:
            txt = str(data)

        print(f"FB_DEBUG [{label}] {txt}")

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _post(
        self,
        endpoint: str,
        data: Dict[str, Any],
        files: Dict[str, Any] | None = None,
        timeout: int = 60,
    ) -> Dict[str, Any]:

        url = f"https://graph.facebook.com/{self.target.api_version}/{endpoint}"

        safe = dict(data)
        if "access_token" in safe:
            safe["access_token"] = "***hidden***"

        self._debug(
            "POST_REQUEST",
            {
                "url": url,
                "data": safe,
                "has_files": bool(files),
            },
        )

        resp = requests.post(url, data=data, files=files, timeout=timeout)

        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}

        self._debug(
            "POST_RESPONSE",
            {
                "status_code": resp.status_code,
                "ok": resp.ok,
                "payload": payload,
            },
        )

        if not resp.ok or "error" in payload:
            raise PlatformError(f"Facebook POST failed: {payload}")

        return payload

    def _get(
        self,
        endpoint: str,
        params: Dict[str, Any],
        timeout: int = 60,
    ) -> Dict[str, Any]:

        url = f"https://graph.facebook.com/{self.target.api_version}/{endpoint}"

        safe = dict(params)
        if "access_token" in safe:
            safe["access_token"] = "***hidden***"

        self._debug(
            "GET_REQUEST",
            {
                "url": url,
                "params": safe,
            },
        )

        resp = requests.get(url, params=params, timeout=timeout)

        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}

        self._debug(
            "GET_RESPONSE",
            {
                "status_code": resp.status_code,
                "ok": resp.ok,
                "payload": payload,
            },
        )

        return payload

    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------

    def _normalize_public_image_url(self, image_url: str) -> str:
        return (image_url or "").strip()

    def _build_message(self, post: SocialPost) -> str:
        return build_facebook_message(post, self.target)

    # ------------------------------------------------------------------
    # Feed / photo
    # ------------------------------------------------------------------

    def _create_feed_post(self, post: SocialPost) -> str:
        payload = self._post(
            f"{self.target.page_id}/feed",
            {
                "message": self._build_message(post),
                "access_token": self.target.access_token,
            },
        )

        post_id = str(payload.get("id") or "").strip()
        if not post_id:
            raise PlatformError("Feed post created but no id returned")

        return post_id

    def _create_photo_post_from_url(self, post: SocialPost, image_url: str) -> str:
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
            raise PlatformError("Photo post created but no id returned")

        return post_id

    def _create_photo_post_from_file(self, post: SocialPost, image_path: str) -> str:
        with open(image_path, "rb") as f:
            payload = self._post(
                f"{self.target.page_id}/photos",
                {
                    "published": "true",
                    "message": self._build_message(post),
                    "access_token": self.target.access_token,
                },
                files={"source": f},
            )

        post_id = str(payload.get("post_id") or payload.get("id") or "").strip()

        if not post_id:
            raise PlatformError("Photo upload created but no id returned")

        return post_id

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def _post_first_comment(self, object_id: str, message: str) -> str:
        payload = self._post(
            f"{object_id}/comments",
            {
                "message": message,
                "access_token": self.target.access_token,
            },
        )

        cid = str(payload.get("id") or "").strip()

        if not cid:
            raise PlatformError("Comment created but no id returned")

        return cid
        

    # ------------------------------------------------------------------
    # REELS upload (3-phase)
    # ------------------------------------------------------------------

    def _upload_reels_video(self, post: SocialPost, video_path: str) -> str:
        if not os.path.exists(video_path):
            raise PlatformError(f"Video file missing: {video_path}")

        file_size = os.path.getsize(video_path)

        # ---------------------------
        # PHASE 1 START
        # ---------------------------

        init_payload = self._post(
            f"{self.target.page_id}/video_reels",
            {
                "upload_phase": "start",
                "access_token": self.target.access_token,
            },
            timeout=30,
        )

        self._debug("REEL_START_OK", init_payload)

        video_id = str(init_payload.get("video_id") or "").strip()
        upload_url = str(init_payload.get("upload_url") or "").strip()

        if not video_id or not upload_url:
            raise PlatformError("Reel start phase missing video_id/upload_url")

        # ---------------------------
        # PHASE 2 BINARY UPLOAD
        # ---------------------------

        with open(video_path, "rb") as vf:
            resp = requests.post(
                upload_url,
                data=vf,
                headers={
                    "Authorization": f"OAuth {self.target.access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(file_size),
                },
                timeout=900,
            )

        try:
            upload_payload = resp.json()
        except Exception:
            upload_payload = {"raw_text": resp.text}

        self._debug(
            "REEL_BINARY_UPLOAD",
            {
                "status_code": resp.status_code,
                "ok": resp.ok,
                "payload": upload_payload,
            },
        )

        if not resp.ok or "error" in upload_payload:
            raise PlatformError("Reel binary upload failed")

        # ---------------------------
        # PHASE 3 FINISH
        # ---------------------------

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

        self._debug("REEL_FINISH", finish_payload)

        # Wait for Meta processing
        time.sleep(5)

        # ---------------------------
        # VERIFY OBJECT
        # ---------------------------

        verify = self._get(
            video_id,
            {
                "fields": "id,status,permalink_url,title,description,length",
                "access_token": self.target.access_token,
            },
        )

        self._debug("REEL_VERIFY_OBJECT", verify)

        # ---------------------------
        # VERIFY PAGE REELS
        # ---------------------------

        reels = self._get(
            f"{self.target.page_id}/video_reels",
            {
                "access_token": self.target.access_token,
            },
        )

        self._debug("PAGE_REELS_LIST", reels)

        return video_id

    # ------------------------------------------------------------------
    # STORY (kept simple)
    # ------------------------------------------------------------------

    def publish_story(
        self,
        post: SocialPost,
        *,
        image_path: str | None = None,
        image_url: str | None = None,
        video_path: str | None = None,
    ) -> str:
    
        if not self.target.page_id:
            raise PlatformError("Missing page_id")
    
        # -------------------------
        # VIDEO STORY (preferred)
        # -------------------------
        if video_path and os.path.exists(video_path):
            try:
                print(f"INFO: Uploading VIDEO story: {video_path}")
                return self._upload_video_story(video_path)
            except Exception as e:
                print(f"WARNING: Video story failed: {e}")
    
        # -------------------------
        # IMAGE STORY (URL only - correct way)
        # -------------------------
        image_url = (image_url or "").strip()
    
        if image_url:
            payload = self._post(
                f"{self.target.page_id}/photo_stories",
                {
                    "url": image_url,
                    "access_token": self.target.access_token,
                },
            )
    
            story_id = str(payload.get("id") or "").strip()
            if not story_id:
                raise PlatformError(f"Image story failed: {payload}")
    
            return story_id
    
        # -------------------------
        # LOCAL IMAGE fallback
        # -------------------------
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                payload = self._post(
                    f"{self.target.page_id}/photo_stories",
                    {
                        "access_token": self.target.access_token,
                    },
                    files={"source": f},
                )
    
            story_id = str(payload.get("id") or "").strip()
            if not story_id:
                raise PlatformError(f"Image story upload failed: {payload}")
    
            return story_id
    
        raise PlatformError("Story requires image_url, image_path, or video_path")

    def _upload_video_story(self, video_path: str) -> str:
        if not self.target.page_id:
            raise PlatformError("Missing page_id")
    
        file_size = os.path.getsize(video_path)
    
        # 1. START
        init = self._post(
            f"{self.target.page_id}/video_stories",
            {
                "upload_phase": "start",
                "access_token": self.target.access_token,
            },
        )
    
        video_id = init.get("video_id")
        upload_url = init.get("upload_url")
    
        if not video_id or not upload_url:
            raise PlatformError(f"Story init failed: {init}")
    
        # 2. UPLOAD
        with open(video_path, "rb") as f:
            resp = requests.post(
                upload_url,
                data=f,
                headers={
                    "Authorization": f"OAuth {self.target.access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                    "Content-Type": "application/octet-stream",
                },
                timeout=600,
            )
    
        if not resp.ok:
            raise PlatformError(f"Story upload failed: {resp.text}")
    
        # 3. FINISH
        finish = self._post(
            f"{self.target.page_id}/video_stories",
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "access_token": self.target.access_token,
            },
        )
    
        if not finish.get("success"):
            raise PlatformError(f"Story finish failed: {finish}")
    
        return str(video_id)
    # ------------------------------------------------------------------
    # MAIN publish()
    # ------------------------------------------------------------------

    def publish(self, post: SocialPost):

        post_link_in_first_comment = bool(
            getattr(self.target, "post_link_in_first_comment", False)
        )

        comment_fail_is_fatal = bool(
            getattr(self.target, "comment_fail_is_fatal", False)
        )

        video_path = (
            getattr(post, "generated_video_path", "")
            or getattr(post, "video_path", "")
            or ""
        ).strip()

        image_url = self._normalize_public_image_url(
            getattr(post, "image_url", "") or ""
        )

        generated_image_path = (
            getattr(post, "generated_image_path", "") or ""
        ).strip()

        fb_post_id = None
        reel_id = None
        first_comment_id = None

        # --------------------------------------------------------------
        # Timeline post first
        # --------------------------------------------------------------

        try:
            if image_url:
                fb_post_id = self._create_photo_post_from_url(post, image_url)
                print(f"INFO: Timeline image post created: {fb_post_id}")

            elif generated_image_path:
                fb_post_id = self._create_photo_post_from_file(
                    post,
                    generated_image_path,
                )
                print(f"INFO: Timeline local image post created: {fb_post_id}")

            else:
                fb_post_id = self._create_feed_post(post)
                print(f"INFO: Timeline text post created: {fb_post_id}")

        except Exception as e:
            print(f"ERROR: Timeline post failed: {e}")

        # --------------------------------------------------------------
        # Link comment
        # --------------------------------------------------------------

        if fb_post_id and post_link_in_first_comment and post.link:
            try:
                first_comment_id = self._post_first_comment(
                    fb_post_id,
                    post.link,
                )
                print(f"INFO: Link comment added: {first_comment_id}")

            except Exception as exc:
                if comment_fail_is_fatal:
                    raise
                print(f"WARNING: Link comment failed: {exc}")

        # --------------------------------------------------------------
        # Reel upload
        # --------------------------------------------------------------

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
                print(f"WARNING: Reel upload failed: {e}")

        return SimpleNamespace(
            remote_post_id=fb_post_id,
            reel_id=reel_id,
            first_comment_id=first_comment_id,
        )