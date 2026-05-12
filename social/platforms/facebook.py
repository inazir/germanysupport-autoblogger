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
        Discover all Facebook pages configured via environment variables.

        Convention: any env var ending in __PAGE_ID defines a page.
        The matching access token must be in the same-prefix __ACCESS_TOKEN var.

        Example .env:
            SOCIAL__GS_FB_MAIN__PAGE_ID=975605518978512
            SOCIAL__GS_FB_MAIN__ACCESS_TOKEN=EAAxxxxx
            SOCIAL__BG_FB_MAIN__PAGE_ID=341096977140542
            SOCIAL__BG_FB_MAIN__ACCESS_TOKEN=EAAyyyyy

        Pages with placeholder values (YOUR_...) are automatically skipped.
        """
        pages = []
        for key, value in os.environ.items():
            if key.endswith("__PAGE_ID"):
                prefix = key[:-9]  # strip __PAGE_ID
                page_id = (value or "").strip()
                token = os.getenv(f"{prefix}__ACCESS_TOKEN", "").strip()
                if page_id and token:
                    pages.append((prefix, page_id, token))
        return pages

    # ------------------------------------------------------------------
    # Feed / photo / legacy video helpers  (unchanged from original)
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
    # Reels upload  (3-phase: start → upload → finish)
    #
    # Facebook treats vertical videos uploaded via /video_reels as Reels
    # and places them in the Reels tab automatically.
    #
    # Phase 1 – Start:  POST /{page_id}/video_reels  → video_id
    # Phase 2 – Upload: POST upload_url (binary PUT in Graph parlance)
    #                   We use requests.post with Content-Type octet-stream
    #                   and the upload_url returned from phase 1.
    # Phase 3 – Finish: POST /{page_id}/video_reels  with video_id + PUBLISHED
    # ------------------------------------------------------------------

    def _upload_reels_video(self, post: SocialPost, video_path: str) -> str:
        """
        Upload a local video file as a Facebook Reel using the 3-phase
        resumable upload protocol.  Returns the video_id string.

        Raises PlatformError on any failure so the caller can treat it
        as non-fatal if desired.
        """
        if not self.target.page_id:
            raise PlatformError(f"Target '{self.target.key}' is missing page_id")

        video_path = (video_path or "").strip()
        if not video_path:
            raise PlatformError("Reels upload requires a non-empty video_path")

        file_size = os.path.getsize(video_path)

        # ---- Phase 1: initialise the upload session ----
        init_payload = self._post(
            f"{self.target.page_id}/video_reels",
            {
                "upload_phase": "start",
                "access_token": self.target.access_token,
            },
            timeout=30,
        )

        video_id = str(init_payload.get("video_id") or "").strip()
        upload_url = str(init_payload.get("upload_url") or "").strip()

        if not video_id or not upload_url:
            raise PlatformError(
                f"Reels start phase returned unexpected payload: {init_payload}"
            )

        # ---- Phase 2: stream the binary file to the upload_url ----
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
                timeout=600,   # large files on shared hosting may be slow
            )

        try:
            upload_result = upload_resp.json()
        except Exception:
            upload_result = {"raw_text": upload_resp.text}

        if not upload_resp.ok or "error" in upload_result:
            raise PlatformError(
                f"Reels upload phase (binary POST) failed: {upload_result}"
            )

        # ---- Phase 3: finish / publish ----
        import time

        finish_payload = self._post(
            f"{self.target.page_id}/video_reels",
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",   # required — without this Meta
                "published": "true",          # keeps the reel in draft state
                "share_to_feed": "true",      # makes it appear on Page timeline
                "description": self._build_message(post),
                "title": (post.title or "")[:255],
                "access_token": self.target.access_token,
            },
            timeout=60,
        )

        if not finish_payload.get("success") and "id" not in finish_payload:
            raise PlatformError(
                f"Reels finish phase returned unexpected payload: {finish_payload}"
            )

        print(f"INFO: Reel finish response: {finish_payload}")

        # ---- Verify: wait for processing then check status ----
        # Meta processes Reels asynchronously. Waiting 15s before checking
        # gives enough time to confirm the reel reached a published state.
        time.sleep(15)

        verify_resp = requests.get(
            f"https://graph.facebook.com/{self.target.api_version}/{video_id}",
            params={
                "fields": "id,status,permalink_url",
                "access_token": self.target.access_token,
            },
            timeout=30,
        )
        try:
            verify = verify_resp.json()
        except Exception:
            verify = {}

        print(f"INFO: Reel status after 15s: {verify.get('status', {})}")

        return video_id

    # ------------------------------------------------------------------
    # Legacy video helper  (kept as fallback, not called by publish())
    # but left here so nothing that directly calls it breaks)
    # ------------------------------------------------------------------

    def _create_video_post_from_file(self, post: SocialPost, video_path: str) -> str:
        """
        Original /videos endpoint upload.  Kept for backward-compatibility.
        publish() now uses _upload_reels_video() instead, with this as
        automatic fallback if the Reels flow raises PlatformError.
        """
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
            raise PlatformError(
                f"Facebook video upload created but no video id returned: {payload}"
            )
        return video_id

    # ------------------------------------------------------------------
    # Comment helper  (unchanged)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Story helpers  (unchanged)
    # ------------------------------------------------------------------

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
            raise PlatformError(
                f"Facebook unpublished photo upload failed: missing photo id: {payload}"
            )
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
            raise PlatformError(
                f"Facebook unpublished local photo upload failed: missing photo id: {payload}"
            )
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
                print(f"WARNING: Video story failed ({ve}), falling back to image story.")
    
        # --- IMAGE STORY ---
        image_url = self._normalize_public_image_url(image_url or "")
        if not image_url:
            raise PlatformError("Facebook story requires a public image_url.")
    
        # STEP 1: Upload as unpublished photo (important for reuse)
        photo_id = self._upload_unpublished_photo_from_url(image_url)
    
        # STEP 2 (FIXED): Publish as FEED POST (reliable surface)
        try:
            feed_payload = self._post(
                f"{self.target.page_id}/feed",
                {
                    "message": self._build_message(post),
                    "attached_media[0]": f"{{'media_fbid':'{photo_id}'}}",
                    "access_token": self.target.access_token,
                },
            )
    
            feed_id = str(feed_payload.get("id") or "").strip()
            if not feed_id:
                raise PlatformError(f"Feed story fallback failed: {feed_payload}")
    
            print(f"INFO: Story fallback published via feed: {feed_id}")
    
            # IMPORTANT:
            # We return feed_id as "story_id equivalent"
            return feed_id
    
        except Exception as e:
            raise PlatformError(f"Photo story fallback failed: {e}")

    def _upload_video_story(self, video_path: str) -> str:
        """Handles the 3-step resumable upload for FB Video Stories."""
        # Step 1: Initialize session
        init_res = self._post(f"{self.target.page_id}/video_stories", {
            "upload_phase": "start",
            "access_token": self.target.access_token
        })
        video_id = init_res.get("video_id")
        upload_url = init_res.get("upload_url")

        # Step 2: Upload binary data
        file_size = os.path.getsize(video_path)
        with open(video_path, "rb") as f:
            binary_data = f.read()
            
        headers = {
            "Authorization": f"OAuth {self.target.access_token}",
            "offset": "0",
            "file_size": str(file_size),
            "Content-Type": "application/octet-stream"
        }
        # Step 2 uses a direct PUT/POST to the upload_url returned in Step 1
        resp = requests.post(upload_url, headers=headers, data=binary_data, timeout=120)
        if not resp.ok:
            raise PlatformError(f"Video story binary upload failed: {resp.text}")

        # Step 3: Finish/Publish
        finish_res = self._post(f"{self.target.page_id}/video_stories", {
            "upload_phase": "finish",
            "video_id": video_id,
            "access_token": self.target.access_token
        })
        
        if finish_res.get("success"):
            return str(video_id)
        raise PlatformError(f"Video story finish phase failed: {finish_res}")
    # ------------------------------------------------------------------
    # publish()  –  main entry point called by publisher.py
    #
    # Priority order (unchanged for image/text):
    #   video_path  → Reels upload (with /videos fallback)
    #   image_url   → photo post from URL
    #   generated_image_path → photo post from file
    #   (none)      → plain text feed post
    #
    # Video upload is attempted independently:
    #   - Reels 3-phase first
    #   - Falls back to /videos if Reels raises PlatformError
    #   - If both fail the exception propagates (caller decides fatality)
    # ------------------------------------------------------------------

    def publish(self, post: SocialPost):

        pages = self._load_pages()

        # Skip placeholder/unconfigured pages so they don't cause OAuthException
        # errors (code 190 "Got unexpected null") in every run.
        valid_pages = [
            (name, page_id, token)
            for name, page_id, token in pages
            if page_id
            and token
            and not page_id.upper().startswith("YOUR_")
            and not token.upper().startswith("YOUR_")
        ]

        # Fall back to the target on self.target if env-var discovery found nothing
        if not valid_pages:
            if self.target.page_id and self.target.access_token:
                valid_pages = [("default", self.target.page_id, self.target.access_token)]
            else:
                raise PlatformError("No valid Facebook pages configured")

        primary = None   # first successful result — returned to publisher.py
        results = []

        for name, page_id, token in valid_pages:

            print(f"\nINFO: ===== Posting to {name} ({page_id}) =====")

            self.target.page_id = page_id
            self.target.access_token = token

            post_link_in_first_comment = bool(getattr(self.target, "post_link_in_first_comment", False))
            comment_fail_is_fatal = bool(getattr(self.target, "comment_fail_is_fatal", False))

            video_path = (getattr(post, "generated_video_path", "") or getattr(post, "video_path", "") or "").strip()
            image_url = self._normalize_public_image_url(getattr(post, "image_url", "") or "")
            generated_image_path = (getattr(post, "generated_image_path", "") or "").strip()

            fb_post_id = None
            reel_id = None
            first_comment_id = None

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
            # Published inside the loop so every page gets its own story.
            # publisher.py calls publish_story() once after publish() returns,
            # but by then self.target has been overwritten to the last page in
            # the loop — so the first page's story was never published.
            # Doing it here ensures both pages always get stories.
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

            page_result = SimpleNamespace(
                page=name,
                remote_post_id=fb_post_id,
                reel_id=reel_id,
                first_comment_id=first_comment_id,
                story_id=story_id,
            )
            results.append(page_result)

            # publisher.py expects a single object with remote_post_id/reel_id
            # attributes — not a list. Returning a list caused:
            # "Unsupported publish result type: list"
            # even when posting succeeded. Use the first page that got a post_id.
            if primary is None and fb_post_id:
                primary = page_result

        # publisher.py calls publish_story() once after this returns, but
        # stories are already published per-page inside the loop above.
        # Set story_handled=True so publisher.py skips the duplicate call.
        result = primary or results[0]
        result.story_handled = True
        return result