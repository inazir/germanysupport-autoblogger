from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


class SocialStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS social_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_key TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    content_type TEXT,
                    wp_post_id INTEGER,
                    remote_post_id TEXT,
                    first_comment_id TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(target_key, external_id)
                )
                """
            )
            conn.commit()

    def already_posted(self, target_key: str, external_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM social_deliveries
                WHERE target_key = ? AND external_id = ? AND status = 'posted'
                LIMIT 1
                """,
                (target_key, external_id),
            ).fetchone()
            return row is not None

    def mark_posted(
        self,
        target_key: str,
        platform: str,
        external_id: str,
        content_type: str,
        wp_post_id: Optional[int],
        remote_post_id: Optional[str],
        first_comment_id: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO social_deliveries (
                    target_key, platform, external_id, content_type, wp_post_id,
                    remote_post_id, first_comment_id, status, error_message, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'posted', NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(target_key, external_id) DO UPDATE SET
                    platform = excluded.platform,
                    content_type = excluded.content_type,
                    wp_post_id = excluded.wp_post_id,
                    remote_post_id = excluded.remote_post_id,
                    first_comment_id = excluded.first_comment_id,
                    status = 'posted',
                    error_message = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (target_key, platform, external_id, content_type, wp_post_id, remote_post_id, first_comment_id),
            )
            conn.commit()

    def mark_failed(
        self,
        target_key: str,
        platform: str,
        external_id: str,
        content_type: str,
        wp_post_id: Optional[int],
        error_message: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO social_deliveries (
                    target_key, platform, external_id, content_type, wp_post_id,
                    remote_post_id, first_comment_id, status, error_message, updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, NULL, 'failed', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(target_key, external_id) DO UPDATE SET
                    platform = excluded.platform,
                    content_type = excluded.content_type,
                    wp_post_id = excluded.wp_post_id,
                    status = 'failed',
                    error_message = excluded.error_message,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (target_key, platform, external_id, content_type, wp_post_id, error_message[:2000]),
            )
            conn.commit()
