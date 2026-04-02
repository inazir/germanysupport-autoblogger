import os
import re
import json
from functools import lru_cache

import requests


ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "").strip()
DEALS_TRANSLATION_MODEL = os.environ.get("DEALS_TRANSLATION_MODEL", "claude-haiku-4-5")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


def _format_price(value, currency="EUR"):
    if value is None:
        return ""
    return f"{value:.2f} {currency}"


def _clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _simple_fallback_de(text: str) -> str:
    """
    Safety-only fallback.
    This is NOT the main translation path.
    If API fails, return a minimally cleaned version rather than maintaining
    a giant rule dictionary.
    """
    return _clean_spaces(text)


def _anthropic_translate(text: str, mode: str) -> str:
    if not text:
        return ""

    if not ANTHROPIC_KEY:
        return _simple_fallback_de(text)

    if mode == "title":
        prompt = (
            "Translate this deal title into natural, concise German for a consumer deals website in Germany. "
            "Keep it short, fluent, and headline-friendly. "
            "Do not explain anything. "
            "Do not add quotation marks. "
            "Return only the translated title.\n\n"
            f"Text: {text}"
        )
    else:
        prompt = (
            "Translate this short promotional phrase into natural, concise German for a consumer deals website in Germany. "
            "Keep it short and fluent. "
            "Do not explain anything. "
            "Do not add quotation marks. "
            "Return only the translated phrase.\n\n"
            f"Text: {text}"
        )

    payload = {
        "model": DEALS_TRANSLATION_MODEL,
        "max_tokens": 120,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    headers = {
        "x-api-key": ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    response = requests.post(
        ANTHROPIC_API_URL,
        headers=headers,
        data=json.dumps(payload),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    parts = data.get("content", [])
    translated = "".join(
        part.get("text", "") for part in parts if part.get("type") == "text"
    )
    translated = _clean_spaces(translated)

    return translated or _simple_fallback_de(text)


@lru_cache(maxsize=1024)
def _translate_title_to_de(text: str) -> str:
    try:
        return _anthropic_translate(text, mode="title")
    except Exception:
        return _simple_fallback_de(text)


@lru_cache(maxsize=1024)
def _translate_promo_to_de(text: str) -> str:
    try:
        return _anthropic_translate(text, mode="promo")
    except Exception:
        return _simple_fallback_de(text)


def build_post_title(item, language: str) -> str:
    base_title = item.title or ""

    if language == "de":
        return f"Aktueller Deal: {_translate_title_to_de(base_title)}"

    return f"Current deal: {base_title}"


def build_excerpt(item, language: str) -> str:
    base_title = item.title or ""

    if language == "de":
        return f"Aktueller Deal: {_translate_title_to_de(base_title)}"

    return f"Current deal: {base_title}"


def build_body(item, language: str) -> str:
    title_source = item.title or ""
    promo_source = item.promo_text or ""

    if language == "de":
        title_text = _translate_title_to_de(title_source)
        promo_text = _translate_promo_to_de(promo_source)
        cta_text = "Deal ansehen"
        changing_text = (
            "Dieses Angebot kann sich jederzeit ändern oder enden. "
            "Bitte prüfe die aktuellen Details direkt beim Anbieter."
        )
        heading = f"Aktueller Deal: {title_text}"
        price_label = "Preis"
        promo_label = "Angebotsdetails"
        savings_label = "Ersparnis"
    else:
        title_text = title_source
        promo_text = promo_source
        cta_text = "View deal"
        changing_text = (
            "This deal may change or end at any time. "
            "Please check the latest details directly on the provider page."
        )
        heading = f"Current deal: {title_text}"
        price_label = "Price"
        promo_label = "Offer details"
        savings_label = "Savings"

    lines = [heading]

    if item.new_price is not None:
        if item.old_price is not None and item.old_price > item.new_price:
            savings = item.old_price - item.new_price
            lines.append(
                f"{price_label}: {_format_price(item.new_price, item.currency)} "
                f"{_format_price(item.old_price, item.currency)} "
                f"({savings_label} {_format_price(savings, item.currency)})"
            )
        else:
            lines.append(f"{price_label}: {_format_price(item.new_price, item.currency)}")

    if promo_text:
        lines.append(f"{promo_label}: {promo_text}")

    lines.append(changing_text)

    if item.internal_url:
        lines.append("")
        if item.internal_url.startswith("/"):
            final_url = f"https://germanysupport.de{item.internal_url}"
        else:
            final_url = item.internal_url
        lines.append(f'<a href="{final_url}">{cta_text}</a>')

    return "\n".join(lines)