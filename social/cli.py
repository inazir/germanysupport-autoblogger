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
        generated_image_public_url=args.generated_image_public_url,
    )

    store = SocialStore(args.db_path)
    result = publish_to_targets(post, targets, target_keys, store, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
