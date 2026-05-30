# social/share_viral_posts.py
"""
Experimental viral Facebook content engine for GermanySupport.de.

Generates high-engagement, emotion-driven posts optimized for organic reach:
comments, shares, dwell time, identity-based reactions.

This is a PARALLEL system — it does NOT touch share_random_tips.py or any
existing pipeline. It shares only infrastructure (env loader, publisher,
store, models) and writes to its own DB table (viral_history).

Run modes
---------
    python3 -m social.share_viral_posts              # publish to all enabled targets
    python3 -m social.share_viral_posts --dry-run    # preview, no publish
    python3 -m social.share_viral_posts --targets gs_fb_main
    python3 -m social.share_viral_posts --provider anthropic
    python3 -m social.share_viral_posts --provider deepseek
    python3 -m social.share_viral_posts --theme immigrant_reality

.env variables (all optional — sensible defaults provided)
----------------------------------------------------------
    VIRAL_LLM_PROVIDER=anthropic       # "anthropic" or "deepseek" (default: anthropic)
    VIRAL_LLM_LANGUAGE=en              # "en" (default: en — FB audience is EN)
    VIRAL_COOLDOWN_DAYS=14             # repeat window per theme (default: 14)
    VIRAL_SITE_URL=https://germanysupport.de
    VIRAL_POST_COMMENTS=true           # auto-post self-comments (default: true)
    VIRAL_MAX_COMMENTS=5               # how many self-comments to post (default: 5)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
from social.env_loader import load_env_file as _load_env

_load_env(Path(__file__).resolve().parents[1] / ".env")

from social.config import get_social_targets, resolve_target_keys
from social.models import SocialPost
from social.publisher import publish_to_targets
from social.store import SocialStore

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [viral] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("viral")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SOCIAL_DIR = Path(__file__).resolve().parent
_DB_PATH = str(_SOCIAL_DIR / "cache" / "social.db")

# ---------------------------------------------------------------------------
# Content theme library
#
# Each theme is a dict:
#   name          → internal key
#   hook_style    → tone/angle instruction for the LLM
#   audience      → who this resonates with
#   topics        → list of (image_title, prompt_hint) pairs
#
# Themes are chosen randomly; within a theme, a topic is chosen avoiding
# recent repeats (viral_history table).
# ---------------------------------------------------------------------------

class ThemeEntry(NamedTuple):
    image_title: str   # short text shown on branded image (≤6 words)
    prompt_hint: str   # topic passed to LLM


THEMES: Dict[str, Dict] = {

    "immigrant_reality": {
        "hook_style": "raw emotional honesty — no filter, no sugarcoating",
        "audience": "immigrants and expats in Europe",
        "topics": [
            ThemeEntry("Nobody Warns You About This", "the emotional reality of moving abroad that nobody talks about before you leave"),
            ThemeEntry("Year 1 vs Year 3 Abroad", "how your mindset and priorities change dramatically after living abroad for 3+ years"),
            ThemeEntry("The Loneliness Nobody Posts", "why immigrants feel lonely even when surrounded by people, and why social media hides this"),
            ThemeEntry("Home Feels Foreign Now", "the strange feeling of visiting your home country after years abroad and no longer fitting in"),
            ThemeEntry("The Invisible Integration Tax", "the hidden psychological cost immigrants pay just to function normally in a new country"),
            ThemeEntry("When Your Accent Costs You", "how accent and language barriers affect job opportunities and social treatment in Germany"),
        ],
    },

    "germany_reality": {
        "hook_style": "wry observation — the gap between expectation and reality",
        "audience": "expats and newcomers in Germany",
        "topics": [
            ThemeEntry("Germany Lied to Me", "the biggest surprises about daily life in Germany that no guide prepares you for"),
            ThemeEntry("Bureaucracy Almost Broke Me", "a relatable, funny-but-painful story about German bureaucracy overwhelming a newcomer"),
            ThemeEntry("Germans Don't Small Talk", "why German social culture feels cold to newcomers and how to actually make friends"),
            ThemeEntry("Cashonly Germany in 2025", "why Germany still relies heavily on cash and how this surprises modern expats"),
            ThemeEntry("Quiet Hours Are Not Optional", "the reality of strict noise rules in Germany and the culture shock for newcomers"),
            ThemeEntry("The Mietvertrag Trap", "hidden clauses in German rental contracts that catch expats off guard"),
        ],
    },

    "money_mindset": {
        "hook_style": "financial wake-up call — slightly uncomfortable truths about money",
        "audience": "young adults, immigrants, and employees in Europe",
        "topics": [
            ThemeEntry("Salary Trap Is Real", "why earning a good salary in Germany still leaves many feeling financially stuck"),
            ThemeEntry("Your Job Is a Subscription", "how employment is like a subscription — and why most people never cancel even when unhappy"),
            ThemeEntry("Inflation Ate Your Raise", "how rising costs in Germany have made salary increases feel meaningless"),
            ThemeEntry("The Renter Wealth Gap", "why long-term renting in Germany instead of buying is costing immigrants wealth"),
            ThemeEntry("Stop Saving, Start Investing", "why keeping money in a German savings account is actually losing you money every year"),
            ThemeEntry("The 40 Year Work Trap", "why the traditional work-until-65 model is increasingly broken for today's young workers"),
        ],
    },

    "ai_opportunity": {
        "hook_style": "practical opportunity — specific and actionable, not hype",
        "audience": "employees, freelancers, and side-hustle seekers",
        "topics": [
            ThemeEntry("AI Side Income Is Real", "specific realistic ways people are earning €500-2000/month using AI tools in 2025"),
            ThemeEntry("Your Job vs AI Timeline", "which job categories in Germany are most vulnerable to AI replacement in the next 5 years"),
            ThemeEntry("Faceless Business Works", "how people are building profitable content businesses online without showing their face"),
            ThemeEntry("AI Tools Most Skip", "underused AI tools that could save immigrants 5+ hours per week on German bureaucracy and admin"),
            ThemeEntry("Freelance + AI = Leverage", "how adding AI tools to freelance work in Germany dramatically increases hourly earnings"),
            ThemeEntry("The Content Income Shift", "how the creator economy is now a viable income path even for immigrants with accents"),
        ],
    },

    "europe_cost_reality": {
        "hook_style": "honest comparison — no idealization",
        "audience": "immigrants choosing or reconsidering European cities",
        "topics": [
            ThemeEntry("Germany vs Netherlands Cost", "honest cost of living comparison between Germany and Netherlands for immigrants in 2025"),
            ThemeEntry("Munich vs Berlin Reality", "real cost and quality-of-life comparison between Munich and Berlin for expats"),
            ThemeEntry("Cheap Europe Myth", "why the idea that Europe is cheap compared to home countries is outdated for most immigrants"),
            ThemeEntry("Net Salary Shock Germany", "the brutal difference between gross salary offers and actual take-home pay in Germany"),
            ThemeEntry("Rent Eats Everything", "how rent increases in German cities have changed the financial math for immigrant workers"),
            ThemeEntry("What €3000 Net Buys You", "a realistic monthly budget breakdown for a single person earning €3000 net in Germany"),
        ],
    },

    "identity_belonging": {
        "hook_style": "deep identity validation — makes readers feel truly seen",
        "audience": "second-generation immigrants and long-term expats",
        "topics": [
            ThemeEntry("You Belong to Two Worlds", "the experience of belonging fully to neither your origin country nor your new country"),
            ThemeEntry("Third Culture Loneliness", "the unique loneliness of third-culture individuals who feel foreign everywhere"),
            ThemeEntry("Success Feels Empty Abroad", "why achieving career success in Germany sometimes feels disconnected from real happiness"),
            ThemeEntry("Code Switching Is Exhausting", "the daily mental energy cost of adapting to German professional and social norms"),
            ThemeEntry("Family Doesn't Understand", "how family back home often misunderstands the realities of immigrant life in Europe"),
            ThemeEntry("Immigrant Guilt Is Real", "the specific guilt of thriving abroad while family struggles back home"),
        ],
    },

    "side_income_europe": {
        "hook_style": "practical and motivating — realistic income ideas with specifics",
        "audience": "employed immigrants wanting additional income in Germany",
        "topics": [
            ThemeEntry("Side Income in Germany Legal", "legal ways to earn extra income in Germany as an employee without losing your visa status"),
            ThemeEntry("Gewerbe in One Day", "how to register a simple Gewerbe (business) in Germany quickly and cheaply"),
            ThemeEntry("Freelance First Client", "how immigrants in Germany have landed their first freelance client without a portfolio"),
            ThemeEntry("Digital Products No Boss", "how selling digital products removes the ceiling on income for immigrant professionals"),
            ThemeEntry("Tutoring Income Germany", "how to earn €25-60/hour tutoring online from Germany using existing skills"),
            ThemeEntry("The €500 Side Hustle Test", "a realistic framework for testing whether a side hustle idea is worth pursuing in Germany"),
        ],
    },

    "mindset_growth": {
        "hook_style": "perspective shift — challenges assumptions without being preachy",
        "audience": "ambitious immigrants and young professionals",
        "topics": [
            ThemeEntry("Comfort Zone Tax", "how staying in a comfortable but limiting situation costs you more than taking a risk"),
            ThemeEntry("Stop Waiting for Permission", "why immigrants often wait for external validation that never comes, and how to move anyway"),
            ThemeEntry("The 5 Year Version of You", "a thought experiment about whether your current daily actions lead to your desired life in 5 years"),
            ThemeEntry("Urgency You're Missing", "the uncomfortable truth that time passing without intentional action is a decision by default"),
            ThemeEntry("What Regret Actually Feels Like", "the specific regrets that immigrants in their 40s and 50s most commonly report"),
            ThemeEntry("Comparison Is the Wrong Game", "why comparing yourself to peers in Germany leads to paralysis, and what to compare instead"),
        ],
    },
}

# ---------------------------------------------------------------------------
# DB helpers — viral_history table (isolated from tips_history)
# ---------------------------------------------------------------------------

def _get_db_path() -> str:
    return os.getenv("SOCIAL_DB_PATH", _DB_PATH)


def _ensure_viral_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS viral_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            theme      TEXT    NOT NULL,
            topic      TEXT    NOT NULL,
            post_text  TEXT,
            posted_at  TEXT    NOT NULL
        )
        """
    )
    conn.commit()


