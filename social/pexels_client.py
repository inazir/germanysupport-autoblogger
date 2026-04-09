from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

import requests


PEXELS_API_URL = "https://api.pexels.com/v1/search"


def _slug_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _build_query(*args) -> str:
    """
    Backward-compatible Pexels query builder.

    Supports either:
    - _build_query(post)
    - _build_query(title, summary, category_label, content_type)
    """

    def _clean(value: str | None) -> str:
        return " ".join((value or "").strip().lower().split())

    title = ""
    summary = ""
    promo = ""
    category = ""
    content_type = ""

    if len(args) == 1:
        post = args[0]
        title = _clean(getattr(post, "title", ""))
        summary = _clean(getattr(post, "summary", ""))
        promo = _clean(getattr(post, "promo_text", ""))
        category = _clean(getattr(post, "category_label", ""))
        content_type = _clean(getattr(post, "content_type", ""))
    else:
        title = _clean(args[0] if len(args) > 0 else "")
        summary = _clean(args[1] if len(args) > 1 else "")
        category = _clean(args[2] if len(args) > 2 else "")
        content_type = _clean(args[3] if len(args) > 3 else "")
        promo = ""

    text = " | ".join(x for x in [title, summary, promo, category, content_type] if x)

    topic_queries: list[tuple[list[str], str]] = [
        (
            [
                "electricity",
                "strom",
                "energy bill",
                "power bill",
                "utility bill",
                "electric provider",
                "electric tariff",
                "stromanbieter",
                "strompreis",
                "gas bill",
                "heating bill",
                "nebenkosten",
            ],
            "electricity meter home energy bill",
        ),
        (
            [
                "solar",
                "photovoltaic",
                "pv",
                "renewable energy",
                "solar panel",
            ],
            "solar panels house roof",
        ),
        (
            [
                "tax",
                "steuer",
                "tax return",
                "steuererklärung",
                "tax class",
                "steuerklasse",
                "elster",
                "tax refund",
                "freelancer tax",
            ],
            "tax documents calculator desk paperwork",
        ),
        (
            [
                "insurance",
                "versicherung",
                "health insurance",
                "krankenversicherung",
                "liability insurance",
                "haftpflicht",
                "household insurance",
                "hausrat",
                "car insurance",
                "travel insurance",
                "legal insurance",
                "rechtschutz",
            ],
            "insurance contract paperwork family home",
        ),
        (
            [
                "visa",
                "residence permit",
                "aufenthaltstitel",
                "aufenthaltserlaubnis",
                "immigration",
                "blue card",
                "eu blue card",
                "work permit",
                "foreigners office",
                "ausländerbehörde",
            ],
            "passport visa documents travel",
        ),
        (
            [
                "anmeldung",
                "address registration",
                "bürgeramt",
                "wohnungsgeberbestätigung",
                "registration certificate",
                "bureaucracy",
                "documents required",
                "appointment",
            ],
            "documents paperwork office appointment",
        ),
        (
            [
                "bank",
                "bank account",
                "konto",
                "iban",
                "money transfer",
                "send money",
                "remittance",
                "wise",
                "revolut",
                "n26",
                "account opening",
            ],
            "online banking smartphone payment card",
        ),
        (
            [
                "credit card",
                "debit card",
                "mastercard",
                "visa card",
                "savings",
                "etf",
                "investment",
                "broker",
                "stock market",
                "trade republic",
                "scalable",
            ],
            "bank card savings finance smartphone",
        ),
        (
            [
                "sim",
                "esim",
                "mobile plan",
                "internet",
                "wifi",
                "dsl",
                "broadband",
                "phone contract",
                "mobile contract",
            ],
            "smartphone sim card mobile internet",
        ),
        (
            [
                "rent",
                "rental",
                "wohnung",
                "apartment",
                "flat",
                "tenant",
                "landlord",
                "miete",
                "warmmiete",
                "kaltmiete",
                "deposit",
                "kaution",
                "wg",
            ],
            "apartment keys contract home",
        ),
        (
            [
                "job",
                "salary",
                "gross net",
                "brutto netto",
                "employment",
                "contract",
                "interview",
                "cv",
                "resume",
                "work in germany",
            ],
            "job interview laptop documents office",
        ),
        (
            [
                "kindergeld",
                "child benefit",
                "family benefit",
                "elterngeld",
                "parental allowance",
                "kita",
                "school",
                "childcare",
            ],
            "family children documents home",
        ),
        (
            [
                "travel",
                "flight",
                "hotel",
                "holiday",
                "urlaub",
                "train",
                "deutsche bahn",
                "bahncard",
                "transport",
                "ticket",
            ],
            "travel suitcase train station",
        ),
        (
            [
                "car",
                "driving licence",
                "driver license",
                "führerschein",
                "vehicle registration",
                "auto insurance",
                "parking",
                "tuv",
            ],
            "car keys documents",
        ),
        (
            [
                "doctor",
                "hospital",
                "medical",
                "clinic",
                "appointment",
                "health card",
                "krankenkasse",
            ],
            "doctor appointment medical documents",
        ),
        (
            [
                "deal",
                "discount",
                "offer",
                "coupon",
                "sale",
                "best deal",
                "cashback",
                "bonus",
                "promo",
            ],
            "shopping discount online deal",
        ),
    ]

    for keywords, query in topic_queries:
        if any(keyword in text for keyword in keywords):
            return query

    if "deal" in category or "deal" in content_type:
        return "shopping discount online deal"

    if "finance" in category:
        return "banking documents calculator"

    if "insurance" in category:
        return "insurance contract paperwork family home"

    if "guide" in content_type or "how to" in title:
        return "documents checklist paperwork desk"

    preferred_terms = [
        "documents",
        "passport",
        "contract",
        "apartment",
        "bank",
        "insurance",
        "electricity",
        "tax",
        "visa",
        "registration",
        "family",
        "travel",
        "smartphone",
        "card",
        "home",
    ]

    found = [term for term in preferred_terms if term in text]
    if found:
        return " ".join(found[:4])

    return "documents paperwork germany"

