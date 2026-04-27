from __future__ import annotations

import json
import os
import random
import re
import requests
import anthropic
from typing import List, Tuple

from social.config import get_social_targets
from social.models import SocialPost
from social.publisher import publish_to_targets
from social.store import SocialStore
# NEW: Import the video generator
from social.video_generator import generate_short_video 


WP_URL = os.environ["WP_URL"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_APP_PASS = os.environ["WP_APP_PASS"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_KEY"]

SOCIAL_DB_PATH = os.getenv(
    "SOCIAL_DB_PATH",
    "social/cache/social.db",
)

CLAUDE_MODEL = os.getenv("SOCIAL_CAPTION_MODEL", "claude-sonnet-4-20250514")
CLAUDE_MAX_TOKENS = int(os.getenv("SOCIAL_CAPTION_MAX_TOKENS", "320"))

SOCIAL_EXISTING_TARGETS = os.getenv(
    "SOCIAL_EXISTING_TARGETS",
    "gs_fb_main,gs_ig_main",
).strip()

SOCIAL_EXISTING_ONLY_ENGLISH = os.getenv(
    "SOCIAL_EXISTING_ONLY_ENGLISH",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}


def _headers():
    import base64
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PASS}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def fetch_posts(limit: int = 100, language: str | None = None) -> List[dict]:
    page = 1
    posts = []
    while True:
        params = {
            "per_page": 100,
            "page": page,
            "status": "publish",
            "_fields": "id,title,excerpt,link,categories,date,lang,slug",
        }
        if language:
            params["lang"] = language
        r = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=_headers(),
            params=params,
            timeout=30,
        )
        if r.status_code == 400:
            break
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        posts.extend(data)
        if len(posts) >= limit:
            break
        page += 1
    return posts[:limit]


def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return " ".join(text.split()).strip()


def normalize_hashtag(tag: str) -> str:
    tag = (tag or "").strip()
    if not tag:
        return ""
    if not tag.startswith("#"):
        tag = f"#{tag}"
    tag = re.sub(r"[^#A-Za-z0-9_]", "", tag)
    return tag


