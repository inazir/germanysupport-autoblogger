"""
social/daily_news/news_ai.py

Phase 1: Generate social media caption from top news items.
Supports Claude (primary), DeepSeek (fallback), template (last resort).
Provider chain is controlled by .env.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List

from social.daily_news.news_fetcher import NewsItem


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(items: List[NewsItem], top_n: int = 3, language: str = "en") -> str:
    today = datetime.now().strftime("%B %d, %Y")
    headlines = "\n".join(
        f"{i+1}. {item.title} (source: {item.source})"
        for i, item in enumerate(items[:top_n])
    )
    language = language.lower().strip()
    if language in {"bn", "bengali", "bangla"}:
        language_instruction = "Write entirely in Bengali (Bangla script). Do not use English or German except for unavoidable proper names, source names, or URLs."
    elif language == "en":
        language_instruction = "Write in English."
    else:
        language_instruction = "Write in German."

    return f"""You are a social media manager for GermanySupport.de, a website helping expats and immigrants in Germany.

Today is {today}.

Here are today's top Germany news headlines:
{headlines}

Write a HIGH ENGAGEMENT Facebook post for our audience of expats and immigrants living in Germany.

REQUIREMENTS:
- Include Today is {today} at the top of the post.
- Don't include your initial text something like here is your HIGH ENGAGEMENT Facebook post. I want only the post with top 3 headlines.
- List each headline as a numbered point with a relevant emoji
- Keep each point to 1-2 short lines
- End with ONE engaging question that invites comments (e.g. ""Read more top news in the comments!" and "Which update affects you most? Comment below 👇" )
- Final line: "Follow @GermanySupport for daily updates."
- Friendly, credible, easy, human writing
- {language_instruction}
- Avoid fake sensationalism or clickbait
- Total length: 3 top headlines, so, should be within 500 words. But don't break lines. If required to up to 600 words.
- No **bold**
- NO hashtags (they will be added separately)

Return ONLY the post text. No preamble, no explanation."""


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _try_claude(prompt: str) -> str | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("NEWS_AI_MODEL", "claude-sonnet-4-5").strip()
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except ImportError:
        print("  [news_ai] anthropic package not installed, skipping Claude")
        return None
    except Exception as exc:
        print(f"  [news_ai] Claude failed: {exc}")
        return None


def _try_deepseek(prompt: str) -> str | None:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("NEWS_AI_FALLBACK_MODEL", "deepseek-chat").strip()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        print(f"  [news_ai] DeepSeek failed: {exc}")
        return None


def _try_openai(prompt: str) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("NEWS_AI_OPENAI_MODEL", "gpt-4o-mini").strip()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        print(f"  [news_ai] OpenAI failed: {exc}")
        return None


def _template_caption(items: List[NewsItem], top_n: int = 3, language: str = "en") -> str:
    """Fallback caption (NO AI). Structured for social posts."""

    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

    lines = []

    # NOTE: Do NOT include "Germany Daily Update" title here
    # Title must be handled in share_news.py to avoid duplication

    for i, item in enumerate(items[:top_n]):
        emoji = emojis[i] if i < len(emojis) else "▶️"

        # Keep it clean: title only, no source clutter
        title = item.title.strip()

        lines.append(f"{emoji} {title}")

    if language.lower().strip() in {"bn", "bengali", "bangla"}:
        cta_lines = [
            "",
            "কোন খবরটি আপনাকে সবচেয়ে বেশি প্রভাবিত করে? নিচে মন্তব্য করুন 👇",
            "",
            "প্রতিদিনের আপডেটের জন্য আমাদের পেজটি অনুসরণ করুন।",
        ]
    else:
        cta_lines = [
            "",
            "Which update affects you most? Comment below 👇",
            "",
            "Follow our page for daily updates.",
        ]
    lines += cta_lines

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_caption(items: List[NewsItem], top_n: int = 3, language: str = "en") -> str:
    """
    Generate a social media caption from the top news items.
    Tries providers in order: primary → fallback → openai → template.
    Returns caption string.
    """
    if not items:
        return _template_caption([], top_n, language)

    primary = os.getenv("NEWS_AI_PROVIDER", "claude").strip().lower()
    fallback = os.getenv("NEWS_AI_FALLBACK_PROVIDER", "deepseek").strip().lower()

    prompt = _build_prompt(items, top_n, language)

    provider_map = {
        "claude": _try_claude,
        "deepseek": _try_deepseek,
        "openai": _try_openai,
    }

    # Build ordered list: primary, fallback, then remaining providers
    order = [primary, fallback]
    for p in ["claude", "deepseek", "openai"]:
        if p not in order:
            order.append(p)

    for provider in order:
        fn = provider_map.get(provider)
        if fn is None:
            continue
        print(f"  [news_ai] Trying provider: {provider}")
        result = fn(prompt)
        if result:
            print(f"  [news_ai] Caption generated via {provider} ({len(result)} chars)")
            return result

    print("  [news_ai] All AI providers failed — using template caption")
    return _template_caption(items, top_n, language)
