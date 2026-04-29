from __future__ import annotations

import json
import os
import random
import re
import requests
from openai import OpenAI
from typing import List, Tuple

from social.config import get_social_targets
from social.models import SocialPost
from social.publisher import publish_to_targets
from social.store import SocialStore
from social.video_generator import generate_short_video 


# --- Configuration & Environment ---
WP_URL = os.environ["WP_URL"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_APP_PASS = os.environ["WP_APP_PASS"]

# DeepSeek Configuration (Social & Video Engine)
DEEPSEEK_KEY = os.environ["DEEPSEEK_API_KEY"]
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_MAX_TOKENS = int(os.getenv("SOCIAL_CAPTION_MAX_TOKENS", "320"))

# Initialize DeepSeek Client once (Uses OpenAI-compatible library)
client = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")

SOCIAL_DB_PATH = os.getenv("SOCIAL_DB_PATH", "social/cache/social.db")

SOCIAL_EXISTING_TARGETS = os.getenv(
    "SOCIAL_EXISTING_TARGETS",
    "gs_fb_main,gs_ig_main",
).strip()

SOCIAL_EXISTING_ONLY_ENGLISH = os.getenv(
    "SOCIAL_EXISTING_ONLY_ENGLISH",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}


# --- Helper Functions ---

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
    if not tag: return ""
    if not tag.startswith("#"): tag = f"#{tag}"
    tag = re.sub(r"[^#A-Za-z0-9_]", "", tag)
    return tag


def generate_caption_and_hashtags(title: str, excerpt: str) -> Tuple[str, List[str]]:
    """Uses DeepSeek-V4-Pro to generate high-speed, low-cost social media content."""
    clean_title = clean_html(title)
    clean_excerpt = clean_html(excerpt)
    
    prompt = (
        f"Create a short, engaging social media caption for this article: {clean_title}. "
        f"Context: {clean_excerpt}. "
        "Return a JSON object with 'caption' (string) and 'hashtags' (list of strings)."
    )

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={'type': 'json_object'},
            max_tokens=DEEPSEEK_MAX_TOKENS
        )
        data = json.loads(response.choices[0].message.content)
        caption = str(data.get("caption") or "").strip()
        hashtags = [normalize_hashtag(x) for x in data.get("hashtags", []) if x]
        return caption, hashtags
    except Exception as exc:
        print(f"WARNING: DeepSeek caption generation failed: {exc}")
        return clean_title, ["#GermanySupport"]


def is_english_post(post: dict) -> bool:
    lang = (post.get("lang") or "").strip().lower()
    if lang:
        return lang == "en"
    link = (post.get("link") or "").strip().lower()
    return "/de/" not in link


def select_platform_hashtags(all_hashtags: List[str], platform: str) -> List[str]:
    # Custom limits per platform
    limit = 3 if platform == "facebook" else 10
    return all_hashtags[:limit]


def build_social_post(wp_post: dict, caption: str, all_hashtags: List[str], target_key: str, platform: str) -> SocialPost:
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
        generate_video=True, 
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
    
    candidates = []
    for p in posts:
        is_fresh = False
        for t_key in target_keys:
            ext_id = f"wp:{p['id']}:{t_key}"
            if not store.already_posted(t_key, ext_id):
                is_fresh = True
                break
        if is_fresh: candidates.append(p)

    if not candidates:
        print("No fresh posts available to share.")
        return

    selected = random.choice(candidates)
    print(f"Selected post: {selected['title']['rendered']} (ID: {selected['id']})")

    # 1. Generate content via DeepSeek (Saving budget here)
    caption, hashtags = generate_caption_and_hashtags(
        selected["title"]["rendered"], 
        selected.get("excerpt", {}).get("rendered", "")
    )

    aggregate = {"posted": [], "skipped": [], "failed": []}

    for target_key in target_keys:
        if target_key not in targets: continue
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

        # 3. Trigger Video Generation
        if social_post.generate_video:
            try:
                print(f"LOG: Generating video for Reel/Story: {social_post.title}")
                video_path = generate_short_video(social_post)
                social_post.generated_video_path = video_path
                print(f"LOG: Video saved at: {video_path}")
            except Exception as v_err:
                print(f"ERROR: Video generation failed: {v_err}")

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
    parser.add_argument("--targets", default=None)
    parser.add_argument("--only-english", action="store_true")
    parser.add_argument("--all-languages", action="store_true")

    args = parser.parse_args()
    
    main(
        dry_run=args.dry_run, 
        target_names=args.targets, 
        only_english=False if args.all_languages else (args.only_english or None)
    )