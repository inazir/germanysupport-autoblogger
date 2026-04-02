from typing import Optional
import hashlib
import re
from .models import DealItem


def normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def build_dedupe_hash(item: DealItem) -> str:
    base = "|".join([
        normalize_text(item.merchant),
        normalize_text(item.title),
        item.language,
        str(item.new_price or ""),
        normalize_text(item.promo_text),
        normalize_text(item.internal_url),
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()