def search_photo(
    *,
    query: str,
    api_key: str,
    per_page: int = 5,
    orientation: str = "square",
) -> Optional[dict]:
    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": orientation,
    }

    resp = requests.get(PEXELS_API_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    photos = payload.get("photos") or []
    if not photos:
        return None

    return photos[0]


def download_photo(
    *,
    photo: dict,
    output_dir: str | Path,
    filename_prefix: str,
    external_id: str,
) -> str:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = photo.get("src") or {}
    image_url = (
        src.get("large2x")
        or src.get("large")
        or src.get("original")
        or src.get("medium")
    )
    if not image_url:
        raise RuntimeError("Pexels photo is missing usable image URL")

    file_name = f"{filename_prefix}_{_slug_hash(external_id)}_pexels.jpg"
    output_path = out_dir / file_name

    img_resp = requests.get(image_url, timeout=60)
    img_resp.raise_for_status()
    output_path.write_bytes(img_resp.content)

    return str(output_path)


def fetch_pexels_background(
    *,
    external_id: str,
    title: str,
    summary: str,
    category_label: str,
    content_type: str,
    output_dir: str | Path,
    filename_prefix: str,
) -> Optional[dict]:
    api_key = os.getenv("PEXELS_KEY", "").strip()
    if not api_key:
        return None

    query = _build_query(title, summary, category_label, content_type)
    photo = search_photo(query=query, api_key=api_key)
    if not photo:
        return None

    local_path = download_photo(
        photo=photo,
        output_dir=output_dir,
        filename_prefix=filename_prefix,
        external_id=external_id,
    )

    return {
        "local_path": local_path,
        "photographer": photo.get("photographer"),
        "photo_url": photo.get("url"),
        "avg_color": photo.get("avg_color"),
        "query": query,
    }