from typing import Optional
from dataclasses import dataclass
from typing import Optional


@dataclass
class DealItem:
    source: str
    external_id: str
    merchant: str
    title: str
    language: str = "en"
    brand: Optional[str] = None
    category: Optional[str] = None
    old_price: Optional[float] = None
    new_price: Optional[float] = None
    currency: str = "EUR"
    promo_text: Optional[str] = None
    product_url: Optional[str] = None
    affiliate_url: Optional[str] = None
    internal_url: Optional[str] = None
    image_url: Optional[str] = None
    availability: str = "active"
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    wp_post_id: Optional[int] = None
    score: int = 0
