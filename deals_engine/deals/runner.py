import os
import sqlite3
from pathlib import Path
from typing import List

from .db import init_db, get_conn
from .generator import build_body, build_excerpt, build_post_title
from .models import DealItem
from .normalizer import build_dedupe_hash
from .publisher import WordPressDealPublisher, resolve_category_id
from .scorer import score_deal
from .sources.csv_feed import CsvFeedSource


BASE_DIR = Path(__file__).resolve().parents[1]


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _parse_languages(value: str) -> List[str]:
    value = (value or "both").strip().lower()
    if value == "en":
        return ["en"]
    if value == "de":
        return ["de"]
    return ["en", "de"]


def _slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:180]


def _db_has_language_variant(conn: sqlite3.Connection, dedupe_hash: str, language: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM deals WHERE dedupe_hash = ? AND language = ? LIMIT 1",
        (dedupe_hash, language),
    ).fetchone()
    return row is not None


def _db_insert_variant(
    conn: sqlite3.Connection,
    item: DealItem,
    dedupe_hash: str,
    language: str,
    wp_post_id: int,
    status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO deals (
            source, external_id, merchant, title, dedupe_hash, category,
            old_price, new_price, currency, promo_text, product_url,
            affiliate_url, internal_url, image_url, availability, ends_at,
            wp_post_id, status, language, first_seen_at, last_seen_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
        (
            item.source,
            item.external_id,
            item.merchant,
            item.title,
            dedupe_hash,
            item.category,
            item.old_price,
            item.new_price,
            item.currency,
            item.promo_text,
            item.product_url,
            item.affiliate_url,
            item.internal_url,
            item.image_url,
            item.availability,
            item.ends_at,
            wp_post_id,
            status,
            language,
        ),
    )
    conn.commit()


def ensure_schema() -> None:
    init_db()
    conn = get_conn()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(deals)").fetchall()}
    if "language" not in cols:
        conn.execute("ALTER TABLE deals ADD COLUMN language TEXT")
        conn.commit()
    conn.close()


def main() -> None:
    ensure_schema()

    wp_url = _env("WP_URL")
    wp_user = _env("WP_USER")
    wp_app_pass = _env("WP_APP_PASS")
    category_slug = _env("DEALS_CATEGORY_SLUG", "best-deals")
    default_status = _env("DEALS_DEFAULT_STATUS", "draft")
    language_mode = _env("DEALS_LANGUAGE_MODE", "both")
    min_score = int(_env("DEALS_MIN_SCORE", "10"))
    max_per_run = int(_env("DEALS_MAX_PER_RUN", "20"))
    csv_path = _env("DEALS_CSV_PATH", str(BASE_DIR / "feeds" / "sample_deals.csv"))
    lang_field = _env("DEALS_WP_LANG_FIELD", "lang")

    category_id = resolve_category_id(wp_url, wp_user, wp_app_pass, category_slug)
    publisher = WordPressDealPublisher(
        wp_url=wp_url,
        username=wp_user,
        app_password=wp_app_pass,
        category_id=category_id,
        default_status=default_status,
        lang_field=lang_field,
    )

    source = CsvFeedSource(csv_path)
    items = source.fetch()
    languages = _parse_languages(language_mode)

    conn = get_conn()
    published_count = 0

    for item in items:
        if published_count >= max_per_run:
            break

        if score_deal(item) < min_score:
            continue

        dedupe_hash = build_dedupe_hash(item)

        for language in languages:
            if published_count >= max_per_run:
                break

            if _db_has_language_variant(conn, dedupe_hash, language):
                continue

            title = build_post_title(item, language)
            excerpt = build_excerpt(item, language)
            body = build_body(item, language)

            slug = _slugify(f"{item.title}-{language}-{item.external_id}")
            result = publisher.publish(
                title=title,
                excerpt=excerpt,
                content=body,
                language=language,
                slug=slug,
                status=default_status,
            )

            _db_insert_variant(
                conn=conn,
                item=item,
                dedupe_hash=dedupe_hash,
                language=language,
                wp_post_id=int(result["id"]),
                status=result.get("status", default_status),
            )
            published_count += 1
            print(f"Published {language} draft for: {item.title} (WP ID {result['id']})")

    conn.close()


if __name__ == "__main__":
    main()
