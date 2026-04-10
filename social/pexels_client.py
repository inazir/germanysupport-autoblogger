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

    def _has_phrase(haystack: str, needle: str) -> bool:
        return needle in haystack

    def _score_keywords(text: str, keywords: list[str]) -> int:
        return sum(1 for keyword in keywords if _has_phrase(text, keyword))

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

    # Intent cues to make visual searches more relevant.
    saving_terms = [
        "save money",
        "cheaper",
        "reduce bill",
        "lower bill",
        "save on",
        "kosten sparen",
        "günstiger",
        "billiger",
        "sparen",
    ]
    compare_terms = [
        "compare",
        "comparison",
        "vs",
        "best provider",
        "anbieter wechseln",
        "wechseln",
        "switch",
        "tariff",
        "tarif",
    ]
    apply_terms = [
        "apply",
        "application",
        "documents required",
        "required documents",
        "checklist",
        "appointment",
        "termin",
        "beantragen",
        "unterlagen",
    ]
    family_terms = [
        "family",
        "child",
        "children",
        "kids",
        "parent",
        "parents",
        "familie",
        "kind",
        "kinder",
    ]
    online_terms = [
        "online",
        "app",
        "smartphone",
        "digital",
        "website",
        "portal",
    ]

    has_saving = any(term in text for term in saving_terms)
    has_compare = any(term in text for term in compare_terms)
    has_apply = any(term in text for term in apply_terms)
    has_family = any(term in text for term in family_terms)
    has_online = any(term in text for term in online_terms)

    # Weighted topic rules. Title matches count more than summary/category matches.
    topic_rules: list[dict] = [
        {
            "name": "electricity",
            "keywords": [
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
                "gas tariff",
                "heating bill",
                "heizkosten",
                "nebenkosten",
            ],
            "base_query": "electricity meter home energy",
        },
        {
            "name": "solar",
            "keywords": [
                "solar",
                "photovoltaic",
                "pv",
                "renewable energy",
                "solar panel",
            ],
            "base_query": "solar panels modern house roof",
        },
        {
            "name": "tax",
            "keywords": [
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
            "base_query": "tax documents calculator desk paperwork",
        },
        {
            "name": "insurance",
            "keywords": [
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
                "rechtsschutz",
                "rechtschutz",
            ],
            "base_query": "insurance paperwork family home contract",
        },
        {
            "name": "visa",
            "keywords": [
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
            "base_query": "passport visa documents desk",
        },
        {
            "name": "registration",
            "keywords": [
                "anmeldung",
                "address registration",
                "bürgeramt",
                "wohnungsgeberbestätigung",
                "registration certificate",
                "bureaucracy",
                "documents required",
                "required documents",
                "appointment",
            ],
            "base_query": "documents paperwork office appointment",
        },
        {
            "name": "banking",
            "keywords": [
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
            "base_query": "online banking smartphone payment card",
        },
        {
            "name": "investing",
            "keywords": [
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
            "base_query": "personal finance savings smartphone card",
        },
        {
            "name": "telecom",
            "keywords": [
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
            "base_query": "smartphone sim card mobile internet",
        },
        {
            "name": "housing",
            "keywords": [
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
            "base_query": "apartment keys rental contract home",
        },
        {
            "name": "jobs",
            "keywords": [
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
            "base_query": "job interview laptop documents office",
        },
        {
            "name": "family",
            "keywords": [
                "kindergeld",
                "child benefit",
                "family benefit",
                "elterngeld",
                "parental allowance",
                "kita",
                "school",
                "childcare",
            ],
            "base_query": "family children home documents",
        },
        {
            "name": "travel",
            "keywords": [
                "travel",
                "flight",
                "hotel",
                "holiday",
                "urlaub",
                "vacation",
                "train",
                "deutsche bahn",
                "bahncard",
                "transport",
                "ticket",
            ],
            "base_query": "travel suitcase train station",
        },
        {
            "name": "car",
            "keywords": [
                "car",
                "driving licence",
                "driver license",
                "führerschein",
                "vehicle registration",
                "auto insurance",
                "parking",
                "tuv",
                "tüv",
            ],
            "base_query": "car keys documents",
        },
        {
            "name": "medical",
            "keywords": [
                "doctor",
                "hospital",
                "medical",
                "clinic",
                "appointment",
                "health card",
                "krankenkasse",
            ],
            "base_query": "doctor appointment medical documents",
        },
        {
            "name": "deal",
            "keywords": [
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
            "base_query": "shopping discount online deal",
        },
    ]

    best_rule = None
    best_score = 0

    for rule in topic_rules:
        keywords = rule["keywords"]

        score = 0
        score += _score_keywords(title, keywords) * 5
        score += _score_keywords(summary, keywords) * 3
        score += _score_keywords(promo, keywords) * 2
        score += _score_keywords(category, keywords) * 3
        score += _score_keywords(content_type, keywords) * 1

        if score > best_score:
            best_score = score
            best_rule = rule

    if best_rule:
        topic = best_rule["name"]
        query = best_rule["base_query"]

        # Intent-sensitive refinements
        if topic == "electricity":
            if has_compare:
                return "energy comparison laptop calculator home"
            if has_saving:
                return "electricity meter home savings"
            return query

        if topic == "solar":
            if has_saving:
                return "solar panels house energy savings"
            return query

        if topic == "tax":
            if "refund" in text or "erstattung" in text:
                return "tax refund calculator paperwork desk"
            if has_online:
                return "online tax documents laptop desk"
            return query

        if topic == "insurance":
            if has_family:
                return "family insurance paperwork home"
            if has_compare:
                return "insurance comparison paperwork laptop"
            return query

        if topic == "visa":
            if has_apply:
                return "passport visa application documents desk"
            return query

        if topic == "registration":
            if has_apply:
                return "office appointment paperwork documents"
            return query

        if topic == "banking":
            if has_online:
                return "mobile banking smartphone payment"
            if "transfer" in text or "remittance" in text:
                return "money transfer smartphone app"
            return query

        if topic == "investing":
            if "etf" in text or "broker" in text or "stock market" in text:
                return "investing app smartphone finance"
            return query

        if topic == "telecom":
            if "esim" in text:
                return "smartphone esim mobile setup"
            return query

        if topic == "housing":
            if "wg" in text:
                return "apartment shared living rental home"
            if has_family:
                return "apartment family home keys"
            return query

        if topic == "jobs":
            if "salary" in text or "brutto netto" in text or "gross net" in text:
                return "salary calculator laptop desk"
            return query

        if topic == "family":
            if has_apply:
                return "family documents home paperwork"
            return query

        if topic == "travel":
            if has_saving or has_compare:
                return "travel planning budget laptop"
            if "train" in text or "bahn" in text:
                return "train station travel ticket"
            return query

        if topic == "car":
            if "parking" in text:
                return "car parking city street"
            return query

        if topic == "medical":
            if has_apply:
                return "doctor appointment paperwork clinic"
            return query

        if topic == "deal":
            return "shopping discount online deal"

        return query

    if "deal" in category or "deal" in content_type:
        return "shopping discount online deal"

    if "finance" in category:
        return "banking documents calculator"

    if "insurance" in category:
        return "insurance paperwork family home"

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