def _was_posted_recently(
    conn: sqlite3.Connection,
    theme: str,
    topic: str,
    cooldown_days: int,
) -> bool:
    threshold = (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).isoformat()
    row = conn.execute(
        "SELECT 1 FROM viral_history WHERE theme=? AND topic=? AND posted_at>=? LIMIT 1",
        (theme, topic, threshold),
    ).fetchone()
    return row is not None


def _record_posted(
    conn: sqlite3.Connection,
    theme: str,
    topic: str,
    post_text: str,
) -> None:
    conn.execute(
        "INSERT INTO viral_history (theme, topic, post_text, posted_at) VALUES (?,?,?,?)",
        (theme, topic, post_text[:2000], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Topic picker
# ---------------------------------------------------------------------------

def pick_topic(
    cooldown_days: int,
    force_theme: Optional[str] = None,
    seed: Optional[int] = None,
) -> Optional[Tuple[str, str, str, str]]:
    """
    Returns (theme_name, hook_style, image_title, prompt_hint).
    Respects cooldown. Falls back to random if all topics exhausted.
    """
    if seed is not None:
        random.seed(seed)

    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_viral_table(conn)

    # Build flat list
    all_items: List[Tuple[str, str, str, str]] = []
    for theme_name, theme_data in THEMES.items():
        for entry in theme_data["topics"]:
            all_items.append((
                theme_name,
                theme_data["hook_style"],
                entry.image_title,
                entry.prompt_hint,
            ))

    # Filter to forced theme if specified
    if force_theme:
        filtered = [x for x in all_items if x[0] == force_theme]
        if not filtered:
            log.warning(f"Theme '{force_theme}' not found. Using all themes.")
        else:
            all_items = filtered

    random.shuffle(all_items)

    chosen = None
    for theme_name, hook_style, image_title, prompt_hint in all_items:
        if not _was_posted_recently(conn, theme_name, prompt_hint, cooldown_days):
            chosen = (theme_name, hook_style, image_title, prompt_hint)
            break

    if chosen is None:
        log.warning("All viral topics within cooldown window. Picking at random (cooldown bypassed).")
        chosen = random.choice(all_items)

    conn.close()
    return chosen


# ---------------------------------------------------------------------------
# AI prompt builder
# ---------------------------------------------------------------------------

_OUTPUT_DELIMITER_POST = "---POST---"
_OUTPUT_DELIMITER_COMMENTS = "---COMMENTS---"
_OUTPUT_DELIMITER_VISUAL = "---VISUAL---"

_COMMENT_PREFIX = "COMMENT"


def _build_viral_prompt(
    prompt_hint: str,
    hook_style: str,
    theme_name: str,
    site_url: str,
    language: str,
    num_comments: int,
) -> str:
    lang_instruction = "Write in English." if language == "en" else "Schreibe auf Deutsch."

    # Build comment slots explicitly so the model sees the exact pattern to fill
    comment_slots = "\n".join(
        f"COMMENT {i}:\n[write comment {i} here]" for i in range(1, num_comments + 1)
    )

    return f"""You are a viral Facebook content writer for GermanySupport.de.

Topic: {prompt_hint}
Hook style: {hook_style}
{lang_instruction}

TASK: Write a viral Facebook post plus {num_comments} self-comments plus one image prompt.

POST RULES:
- Line 1: scroll-stopping hook, max 12 words, NOT starting with "I"
- Body: 3-5 short paragraphs, 1-3 sentences each, no bullet points
- Second-to-last line: direct engagement question (e.g. "What was your biggest shock? Drop it below 👇")
- Last line: soft CTA (e.g. "Follow GermanySupport for daily Germany tips 🇩🇪")
- Total: 150-280 words, max 3 emojis, no hashtags, no markdown

COMMENT RULES (each comment):
- 2-5 sentences expanding the post topic
- Natural, conversational tone
- End with a micro-question to keep thread alive
- Comment 1: most practical insight
- Comment 2: surprising statistic or fact
- Comment 3: relatable scenario
- Comment 4: common mistake to avoid
- Comment 5: what this means for the future

IMAGE PROMPT RULES:
- Cinematic, high-contrast, emotionally symbolic
- No text in image
- 1-2 sentences

OUTPUT FORMAT — copy this structure exactly, fill in the brackets:

---POST---
[write the full Facebook post here]
---COMMENTS---
COMMENT 1:
[write comment 1 here]
COMMENT 2:
[write comment 2 here]
COMMENT 3:
[write comment 3 here]
COMMENT 4:
[write comment 4 here]
COMMENT 5:
[write comment 5 here]
---VISUAL---
[write the image prompt here]

Do not add any text before ---POST--- or after the image prompt.
Do not use any other section headers.
Do not explain anything."""


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------

class ViralContent(NamedTuple):
    post_text: str
    comments: List[str]          # ordered list, len == num_comments
    visual_prompt: str
    image_title: str             # for branded image headline
    theme: str
    hook_style: str
    prompt_hint: str


def _parse_viral_response(
    raw: str,
    image_title: str,
    theme: str,
    hook_style: str,
    prompt_hint: str,
    num_comments: int,
) -> ViralContent:
    """
    Robust parser for LLM output.

    Tries three extraction strategies in order:
    1. Exact delimiters (---POST--- / ---COMMENTS--- / ---VISUAL---)
    2. Numbered comment headers (COMMENT 1: / **COMMENT 1:** / 1. etc.)
    3. Hard fallback — treat full response as post text, no comments
    """
    import re as _re

    raw = raw.strip()

    # ── Strategy 1: exact delimiters ────────────────────────────────────────
    has_post_delim     = _OUTPUT_DELIMITER_POST in raw
    has_comment_delim  = _OUTPUT_DELIMITER_COMMENTS in raw
    has_visual_delim   = _OUTPUT_DELIMITER_VISUAL in raw

    post_text = ""
    comments: List[str] = []
    visual_prompt = ""

    if has_post_delim and has_comment_delim:
        post_text = raw.split(_OUTPUT_DELIMITER_POST, 1)[1]
        post_text = post_text.split(_OUTPUT_DELIMITER_COMMENTS, 1)[0].strip()
        log.info("Parser: used exact POST delimiter")
    
    if has_comment_delim:
        comments_block = raw.split(_OUTPUT_DELIMITER_COMMENTS, 1)[1]
        if has_visual_delim:
            comments_block = comments_block.split(_OUTPUT_DELIMITER_VISUAL, 1)[0]
        comments = _extract_numbered_comments(comments_block, num_comments)
        log.info(f"Parser: extracted {len(comments)} comments via COMMENTS delimiter")

    if has_visual_delim:
        visual_prompt = raw.split(_OUTPUT_DELIMITER_VISUAL, 1)[1].strip()

    # ── Strategy 2: no POST delimiter but COMMENT headers exist anywhere ────
    if not post_text:
        # Find the first COMMENT N: marker (handles markdown bold too)
        first_comment_match = _re.search(
            r'(?:^|\n)\s*\*{0,2}COMMENT\s*1\s*:?\*{0,2}',
            raw, flags=_re.IGNORECASE
        )
        if first_comment_match:
            post_text = raw[:first_comment_match.start()].strip()
            # Remove leading delimiter line if present
            post_text = _re.sub(r'^---POST---\s*', '', post_text, flags=_re.IGNORECASE).strip()
            log.info("Parser: extracted post text before first COMMENT marker")

            if not comments:
                comment_section = raw[first_comment_match.start():]
                # Cut off at visual delimiter or ---VISUAL---
                visual_match = _re.search(r'---VISUAL---', comment_section, flags=_re.IGNORECASE)
                if visual_match:
                    if not visual_prompt:
                        visual_prompt = comment_section[visual_match.end():].strip()
                    comment_section = comment_section[:visual_match.start()]
                comments = _extract_numbered_comments(comment_section, num_comments)
                log.info(f"Parser: extracted {len(comments)} comments via strategy 2")

    # ── Strategy 3: hard fallback ────────────────────────────────────────────
    if not post_text:
        lines = raw.splitlines()
        post_text = "\n".join(lines[:20]).strip()
        log.warning("Parser: fallback — using first 20 lines as post text, no comments parsed")

    # ── Trim comments ────────────────────────────────────────────────────────
    comments = [c for c in comments if c.strip()][:num_comments]
    log.info(f"Parser final: post_len={len(post_text)}  comments={len(comments)}  visual={'yes' if visual_prompt else 'no'}")

    if not visual_prompt:
        visual_prompt = "Cinematic portrait of a determined immigrant in a modern European city, golden hour light, emotional depth, high contrast, photorealistic"

    return ViralContent(
        post_text=post_text,
        comments=comments,
        visual_prompt=visual_prompt,
        image_title=image_title,
        theme=theme,
        hook_style=hook_style,
        prompt_hint=prompt_hint,
    )


def _extract_numbered_comments(block: str, num_comments: int) -> List[str]:
    """
    Extract COMMENT 1..N from a text block.
    Handles formats:
      COMMENT 1: text
      **COMMENT 1:** text
      COMMENT 1\ntext
      1. text  (plain numbered list fallback)
    """
    import re as _re

    comments: List[str] = []
    # Split on any "COMMENT N:" pattern (with optional markdown bold)
    parts = _re.split(
        r'\*{0,2}COMMENT\s*\d+\s*:?\*{0,2}\s*',
        block,
        flags=_re.IGNORECASE,
    )
    # parts[0] is text before first COMMENT marker — skip it
    for part in parts[1:]:
        text = part.strip()
        if text:
            # Stop at next section delimiter
            text = _re.split(r'^---', text, maxsplit=1, flags=_re.MULTILINE)[0].strip()
            if text:
                comments.append(text)

    if not comments:
        # Last resort: numbered list  "1. ...", "2. ..."
        numbered = _re.findall(r'^\d+\.\s+(.+?)(?=^\d+\.|\Z)', block, flags=_re.MULTILINE | _re.DOTALL)
        comments = [c.strip() for c in numbered if c.strip()]

    return comments[:num_comments]


# ---------------------------------------------------------------------------
# LLM callers
# ---------------------------------------------------------------------------

def _call_anthropic(prompt: str) -> str:
    api_key = os.getenv("ANTHROPIC_KEY", "").strip()
    model = os.getenv("VIRAL_ANTHROPIC_MODEL") or os.getenv("CHEAP_ANTHROPIC_MODEL", "claude-haiku-4-5")

    if not api_key:
        raise RuntimeError("ANTHROPIC_KEY is not set")

    payload = json.dumps({
        "model": model,
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=45) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    return body["content"][0]["text"].strip()


def _call_deepseek(prompt: str) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    payload = json.dumps({
        "model": model,
        "max_tokens": 1200,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=45) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    return body["choices"][0]["message"]["content"].strip()


_LLM_CALLERS = {
    "anthropic": _call_anthropic,
    "deepseek": _call_deepseek,
}


def generate_viral_content(
    theme_name: str,
    hook_style: str,
    image_title: str,
    prompt_hint: str,
    provider: str,
    language: str,
    site_url: str,
    num_comments: int = 5,
) -> ViralContent:
    provider = provider.lower().strip()
    caller = _LLM_CALLERS.get(provider)
    if caller is None:
        available = ", ".join(_LLM_CALLERS.keys())
        raise RuntimeError(f"Unknown provider '{provider}'. Available: {available}")

    prompt = _build_viral_prompt(
        prompt_hint=prompt_hint,
        hook_style=hook_style,
        theme_name=theme_name,
        site_url=site_url,
        language=language,
        num_comments=num_comments,
    )

    raw = caller(prompt)
    log.info(f"LLM response preview: {raw[:300]!r}")
    return _parse_viral_response(
        raw=raw,
        image_title=image_title,
        theme=theme_name,
        hook_style=hook_style,
        prompt_hint=prompt_hint,
        num_comments=num_comments,
    )


# ---------------------------------------------------------------------------
# Build SocialPost
# ---------------------------------------------------------------------------

def _make_external_id(theme: str, prompt_hint: str) -> str:
    digest = hashlib.sha256(prompt_hint.encode("utf-8")).hexdigest()[:16]
    return f"viral:{theme}:{digest}"


def _get_site_url() -> str:
    return (
        os.getenv("VIRAL_SITE_URL", "")
        or os.getenv("WP_URL", "")
        or "https://germanysupport.de"
    ).rstrip("/")


def build_viral_post(content: ViralContent, language: str) -> SocialPost:
    hashtags = os.getenv(
        "VIRAL_HASHTAGS",
        "#germanysupport #germany #expat #immigrant" if language == "en"
        else "#germanysupport #deutschland #expat #immigrant",
    )

    return SocialPost(
        external_id=_make_external_id(content.theme, content.prompt_hint),
        content_type="article",
        title=content.image_title,
        promo_text=content.post_text[:120],   # subtitle on branded image
        summary=content.post_text,            # full caption used by formatter.py
        link=_get_site_url(),
        language=language,
        hashtags=hashtags,
        category_label=content.theme,
        generate_image=True,
        wp_post_id=None,
    )


# ---------------------------------------------------------------------------
# Self-comment poster
# Delegates to FacebookPublisher._post_first_comment() — same pattern as
# news_comments.py which is confirmed working in production.
# ---------------------------------------------------------------------------

def post_self_comments(
    post_id: str,
    comments: List[str],
    targets: Dict,
    target_keys: List[str],
    delay_seconds: float = 8.0,
) -> List[str]:
    """
    Post self-comments to Facebook pages for the given target keys.
    Uses FacebookPublisher._post_first_comment() — the same path used by
    news_comments.py and the existing link-in-first-comment feature.
    Returns list of posted comment IDs.
    """
    from social.platforms.facebook import FacebookPublisher
    from social.platforms.base import PlatformError

    comment_ids: List[str] = []

    for key in target_keys:
        target = targets.get(key)
        if not target or target.platform != "facebook":
            continue

        publisher = FacebookPublisher(target)

        for i, comment_text in enumerate(comments):
            if not comment_text.strip():
                continue
            try:
                if i > 0:
                    time.sleep(delay_seconds)
                cid = publisher._post_first_comment(post_id, comment_text)
                log.info(f"  Comment {i+1} posted: {cid}")
                comment_ids.append(cid)
            except PlatformError as exc:
                log.warning(f"  Comment {i+1} failed: {exc}")
            except Exception as exc:
                log.warning(f"  Comment {i+1} unexpected error: {exc}")

    return comment_ids


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and publish viral Facebook content for GermanySupport."
    )
    parser.add_argument(
        "--targets",
        default="all",
        help="Comma-separated target keys, or 'all' (default: all enabled)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider: 'anthropic' or 'deepseek'. Overrides VIRAL_LLM_PROVIDER.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language: 'en' or 'de'. Overrides VIRAL_LLM_LANGUAGE.",
    )
    parser.add_argument(
        "--theme",
        default=None,
        help=f"Force a specific theme. Options: {', '.join(THEMES.keys())}",
    )
    parser.add_argument(
        "--cooldown-days",
        type=int,
        default=None,
        help="Repeat cooldown in days. Overrides VIRAL_COOLDOWN_DAYS.",
    )
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Skip posting self-comments even if VIRAL_POST_COMMENTS=true.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate content but do not publish.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible topic selection.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override SQLite DB path.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    provider     = args.provider or os.getenv("VIRAL_LLM_PROVIDER", "anthropic").strip()
    language     = args.language or os.getenv("VIRAL_LLM_LANGUAGE", "en").strip()
    cooldown     = args.cooldown_days if args.cooldown_days is not None \
                   else int(os.getenv("VIRAL_COOLDOWN_DAYS", "14"))
    db_path      = args.db_path or os.getenv("SOCIAL_DB_PATH", _DB_PATH)
    post_comments = not args.no_comments and os.getenv("VIRAL_POST_COMMENTS", "true").lower() not in ("0", "false", "no")
    num_comments  = int(os.getenv("VIRAL_MAX_COMMENTS", "5"))
    site_url      = _get_site_url()

    log.info(f"provider={provider}  language={language}  cooldown={cooldown}d  comments={post_comments}")

    # ── 1. Load targets ─────────────────────────────────────────────────────
    targets = get_social_targets()
    if not targets:
        log.error("No social targets configured. Check SOCIAL_TARGETS in .env.")
        return 1

    target_keys = resolve_target_keys(args.targets, list(targets.keys()))
    log.info(f"targets={target_keys}")

    # ── 2. Pick topic ────────────────────────────────────────────────────────
    picked = pick_topic(
        cooldown_days=cooldown,
        force_theme=args.theme,
        seed=args.seed,
    )
    if not picked:
        log.error("Could not pick a topic.")
        return 1

    theme_name, hook_style, image_title, prompt_hint = picked
    log.info(f"theme={theme_name}")
    log.info(f"topic={prompt_hint}")

    # ── 3. Generate content ──────────────────────────────────────────────────
    log.info(f"Generating viral content via {provider}...")
    try:
        viral_content = generate_viral_content(
            theme_name=theme_name,
            hook_style=hook_style,
            image_title=image_title,
            prompt_hint=prompt_hint,
            provider=provider,
            language=language,
            site_url=site_url,
            num_comments=num_comments,
        )
    except Exception as exc:
        log.error(f"Content generation failed: {exc}")
        return 1

    log.info(f"Post preview (first 120 chars): {viral_content.post_text[:120]!r}")
    log.info(f"Comments generated: {len(viral_content.comments)}")
    log.info(f"Visual prompt: {viral_content.visual_prompt[:80]!r}")

    # ── 4. Dry run ───────────────────────────────────────────────────────────
    if args.dry_run:
        preview = {
            "dry_run": True,
            "theme": theme_name,
            "hook_style": hook_style,
            "image_title": image_title,
            "prompt_hint": prompt_hint,
            "provider": provider,
            "language": language,
            "post_text": viral_content.post_text,
            "comments": viral_content.comments,
            "visual_prompt": viral_content.visual_prompt,
            "targets": target_keys,
        }
        log.info("DRY RUN — not publishing.")
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    # ── 5. Build post and publish ────────────────────────────────────────────
    post = build_viral_post(viral_content, language)
    store = SocialStore(db_path)

    log.info("Publishing...")
    result = publish_to_targets(post, targets, target_keys, store, dry_run=False)

    posted_entries = result.get("posted", [])
    posted_count   = len(posted_entries)
    skipped_count  = len(result.get("skipped", []))
    failed_count   = len(result.get("failed", []))

    for entry in posted_entries:
        log.info(f"✓ Published to {entry['target']} ({entry['platform']})  id={entry.get('id')}")
    for entry in result.get("skipped", []):
        log.info(f"↷ Skipped {entry['target']}: {entry.get('reason')}")
    for entry in result.get("failed", []):
        log.error(f"✗ Failed {entry['target']}: {entry.get('error')}")

    # ── 6. Post self-comments ────────────────────────────────────────────────
    # Iterate per posted entry so each page gets comments on ITS OWN post_id.
    # Using target_keys (all targets) caused each page to post comments on the
    # first Facebook post_id found, duplicating comments when multiple FB pages
    # are configured.
    log.info(f"Comments check: post_comments={post_comments}  num_comments={len(viral_content.comments)}  posted_entries={len(posted_entries)}")
    if post_comments and viral_content.comments and posted_entries:
        for entry in posted_entries:
            if entry.get("platform") != "facebook":
                continue
            fb_post_id = entry.get("id", "")
            fb_target_key = entry.get("target", "")
            if not fb_post_id or not fb_target_key:
                continue
            log.info(f"Posting {len(viral_content.comments)} self-comments to {fb_target_key} post {fb_post_id}...")
            comment_ids = post_self_comments(
                post_id=fb_post_id,
                comments=viral_content.comments,
                targets=targets,
                target_keys=[fb_target_key],
            )
            log.info(f"Comments posted to {fb_target_key}: {len(comment_ids)}")

    # ── 7. Record to history ─────────────────────────────────────────────────
    if posted_count > 0:
        conn = sqlite3.connect(db_path)
        _ensure_viral_table(conn)
        _record_posted(conn, theme_name, prompt_hint, viral_content.post_text)
        conn.close()
        log.info(f"Recorded to viral_history (theme={theme_name}).")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failed_count > 0 and posted_count == 0 else 0


if __name__ == "__main__":
    sys.exit(main())