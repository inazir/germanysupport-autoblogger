"""
social/daily_news/news_fetcher.py

Phase 1: Fetch RSS feeds, filter for Germany relevance, deduplicate.
No external dependencies beyond feedparser (pip install feedparser).
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

# feedparser is the only new dependency
try:
    import feedparser
except ImportError:
    raise ImportError("feedparser is required: pip install feedparser --break-system-packages")


# ---------------------------------------------------------------------------
# Default RSS sources — override via NEWS_RSS_SOURCES in .env
# ---------------------------------------------------------------------------

DEFAULT_RSS_SOURCES = [
    "https://rss.dw.com/xml/rss-en-all",
    "https://www.tagesschau.de/xml/rss2",
    "https://feeds.reuters.com/reuters/worldNews",
    "https://www.spiegel.de/schlagzeilen/index.rss",
]

# ---------------------------------------------------------------------------
# Germany relevance keywords
# ---------------------------------------------------------------------------

GERMANY_KEYWORDS = [
    "germany", "german", "deutschland", "berlin", "munich", "münchen",
    "hamburg", "stuttgart", "frankfurt", "cologne", "düsseldorf",
    "scholz", "bundestag", "bundesrat", "bundeswehr",
    "visa", "immigration", "expat", "residence permit", "aufenthaltserlaubnis",
    "economy", "inflation", "housing", "rent", "miete",
    "transport", "train strike", "deutsche bahn", "db ",
    "jobs", "employment", "unemployment", "arbeitsmarkt",
    "citizenship", "einbürgerung", "naturalisation",
    "kindergeld", "elterngeld", "sozialleistungen",
    "dax", "bundesbank", "ecb", "euro",
]


@dataclass
class NewsItem:
    title: str
    summary: str
    url: str
    source: str          # feed domain, e.g. "dw.com"
    published_at: datetime
    relevance_score: float = 0.0
    dedup_key: str = ""  # set after construction

    def __post_init__(self):
        if not self.dedup_key:
            self.dedup_key = _make_dedup_key(self.title)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_rss_sources() -> List[str]:
    raw = os.getenv("NEWS_RSS_SOURCES", "").strip()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    return DEFAULT_RSS_SOURCES


def _clean_html(text: str) -> str:
    """Strip HTML tags and normalise whitespace."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return " ".join(text.split()).strip()


def _source_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
        # strip www. prefix
        return host.removeprefix("www.")
    except Exception:
        return url


def _parse_date(entry) -> datetime:
    """Parse feedparser's published_parsed or updated_parsed into UTC datetime."""
    for attr in ("published_parsed", "updated_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(tz=timezone.utc)


def _make_dedup_key(title: str) -> str:
    """
    Normalised key for duplicate detection.
    Strips punctuation, lowercases, removes stop words, then hashes.
    Two near-identical headlines should produce the same key.
    """
    stop = {"a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or", "is", "are", "was"}
    text = title.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [w for w in text.split() if w not in stop and len(w) > 2]
    # Use first 6 significant tokens as the key so minor wording differences
    # (e.g. "Germany's economy..." vs "German economy...") still match
    canonical = " ".join(sorted(tokens[:8]))
    return hashlib.md5(canonical.encode()).hexdigest()


def _germany_relevance(title: str, summary: str) -> float:
    """
    Return a relevance score 0.0–1.0.
    Checks title (weighted more) and summary against GERMANY_KEYWORDS.
    """
    text_title = title.lower()
    text_body = (summary or "").lower()
    hits_title = sum(1 for kw in GERMANY_KEYWORDS if kw in text_title)
    hits_body = sum(1 for kw in GERMANY_KEYWORDS if kw in text_body)
    # Title hits count double
    raw = hits_title * 2 + hits_body
    # Cap at 1.0: 3+ keyword hits = max score
    return min(raw / 6.0, 1.0)


def _is_germany_relevant(title: str, summary: str) -> bool:
    """Quick boolean gate — must have at least one keyword match anywhere."""
    combined = (title + " " + (summary or "")).lower()
    return any(kw in combined for kw in GERMANY_KEYWORDS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_news(
    max_fetch: int | None = None,
    min_relevance: float = 0.0,
) -> List[NewsItem]:
    """
    Fetch RSS feeds, filter for Germany relevance, deduplicate, return list
    sorted by (relevance_score DESC, published_at DESC).

    Parameters
    ----------
    max_fetch   : max items to return (default: NEWS_MAX_FETCH env var or 40)
    min_relevance: minimum relevance score 0.0–1.0 (default 0.0 = any match)
    """
    if max_fetch is None:
        max_fetch = int(os.getenv("NEWS_MAX_FETCH", "40"))

    sources = _get_rss_sources()
    seen_keys: set[str] = set()
    items: List[NewsItem] = []

    for feed_url in sources:
        try:
            feed = feedparser.parse(feed_url)
            entries = feed.entries or []
            print(f"  [fetcher] {feed_url} → {len(entries)} entries")
        except Exception as exc:
            print(f"  [fetcher] WARNING: failed to fetch {feed_url}: {exc}")
            continue

        domain = _source_domain(feed_url)

        for entry in entries:
            title = _clean_html(getattr(entry, "title", "")).strip()
            summary = _clean_html(getattr(entry, "summary", "") or getattr(entry, "description", "")).strip()
            url = getattr(entry, "link", "").strip()

            if not title or not url:
                continue

            # Germany relevance gate
            if not _is_germany_relevant(title, summary):
                continue

            # Deduplication
            key = _make_dedup_key(title)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            score = _germany_relevance(title, summary)
            if score < min_relevance:
                continue

            published_at = _parse_date(entry)

            items.append(NewsItem(
                title=title,
                summary=summary[:500],   # cap summary length
                url=url,
                source=domain,
                published_at=published_at,
                relevance_score=score,
                dedup_key=key,
            ))

    # Sort: relevance DESC, then freshness DESC
    items.sort(key=lambda x: (x.relevance_score, x.published_at), reverse=True)

    print(f"  [fetcher] Total after filter+dedup: {len(items)} items")
    return items[:max_fetch]
