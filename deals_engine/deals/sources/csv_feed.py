import csv
from pathlib import Path
from ..models import DealItem
from ..utils import safe_float
from .base import DealSource


class CsvFeedSource(DealSource):
    name = "csv"

    def __init__(self, path: str):
        self.path = Path(path)

    def fetch(self):
        if not self.path.exists():
            raise FileNotFoundError(f"CSV feed not found: {self.path}")

        items = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            required = {"id", "merchant", "title", "category", "internal_url"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Missing CSV columns: {', '.join(sorted(missing))}")

            for row in reader:
                items.append(
                    DealItem(
                        source=self.name,
                        external_id=(row.get("id") or "").strip(),
                        merchant=(row.get("merchant") or "").strip(),
                        title=(row.get("title") or "").strip(),
                        brand=(row.get("brand") or "").strip() or None,
                        category=(row.get("category") or "").strip() or None,
                        old_price=safe_float(row.get("old_price")),
                        new_price=safe_float(row.get("new_price")),
                        currency=(row.get("currency") or "EUR").strip(),
                        promo_text=(row.get("promo_text") or "").strip() or None,
                        product_url=(row.get("product_url") or "").strip() or None,
                        affiliate_url=(row.get("affiliate_url") or "").strip() or None,
                        internal_url=(row.get("internal_url") or "").strip() or None,
                        image_url=(row.get("image_url") or "").strip() or None,
                        availability=(row.get("availability") or "active").strip(),
                        starts_at=(row.get("starts_at") or "").strip() or None,
                        ends_at=(row.get("ends_at") or "").strip() or None,
                    )
                )
        return items
