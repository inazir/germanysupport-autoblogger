import sqlite3
from .config import DB_PATH


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            language TEXT NOT NULL,
            merchant TEXT NOT NULL,
            title TEXT NOT NULL,
            dedupe_hash TEXT NOT NULL,
            category TEXT,
            old_price REAL,
            new_price REAL,
            currency TEXT,
            promo_text TEXT,
            internal_url TEXT,
            affiliate_url TEXT,
            product_url TEXT,
            image_url TEXT,
            availability TEXT,
            starts_at TEXT,
            ends_at TEXT,
            status TEXT DEFAULT 'new',
            score INTEGER DEFAULT 0,
            wp_post_id INTEGER,
            first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, external_id, language)
        )
        '''
    )
    conn.commit()
    conn.close()


def has_dedupe_hash(dedupe_hash: str, language: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM deals WHERE dedupe_hash = ? AND language = ? LIMIT 1",
        (dedupe_hash, language),
    ).fetchone()
    conn.close()
    return row is not None


def upsert_deal(item, dedupe_hash: str, publish_status: str):
    conn = get_conn()
    conn.execute(
        '''
        INSERT INTO deals (
            source, external_id, language, merchant, title, dedupe_hash,
            category, old_price, new_price, currency, promo_text,
            internal_url, affiliate_url, product_url, image_url,
            availability, starts_at, ends_at,
            status, score, wp_post_id, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(source, external_id, language)
        DO UPDATE SET
            merchant = excluded.merchant,
            title = excluded.title,
            dedupe_hash = excluded.dedupe_hash,
            category = excluded.category,
            old_price = excluded.old_price,
            new_price = excluded.new_price,
            currency = excluded.currency,
            promo_text = excluded.promo_text,
            internal_url = excluded.internal_url,
            affiliate_url = excluded.affiliate_url,
            product_url = excluded.product_url,
            image_url = excluded.image_url,
            availability = excluded.availability,
            starts_at = excluded.starts_at,
            ends_at = excluded.ends_at,
            status = excluded.status,
            score = excluded.score,
            wp_post_id = excluded.wp_post_id,
            last_seen_at = CURRENT_TIMESTAMP
        ''',
        (
            item.source,
            item.external_id,
            item.language,
            item.merchant,
            item.title,
            dedupe_hash,
            item.category,
            item.old_price,
            item.new_price,
            item.currency,
            item.promo_text,
            item.internal_url,
            getattr(item, "affiliate_url", None),
            item.product_url,
            getattr(item, "image_url", None),
            getattr(item, "availability", None),
            getattr(item, "starts_at", None),
            getattr(item, "ends_at", None),
            publish_status,
            item.score,
            item.wp_post_id,
        ),
    )
    conn.commit()
    conn.close()