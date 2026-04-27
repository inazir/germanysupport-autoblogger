# social/cli.py
from __future__ import annotations

import argparse
import json
import sys

from social.config import get_social_targets, resolve_target_keys
from social.models import SocialPost
from social.publisher import publish_to_targets
from social.store import SocialStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic social publisher")
    parser.add_argument("--external-id", required=True)
    parser.add_argument("--content-type", default="article", choices=["article", "deal", "guide", "news"])
    parser.add_argument("--title", required=True)
    parser.add_argument("--link", required=True)
    parser.add_argument("--summary")
    parser.add_argument("--image-url")
    parser.add_argument("--merchant")
    parser.add_argument("--promo-text")
    parser.add_argument("--old-price")
    parser.add_argument("--new-price")
    parser.add_argument("--coupon-code")
    parser.add_argument("--language", default="de")
    parser.add_argument("--hashtags")
    parser.add_argument("--wp-post-id", type=int)
    parser.add_argument("--category-label")
    parser.add_argument("--generate-image", action="store_true")
    parser.add_argument("--generated-image-public-url")

    # --- Video arguments (added for Reels support) ---
    # --generate-video: tells publisher.py to attempt video generation
    #   (not used here — generation happens upstream in share_existing_articles.py
    #    before this CLI is called, but the flag is kept for forward compatibility)
    parser.add_argument(
        "--generate-video",
        action="store_true",
        help="Flag: a video was requested for this post",
    )
    # --generated-video-path: absolute path to the already-generated .mp4 file.
    #   share_existing_articles.py generates the video, then passes the path here
    #   so publisher.py / facebook.py can upload it without regenerating.
    parser.add_argument(
        "--generated-video-path",
        default="",
        help="Absolute path to a pre-generated video file (mp4)",
    )
    # --generated-video-public-url: the public HTTPS URL for the video file,
    #   constructed from SOCIAL_VIDEO_PUBLIC_BASE_URL in share_existing_articles.py.
    parser.add_argument(
        "--generated-video-public-url",
        default="",
        help="Public HTTPS URL for the pre-generated video",
    )

    parser.add_argument("--targets", default="all")
    parser.add_argument("--db-path", default="deals_engine/data/deals.sqlite")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = get_social_targets()
    if not targets:
        raise RuntimeError("No social targets configured. Set SOCIAL_TARGETS in .env")

    target_keys = resolve_target_keys(args.targets, list(targets.keys()))
    post = SocialPost(
        external_id=args.external_id,
        content_type=args.content_type,
        title=args.title,
        link=args.link,
        summary=args.summary,
        image_url=args.image_url,
        merchant=args.merchant,
        promo_text=args.promo_text,
        old_price=args.old_price,
        new_price=args.new_price,
        coupon_code=args.coupon_code,
        language=args.language,
        hashtags=args.hashtags,
        wp_post_id=args.wp_post_id,
        category_label=args.category_label,
        generate_image=args.generate_image,
        generated_image_public_url=args.generated_image_public_url or None,
        # Video fields — publisher.py and facebook.py read these off the post object
        generate_video=args.generate_video,
        generated_video_path=args.generated_video_path or None,
        generated_video_public_url=args.generated_video_public_url or None,
    )

    store = SocialStore(args.db_path)
    result = publish_to_targets(post, targets, target_keys, store, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
