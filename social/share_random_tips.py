# social/share_random_tips.py
"""
Generates and publishes random evergreen Germany-tips posts to all configured
social platforms (Facebook, Instagram, and any future platforms).

Run modes
---------
    python3 -m social.share_random_tips              # publish to all enabled targets
    python3 -m social.share_random_tips --dry-run    # print post preview, skip publish
    python3 -m social.share_random_tips --targets facebook_gs,instagram_gs
    python3 -m social.share_random_tips --provider anthropic
    python3 -m social.share_random_tips --provider deepseek
    ./run_random_tips.sh                              # wrapper (mirrors run_social_from_existing.sh)
    ./run_random_tips.sh --dry-run

New .env variables (optional — all have sensible defaults)
----------------------------------------------------------
    TIPS_LLM_PROVIDER=anthropic          # "anthropic" or "deepseek"  (default: anthropic)
    TIPS_LLM_LANGUAGE=en                 # "en" or "de"               (default: en)
    TIPS_COOLDOWN_DAYS=30                # anti-repeat window          (default: 30)
    TIPS_SITE_URL=https://germanysupport.de  # CTA link in caption     (default: env WP_URL)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: load .env exactly like every other module in this project
# ---------------------------------------------------------------------------
from social.env_loader import load_env_file as _load_env

_load_env(Path(__file__).resolve().parents[1] / ".env")

from social.config import get_social_targets, resolve_target_keys
from social.models import SocialPost
from social.publisher import publish_to_targets
from social.store import SocialStore


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SOCIAL_DIR = Path(__file__).resolve().parent
_DB_PATH = str(_SOCIAL_DIR / "cache" / "social.db")

# ---------------------------------------------------------------------------
# Content library
# Each category maps to a list of (image_title, prompt_hint) pairs.
# image_title  → shown on the branded image (short hook, ≤5 words)
# prompt_hint  → fed to the LLM as the specific topic to write about
# ---------------------------------------------------------------------------
CONTENT_LIBRARY: Dict[str, List[Tuple[str, str]]] = {
    "anmeldung": [
        ("Register Early in Germany", "why registering (Anmeldung) early matters and how it affects tax ID"),
        ("Anmeldung Step by Step", "exact documents needed for Anmeldung and how to book an appointment"),
        ("Skip the Anmeldung Queue", "tips to get a faster Anmeldung appointment in big German cities"),
        ("Anmeldung Mistakes to Avoid", "common mistakes newcomers make during Anmeldung and how to avoid them"),
        ("Anmeldung & Your Tax ID", "how Anmeldung triggers the Steuer-ID and why delays cause problems"),
    ],
    "visa": [
        ("Germany Visa Tip", "one practical tip about extending or switching visas in Germany"),
        ("Freelance Visa Germany", "key requirements for the German freelance visa (Freiberufler)"),
        ("Blue Card Germany", "how the EU Blue Card works and who qualifies"),
        ("Family Reunion Visa", "how to bring a spouse or family member to Germany on a visa"),
        ("Visa Extension Reminder", "why you should start visa extension paperwork 3 months early"),
    ],
    "jobs": [
        ("Job Tip Germany", "one actionable job-search tip specific to the German market"),
        ("German CV Format", "how a German CV (Lebenslauf) differs from international CVs"),
        ("LinkedIn vs Xing Germany", "when to use LinkedIn vs Xing for job hunting in Germany"),
        ("German Job Interview Tips", "how to prepare for a German job interview, including punctuality and directness"),
        ("Job Boards in Germany", "best job platforms in Germany: StepStone, Indeed, Arbeitsagentur"),
        ("Salary Negotiation Germany", "how to negotiate salary in Germany without being seen as rude"),
        ("German Language Advantage", "how even B1 German dramatically improves your job prospects"),
    ],
    "money_saving": [
        ("Save Money in Germany", "one underrated way to save money on everyday expenses in Germany"),
        ("Cheaper Groceries Germany", "how to shop for groceries cheaper using discounters like Aldi and Lidl"),
        ("Compare Electricity Germany", "how to compare and switch electricity providers to save €100–300 per year"),
        ("Internet Contract Hack", "why comparing internet contracts yearly saves money in Germany"),
        ("Public Transport Savings", "how to use Deutschlandticket and other passes to cut transport costs"),
        ("SCHUFA Score & Savings", "how a good SCHUFA score saves you money on deposits and contracts"),
        ("Avoid Bank Fees Germany", "best free bank accounts in Germany and how to avoid hidden fees"),
    ],
    "renting": [
        ("Renting in Germany", "one important tip about renting a flat in Germany as a foreigner"),
        ("German Rental Contract", "what to check in a German Mietvertrag before signing"),
        ("Rental Deposit Rules", "how the Kaution (rental deposit) works and how to get it back"),
        ("SCHUFA for Renting", "why landlords ask for a SCHUFA report and how to get one"),
        ("Flat Hunting Tips", "best platforms and strategies for finding a flat in Germany"),
        ("Nebenkosten Explained", "what Nebenkosten (utility costs) include and why they matter"),
        ("Termination Notice Germany", "how much notice you need to give to terminate a German rental contract"),
    ],
    "family": [
        ("Child Benefit Germany", "how Kindergeld works and who is eligible"),
        ("Kita in Germany", "how to find and register for a Kita (daycare) in Germany"),
        ("School System Germany", "how the German school system works for expat families"),
        ("Parental Leave Germany", "how Elterngeld (parental leave pay) works in Germany"),
        ("Family Health Insurance", "how to add family members to statutory health insurance in Germany"),
    ],
    "taxes": [
        ("File Taxes Germany", "why filing a tax return (Steuererklärung) is worth it even if optional"),
        ("Tax Return Germany Tip", "one deduction that most employees miss in their German tax return"),
        ("ELSTER for Taxes", "how to use ELSTER to file taxes online for free in Germany"),
        ("Freelancer Tax Germany", "quarterly tax prepayments (Vorauszahlungen) explained for freelancers"),
        ("Church Tax Germany", "what Kirchensteuer is and how to opt out if you're not religious"),
    ],
    "transport": [
        ("Deutschlandticket Tip", "how to get the most value out of the Deutschlandticket"),
        ("DB Train Hacks", "how to find cheap Deutsche Bahn tickets using Sparpreise and BahnCard"),
        ("Cycling in Germany", "how cycling infrastructure works in German cities and e-bike tips"),
        ("Driving License Germany", "how to convert a foreign driving license in Germany"),
        ("Car Sharing Germany", "best car-sharing apps in Germany and when they beat owning a car"),
    ],
    "student_life": [
        ("Student Tip Germany", "one money-saving or life hack tip for international students in Germany"),
        ("Semesterticket Explained", "how the student Semesterticket works and what transport it covers"),
        ("Student Health Insurance", "cheapest health insurance options for students in Germany"),
        ("Working While Studying", "how many hours international students can legally work in Germany"),
        ("Student Housing Germany", "how to find student housing (Studentenwohnheim) in Germany"),
        ("BAföG for Students", "who qualifies for BAföG student financial aid in Germany"),
    ],
    "insurance": [
        ("Insurance Tip Germany", "one type of insurance that is underrated but very useful in Germany"),
        ("Haftpflicht Insurance", "why personal liability insurance (Haftpflicht) is essential in Germany"),
        ("Health Insurance Germany", "difference between statutory (GKV) and private (PKV) health insurance"),
        ("Household Insurance", "what Hausratversicherung covers and when it's worth it"),
        ("Travel Insurance Germany", "why travel insurance matters even when living inside the EU"),
    ],
    "bureaucracy": [
        ("Germany Bureaucracy Tip", "one tip to navigate German bureaucracy faster and with less stress"),
        ("Appointment Booking Germany", "how to book government appointments faster in German cities"),
        ("Post in Germany", "how Deutsche Post and DHL parcel systems work, and how to receive packages"),
        ("Digital Signature Germany", "how to use electronic signatures for German documents legally"),
        ("Certified Documents Germany", "when you need beglaubigte Kopien (certified copies) and how to get them"),
    ],
    "german_life_hacks": [
        ("Germany Life Hack", "one surprising life hack that makes daily life easier in Germany"),
        ("Cash in Germany", "why Germany is still very cash-heavy and how to always be prepared"),
        ("Quiet Hours Germany", "what Ruhezeiten (quiet hours) are and how to avoid neighbour complaints"),
        ("Recycling Germany", "how the German recycling system (Pfand, Gelber Sack, Biotonne) works"),
        ("Sunday Rules Germany", "what is and isn't allowed on Sundays in Germany"),
        ("German Punctuality", "how punctuality works in professional vs social settings in Germany"),
    ],
    "mistakes_to_avoid": [
        ("Avoid This Mistake", "one very common and costly mistake newcomers make in Germany"),
        ("Don't Skip Registration", "consequences of not doing Anmeldung on time in Germany"),
        ("Insurance Gap Mistake", "the risk of having even a short health insurance gap in Germany"),
        ("Late Tax Filing Germany", "penalties for filing taxes or Umsatzsteuer late in Germany"),
        ("Verbal Contract Warning", "why verbal agreements are risky in Germany and what to do instead"),
    ],
    "apps_in_germany": [
        ("Best App in Germany", "one must-have app for daily life in Germany that most expats don't know"),
        ("Banking Apps Germany", "best mobile banking apps for expats in Germany (N26, Wise, DKB)"),
        ("Transport Apps Germany", "best apps for public transport navigation in Germany"),
        ("Doctor Booking Apps", "how to book doctor appointments online in Germany using apps like Doctolib"),
        ("Government Apps Germany", "useful German government and official apps for expats"),
        ("Language Learning Apps", "best apps for learning German as a newcomer"),
    ],
    "salary_career": [
        ("Salary Tip Germany", "one fact about German salaries that surprises most newcomers"),
        ("Gross vs Net Salary", "how to calculate net salary from gross in Germany"),
        ("13th Month Salary", "what Weihnachtsgeld and Urlaubsgeld are and who gets them"),
        ("Raise Request Germany", "how to ask for a salary raise in German workplace culture"),
        ("Probation Period Germany", "rights and risks during the Probezeit (probationary period) in Germany"),
        ("Notice Period Germany", "how Kündigungsfristen (notice periods) work for employees in Germany"),
    ],
}


# ---------------------------------------------------------------------------
# Anti-repetition: tips_history table in existing social.db
# ---------------------------------------------------------------------------

def _get_db_path() -> str:
    return os.getenv("SOCIAL_DB_PATH", _DB_PATH)


def _ensure_tips_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tips_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            category  TEXT    NOT NULL,
            topic     TEXT    NOT NULL,
            posted_at TEXT    NOT NULL
        )
        """
    )
    conn.commit()


