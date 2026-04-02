from .db import has_dedupe_hash


def is_duplicate(dedupe_hash: str, language: str) -> bool:
    return has_dedupe_hash(dedupe_hash, language)
