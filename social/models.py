from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SocialPost:
    external_id: str
    content_type: str
    title: str
    link: str
    summary: Optional[str] = None
    image_url: Optional[str] = None
    merchant: Optional[str] = None
    promo_text: Optional[str] = None
    old_price: Optional[str] = None
    new_price: Optional[str] = None
    coupon_code: Optional[str] = None
    language: str = "de"
    hashtags: Optional[str] = None
    wp_post_id: Optional[int] = None
    category_label: Optional[str] = None
    generate_image: bool = False
    generated_image_path: Optional[str] = None
    generated_image_public_url: Optional[str] = None


@dataclass
class SocialTarget:
    key: str
    platform: str
    enabled: bool
    name: str
    access_token: str
    api_version: str = "v25.0"
    page_id: Optional[str] = None
    ig_business_account_id: Optional[str] = None
    allowed_content_types: List[str] = field(default_factory=lambda: ["article", "deal"])
    post_link_in_first_comment: bool = False
    comment_fail_is_fatal: bool = False
    require_image: bool = False
    template: str = "default"
    image_style: str = "main_brand"
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    max_caption_chars: Optional[int] = None
    skip_if_image_generation_fails: bool = False
    publish_story: bool = False