def _was_posted_recently(
    conn: sqlite3.Connection,
    category: str,
    topic: str,
    cooldown_days: int,
) -> bool:
    threshold = (datetime.now(timezone.utc) - timedelta(days=cooldown_days)).isoformat()
    row = conn.execute(
        """
        SELECT 1 FROM tips_history
        WHERE category = ? AND topic = ? AND posted_at >= ?
        LIMIT 1
        """,
        (category, topic, threshold),
    ).fetchone()
    return row is not None


def _record_posted(conn: sqlite3.Connection, category: str, topic: str) -> None:
    conn.execute(
        "INSERT INTO tips_history (category, topic, posted_at) VALUES (?, ?, ?)",
        (category, topic, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def pick_topic(
    cooldown_days: int,
    seed: Optional[int] = None,
) -> Optional[Tuple[str, str, str]]:
    """
    Returns (category, image_title, prompt_hint) avoiding recently posted topics.
    Falls back to ignoring cooldown if everything has been used recently.
    """
    if seed is not None:
        random.seed(seed)

    db_path = _get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_tips_table(conn)

    # Build a flat list, shuffle it, pick first that isn't on cooldown
    all_items: List[Tuple[str, str, str]] = []
    for category, topics in CONTENT_LIBRARY.items():
        for image_title, prompt_hint in topics:
            all_items.append((category, image_title, prompt_hint))

    random.shuffle(all_items)

    chosen = None
    for category, image_title, prompt_hint in all_items:
        if not _was_posted_recently(conn, category, prompt_hint, cooldown_days):
            chosen = (category, image_title, prompt_hint)
            break

    # Fallback: all topics used recently → pick completely at random
    if chosen is None:
        print("WARNING: All topics within cooldown window. Picking at random (cooldown bypassed).")
        chosen = random.choice(all_items)

    conn.close()
    return chosen


# ---------------------------------------------------------------------------
# LLM caption generation
# ---------------------------------------------------------------------------

def _get_site_url() -> str:
    url = (
        os.getenv("TIPS_SITE_URL", "")
        or os.getenv("WP_URL", "")
        or os.getenv("WORDPRESS_URL", "")
        or "https://germanysupport.de"
    ).rstrip("/")
    return url


def _build_caption_prompt(prompt_hint: str, language: str, site_url: str) -> str:
    language = language.lower().strip()
    if language in {"bn", "bengali", "bangla"}:
        lang_instruction = "Write entirely in Bengali (Bangla script). Do not use English or German except for unavoidable proper names or URLs."
    elif language == "en":
        lang_instruction = "Write in English."
    else:
        lang_instruction = "Schreibe auf Deutsch."
    return f"""You are a social media writer for GermanySupport.de — a practical guide for immigrants, expats, and newcomers living in Germany.

Write ONE social media post about: {prompt_hint}

You must return EXACTLY two sections separated by the delimiter ---IMAGE_SUBTITLE---

Section 1 — IMAGE_SUBTITLE (appears on the social image graphic):
- Maximum 10 words, no emoji, no punctuation at the end
- A single punchy sentence that distils the core tip
- Example: "Start your visa extension 6 weeks before it expires"

Section 2 — CAPTION (the full post text for Facebook/Instagram):
- Format: hook line → 1–2 tip lines → CTA line
- Hook: short, punchy, starts with an emoji or a bold question/statement
- Tip: practical, specific, actionable (1–2 sentences max)
- CTA: End by asking readers in Bengali to follow @brownguygermany and visit the GermanySupport website using the link in the first comment
- Do not include URLs or website links in the caption
- Total length: 5–9 lines, under 280 words
- Use 1–3 relevant emojis total, do NOT overload
- Tone: helpful, modern, trustworthy — NOT clickbait
- Do NOT include hashtags (added separately)
- Do NOT use markdown formatting (no bold, no asterisks)
- {lang_instruction}

Return format (nothing else — no preamble, no labels):
<the image subtitle here>
---IMAGE_SUBTITLE---
<the full caption here>"""


_SUBTITLE_DELIMITER = "---IMAGE_SUBTITLE---"


def _parse_llm_response(raw: str) -> Tuple[str, str]:
    """
    Split LLM response into (image_subtitle, caption).
    The model is asked to put the subtitle FIRST, then the delimiter, then the caption.
    Falls back gracefully if the model ignores the format.
    """
    raw = raw.strip()
    if _SUBTITLE_DELIMITER in raw:
        parts = raw.split(_SUBTITLE_DELIMITER, 1)
        subtitle = parts[0].strip()
        caption  = parts[1].strip()
    else:
        # Fallback: no delimiter found — treat first line as subtitle, rest as caption
        lines = raw.splitlines()
        subtitle = lines[0].strip() if lines else ""
        caption  = "\n".join(lines[1:]).strip() if len(lines) > 1 else raw

    # Hard cap subtitle at 10 words — truncate if LLM was verbose
    words = subtitle.split()
    if len(words) > 10:
        subtitle = " ".join(words[:10])

    return subtitle, caption


def generate_caption_anthropic(prompt_hint: str, language: str, site_url: str) -> Tuple[str, str]:
    import urllib.request

    api_key = os.getenv("ANTHROPIC_KEY", "").strip()
    model = os.getenv("CHEAP_ANTHROPIC_MODEL", "claude-haiku-4-5").strip()

    if not api_key:
        raise RuntimeError("ANTHROPIC_KEY is not set in .env")

    payload = json.dumps({
        "model": model,
        "max_tokens": 500,
        "messages": [
            {
                "role": "user",
                "content": _build_caption_prompt(prompt_hint, language, site_url),
            }
        ],
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

    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    raw = body["content"][0]["text"].strip()
    return _parse_llm_response(raw)


def generate_caption_deepseek(prompt_hint: str, language: str, site_url: str) -> Tuple[str, str]:
    from openai import OpenAI

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
    max_tokens = int(os.getenv("DEEPSEEK_MAX_TOKENS", "450"))

    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set in .env")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": _build_caption_prompt(prompt_hint, language, site_url),
        }],
        max_tokens=max_tokens,
    )
    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        raise RuntimeError("DeepSeek returned an empty caption response")
    return _parse_llm_response(raw)


# ---------------------------------------------------------------------------
# Provider registry — add new providers here without touching anything else
# Each provider function returns (image_subtitle: str, caption: str)
# ---------------------------------------------------------------------------
_CAPTION_PROVIDERS = {
    "anthropic": generate_caption_anthropic,
    "deepseek":  generate_caption_deepseek,
    # future: "openai": generate_caption_openai, etc.
}


def generate_caption(
    prompt_hint: str, language: str, site_url: str, provider: str
) -> Tuple[str, str]:
    """Returns (image_subtitle, caption)."""
    provider = provider.lower().strip()
    fn = _CAPTION_PROVIDERS.get(provider)
    if fn is None:
        available = ", ".join(_CAPTION_PROVIDERS.keys())
        raise RuntimeError(
            f"Unknown LLM provider '{provider}'. Available: {available}"
        )
    return fn(prompt_hint, language, site_url)


# ---------------------------------------------------------------------------
# Build a SocialPost for a tip
# ---------------------------------------------------------------------------

def _make_external_id(category: str, prompt_hint: str) -> str:
    digest = hashlib.sha256(prompt_hint.encode("utf-8")).hexdigest()[:16]
    return f"tip:{category}:{digest}"


def build_tip_post(
    category: str,
    image_title: str,
    image_subtitle: str,
    caption: str,
    language: str,
    hashtags: Optional[str] = None,
) -> SocialPost:
    external_id = _make_external_id(category, image_title)
    site_url = _get_site_url()
    is_bengali = language.lower().strip() in {"bn", "bengali", "bangla"}

    # Default hashtags if none supplied
    if not hashtags:
        language = language.lower().strip()
        if language in {"bn", "bengali", "bangla"}:
            hashtags = os.getenv(
                "SOCIAL_DEFAULT_HASHTAGS_BN",
                "#germanysupport #জার্মানি #প্রবাসী #জার্মানিজীবন",
            )
        elif language == "de":
            hashtags = os.getenv(
                "SOCIAL_DEFAULT_HASHTAGS_DE",
                "#germanysupport #deutschland #tipps #expat",
            )
        else:
            hashtags = os.getenv(
                "SOCIAL_DEFAULT_HASHTAGS_EN",
                "#germanysupport #germany #expat #newcomers",
            )

    return SocialPost(
        external_id=external_id,
        content_type="article",
        title=image_subtitle if is_bengali and image_subtitle else image_title,
        promo_text=None if is_bengali else image_subtitle,
        summary=caption,           # full post body used by formatter.py for Facebook/Instagram caption
        link=site_url,
        language=language,
        hashtags=hashtags,
        category_label=category,
        generate_image=True,
        wp_post_id=None,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and publish a random evergreen Germany tip to social platforms."
    )
    parser.add_argument(
        "--targets",
        default="all",
        help="Comma-separated target keys, or 'all' (default: all enabled targets)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider: 'anthropic' or 'deepseek'. Overrides TIPS_LLM_PROVIDER in .env.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Caption language: 'en', 'de', or 'bn'. Overrides TIPS_LLM_LANGUAGE in .env.",
    )
    parser.add_argument(
        "--cooldown-days",
        type=int,
        default=None,
        help="Days before the same topic can repeat. Overrides TIPS_COOLDOWN_DAYS in .env.",
    )
    parser.add_argument(
        "--hashtags",
        default="",
        help="Override default hashtags (optional).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pick topic and generate caption/image, but skip publishing.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible topic picking (useful for testing).",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override SQLite DB path (default: social/cache/social.db).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    # Resolve config — CLI flags take precedence over .env
    provider  = args.provider  or os.getenv("TIPS_LLM_PROVIDER",  "anthropic").strip()
    language  = args.language  or os.getenv("TIPS_LLM_LANGUAGE",  "en").strip()
    cooldown  = args.cooldown_days if args.cooldown_days is not None \
                else int(os.getenv("TIPS_COOLDOWN_DAYS", "30"))
    db_path   = args.db_path or os.getenv("SOCIAL_DB_PATH", _DB_PATH)

    print(f"[tips] provider={provider}  language={language}  cooldown={cooldown}d")

    # ── 1. Load social targets ──────────────────────────────────────────────
    targets = get_social_targets()
    if not targets:
        print("ERROR: No social targets configured. Check SOCIAL_TARGETS in .env.")
        return 1

    target_keys = resolve_target_keys(args.targets, list(targets.keys()))
    print(f"[tips] targets={target_keys}")

    # ── 2. Pick topic ───────────────────────────────────────────────────────
    picked = pick_topic(cooldown_days=cooldown, seed=args.seed)
    if not picked:
        print("ERROR: Could not pick a topic.")
        return 1

    category, image_title, prompt_hint = picked
    print(f"[tips] category={category}")
    print(f"[tips] topic={prompt_hint}")

    # ── 3. Generate caption ─────────────────────────────────────────────────
    print(f"[tips] Generating caption via {provider}...")
    try:
        site_url = _get_site_url()
        image_subtitle, caption = generate_caption(prompt_hint, language, site_url, provider)
    except Exception as exc:
        print(f"ERROR: Caption generation failed: {exc}")
        return 1

    print(f"[tips] Image subtitle: {image_subtitle}")
    print("[tips] Caption generated:")
    print("-------")
    print(caption)
    print("-------")

    # ── 4. Build SocialPost ─────────────────────────────────────────────────
    post = build_tip_post(
        category=category,
        image_title=image_title,
        image_subtitle=image_subtitle,
        caption=caption,
        language=language,
        hashtags=args.hashtags or None,
    )

    # ── 5. Dry-run: stop here ───────────────────────────────────────────────
    if args.dry_run:
        preview = {
            "dry_run": True,
            "category": category,
            "image_title": image_title,
            "image_subtitle": image_subtitle,
            "prompt_hint": prompt_hint,
            "provider": provider,
            "language": language,
            "external_id": post.external_id,
            "caption": caption,
            "hashtags": post.hashtags,
            "targets": target_keys,
        }
        print("[tips] DRY RUN — not publishing.")
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    # ── 6. Publish ──────────────────────────────────────────────────────────
    store = SocialStore(db_path)
    print("[tips] Publishing...")
    result = publish_to_targets(post, targets, target_keys, store, dry_run=False)

    posted_count  = len(result.get("posted",  []))
    skipped_count = len(result.get("skipped", []))
    failed_count  = len(result.get("failed",  []))

    for entry in result.get("posted", []):
        print(f"[tips] ✓ Published to {entry['target']} ({entry['platform']})  id={entry.get('id')}")

    for entry in result.get("skipped", []):
        print(f"[tips] ↷ Skipped {entry['target']}: {entry.get('reason')}")

    for entry in result.get("failed", []):
        print(f"[tips] ✗ Failed  {entry['target']}: {entry.get('error')}")

    # ── 7. Record in tips_history only if at least one platform succeeded ───
    if posted_count > 0:
        conn = sqlite3.connect(db_path)
        _ensure_tips_table(conn)
        _record_posted(conn, category, prompt_hint)
        conn.close()
        print(f"[tips] Recorded to tips_history (category={category}).")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failed_count > 0 and posted_count == 0 else 0


if __name__ == "__main__":
    sys.exit(main())