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

    fallback_tags = [
        "#GermanySupport",
        "#GermanyLife",
        "#ExpatsInGermany",
        "#GermanyGuide",
        "#GermanyTips",
    ]

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""
You create short, useful social media captions and relevant hashtags for GermanySupport.de.

Task:
Based on the article title and excerpt, return:
1. a short English caption
2. a list of relevant hashtags

Rules for caption:
- English only
- 2 to 4 short lines
- Natural, useful, trustworthy tone
- Not salesy
- No URL
- Do not mention "first comment"
- Under 260 characters if possible

Rules for hashtags:
- English only
- 6 to 10 hashtags
- Relevant to the specific topic
- Mix broad + niche hashtags
- No spammy tags
- No duplicate hashtags
- Return hashtags with leading #

Return ONLY valid JSON in this format:
{{
  "caption": "text here",
  "hashtags": ["#TagOne", "#TagTwo", "#TagThree"]
}}

Article title:
{clean_title}

Article excerpt:
{clean_excerpt}
""".strip()

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

        if not isinstance(hashtags, list):
            hashtags = []

        hashtags = [normalize_hashtag(x) for x in hashtags]
        hashtags = [x for x in hashtags if x]

        seen = set()
        unique_hashtags = []
        for tag in hashtags:
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                unique_hashtags.append(tag)

        if not caption:
            caption = fallback_caption or clean_title

        if not unique_hashtags:
            unique_hashtags = fallback_tags

        caption = re.sub(r"\n{3,}", "\n\n", caption).strip()
        return caption, unique_hashtags

    except Exception as exc:
        print(f"WARNING: Claude caption/hashtag generation failed: {exc}")
        return fallback_caption or clean_title, fallback_tags


def get_selected_target_keys(all_targets: dict, requested: str | None = None) -> list[str]:
    raw = (requested or SOCIAL_EXISTING_TARGETS or "").strip()
    if not raw or raw.lower() == "all":
        return list(all_targets.keys())

    keys = [x.strip() for x in raw.split(",") if x.strip()]
    return [k for k in keys if k in all_targets]


def is_english_post(post: dict) -> bool:
    lang = (post.get("lang") or "").strip().lower()
    if lang:
        return lang == "en"

    link = (post.get("link") or "").strip().lower()
    if "/de/" in link or link.endswith("/de"):
        return False

    slug = (post.get("slug") or "").strip().lower()
    if slug.endswith("-de"):
        return False

    title = clean_html(post.get("title", {}).get("rendered", "")).lower()
    german_markers = {
        " wie ",
        " für ",
        " und ",
        " in deutschland ",
        " erklärung ",
        " leitfaden ",
        " vergleich ",
        " schritt ",
    }
    padded_title = f" {title} "
    if any(marker in padded_title for marker in german_markers):
        return False

    return True


def select_platform_hashtags(all_hashtags: List[str], platform: str) -> List[str]:
    if platform == "instagram":
        return all_hashtags[:8]
    if platform == "facebook":
        return all_hashtags[:3]
    return all_hashtags[:5]


def build_social_post(
    wp_post: dict,
    caption: str,
    all_hashtags: List[str],
    target_key: str,
    platform: str,
) -> SocialPost:
    title = clean_html(wp_post["title"]["rendered"])
    selected_tags = select_platform_hashtags(all_hashtags, platform)
    hashtags_text = " ".join(selected_tags).strip()
    
    return SocialPost(
        external_id=f"wp:{wp_post['id']}:{target_key}",
        content_type="article",
        title=title,
        summary=caption,
        hashtags=hashtags_text or None,
        link=wp_post["link"],
        language="en",
        generate_image=True,
        wp_post_id=wp_post["id"],
    )


def main(
    dry_run: bool = False,
    target_names: str | None = None,
    only_english: bool | None = None,
):
    if only_english is None:
        only_english = SOCIAL_EXISTING_ONLY_ENGLISH

    print("Fetching posts...")
    posts = fetch_posts(limit=200, language="en" if only_english else None)

    if not posts:
        print("No posts found")
        return

    # Extra safeguard in case lang filter is ignored by the site/plugin.
    if only_english:
        posts = [p for p in posts if is_english_post(p)]

    if not posts:
        print("No eligible posts found after filtering")
        return

    targets = get_social_targets()
    if not targets:
        print("No social targets configured")
        return

    target_keys = get_selected_target_keys(targets, target_names)
    if not target_keys:
        print("No valid selected targets found")
        return

    print(f"Selected targets: {', '.join(target_keys)}")
    print(f"Only English posts: {only_english}")

    store = SocialStore(SOCIAL_DB_PATH)

    candidates = []
    for p in posts:
        if any(not store.already_posted(t, f"wp:{p['id']}:{t}") for t in target_keys):
            candidates.append(p)

    if not candidates:
        print("No fresh posts available for the selected targets")
        return

    selected = random.choice(candidates)
    title = clean_html(selected["title"]["rendered"])
    excerpt = clean_html(selected.get("excerpt", {}).get("rendered", ""))

    print(f"Selected post: {title}")
    print(f"Selected link: {selected['link']}")
    print(f"Selected lang: {selected.get('lang')}")

    caption, hashtags = generate_caption_and_hashtags(title, excerpt)
    print(f"Generated caption: {caption}")
    print(f"Generated hashtags: {' '.join(hashtags)}")

    aggregate = {"posted": [], "skipped": [], "failed": []}

    for target_key in target_keys:
        target = targets[target_key]

        social_post = build_social_post(
            wp_post=selected,
            caption=caption,
            all_hashtags=hashtags,
            target_key=target_key,
            platform=target.platform,
        )

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

    print("RESULT:", aggregate)


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

    only_english = None
    if args.only_english:
        only_english = True
    if args.all_languages:
        only_english = False

    main(
        dry_run=args.dry_run,
        target_names=args.targets,
        only_english=only_english,
    )