def parse_json_safe(raw: str) -> dict | None:
    text = raw.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def generate_caption_and_hashtags(title: str, excerpt: str) -> Tuple[str, List[str]]:
    clean_title = clean_html(title)
    clean_excerpt = clean_html(excerpt)
    fallback_caption = clean_excerpt or clean_title
    if len(fallback_caption) > 180:
        fallback_caption = fallback_caption[:180].rsplit(" ", 1)[0] + "..."
    fallback_tags = ["#GermanySupport", "#GermanyLife", "#ExpatsInGermany"]

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = (
        f"Create a short, engaging social media caption for this article title: {clean_title}. "
        f"Context excerpt: {clean_excerpt}. "
        "Return the response as a JSON object with 'caption' and 'hashtags' (list) keys."
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        data = parse_json_safe(raw) or {}
        caption = str(data.get("caption") or "").strip()
        hashtags = data.get("hashtags") or []
        hashtags = [normalize_hashtag(x) for x in hashtags if x]
        return caption or fallback_caption, hashtags or fallback_tags
    except Exception as exc:
        print(f"WARNING: Claude caption generation failed: {exc}")
        return fallback_caption, fallback_tags


def is_english_post(post: dict) -> bool:
    lang = (post.get("lang") or "").strip().lower()
    if lang:
        return lang == "en"
    link = (post.get("link") or "").strip().lower()
    if "/de/" in link:
        return False
    return True


def select_platform_hashtags(all_hashtags: List[str], platform: str) -> List[str]:
    # Facebook likes fewer tags, Instagram likes more
    limit = 3 if platform == "facebook" else 10
    return all_hashtags[:limit]


def build_social_post(
    wp_post: dict, 
    caption: str, 
    all_hashtags: List[str], 
    target_key: str, 
    platform: str
) -> SocialPost:
    title = clean_html(wp_post["title"]["rendered"])
    selected_tags = select_platform_hashtags(all_hashtags, platform)
    hashtags_str = " ".join(selected_tags)

    return SocialPost(
        external_id=f"wp:{wp_post['id']}:{target_key}",
        content_type="article",
        title=title,
        link=wp_post["link"],
        summary=caption,
        hashtags=hashtags_str,
        wp_post_id=wp_post["id"],
        generate_image=True,
        generate_video=True,  # Enable video generation for the newer pipeline
    )


def main(dry_run: bool = False, target_names: str | None = None, only_english: bool | None = None):
    if only_english is None:
        only_english = SOCIAL_EXISTING_ONLY_ENGLISH

    print(f"Fetching posts (only_english={only_english})...")
    posts = fetch_posts(limit=200, language="en" if only_english else None)
    
    if only_english:
        posts = [p for p in posts if is_english_post(p)]
    
    targets = get_social_targets()
    target_keys = [x.strip() for x in (target_names or SOCIAL_EXISTING_TARGETS).split(",") if x.strip()]
    
    store = SocialStore(SOCIAL_DB_PATH)
    
    # Filter for posts not yet sent to at least one of our targets
    candidates = []
    for p in posts:
        is_fresh = False
        for t_key in target_keys:
            ext_id = f"wp:{p['id']}:{t_key}"
            if not store.already_posted(t_key, ext_id):
                is_fresh = True
                break
        if is_fresh:
            candidates.append(p)

    if not candidates:
        print("No fresh posts available to share.")
        return

    selected = random.choice(candidates)
    print(f"Selected post: {selected['title']['rendered']} (ID: {selected['id']})")

    # 1. Generate content via Claude
    caption, hashtags = generate_caption_and_hashtags(
        selected["title"]["rendered"], 
        selected.get("excerpt", {}).get("rendered", "")
    )

    aggregate = {"posted": [], "skipped": [], "failed": []}

    for target_key in target_keys:
        if target_key not in targets:
            continue
        target = targets[target_key]
        
        ext_id = f"wp:{selected['id']}:{target_key}"
        if store.already_posted(target_key, ext_id):
            print(f"Skipping {target_key}: already posted.")
            continue

        # 2. Build the Post Object
        social_post = build_social_post(
            wp_post=selected,
            caption=caption,
            all_hashtags=hashtags,
            target_key=target_key,
            platform=target.platform,
        )

        # 3. Trigger Video Generation (NEW)
        if social_post.generate_video:
            try:
                print(f"LOG: Generating video for Reel/Story: {social_post.title}")
                # This uses the summary (caption) created by Claude above
                video_path = generate_short_video(social_post)
                social_post.generated_video_path = video_path
                print(f"LOG: Video saved at: {video_path}")
            except Exception as v_err:
                print(f"ERROR: Video generation failed: {v_err}")
                # We continue anyway; the publisher will fallback to images if video fails

        # 4. Publish
        result = publish_to_targets(
            post=social_post,
            targets=targets,
            target_keys=[target_key],
            store=store,
            dry_run=dry_run,
        )

        aggregate["posted"].extend(result.get("posted", []))
        aggregate["skipped"].extend(result.get("skipped", []))
        aggregate["failed"].extend(result.get("failed", []))

    print("SUMMARY RESULT:", aggregate)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--targets",
        default=None,
        help='Comma-separated targets, e.g. "gs_fb_main,gs_ig_main"',
    )
    parser.add_argument(
        "--only-english",
        action="store_true",
        help="Only pick English posts",
    )
    parser.add_argument(
        "--all-languages",
        action="store_true",
        help="Allow posts of any language",
    )

    args = parser.parse_args()
    
    main(
        dry_run=args.dry_run, 
        target_names=args.targets, 
        only_english=False if args.all_languages else (args.only_english or None)
    )