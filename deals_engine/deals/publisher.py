from typing import Optional, Tuple
import requests


class WordPressDealPublisher:
    def __init__(
        self,
        wp_url: str,
        username: str,
        app_password: str,
        category_id: int,
        default_status: str = "draft",
        lang_field: str = "lang",
    ):
        self.base = wp_url.rstrip("/")
        self.auth = (username, app_password)
        self.category_id = category_id
        self.default_status = default_status
        self.lang_field = lang_field

    def _build_payload(
        self,
        title: str,
        excerpt: str,
        content: str,
        language: str,
        slug: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        payload = {
            "title": title,
            "excerpt": excerpt,
            "content": content,
            "status": status or self.default_status,
            "categories": [self.category_id],
            # Common Polylang REST field.
            self.lang_field: language,
            # Helpful fallback for sites/plugins expecting a different key.
            "language": language,
        }
        if slug:
            payload["slug"] = slug
        return payload

    def publish(
        self,
        title: str,
        excerpt: str,
        content: str,
        language: str,
        slug: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        payload = self._build_payload(
            title=title,
            excerpt=excerpt,
            content=content,
            language=language,
            slug=slug,
            status=status,
        )
        response = requests.post(
            f"{self.base}/wp-json/wp/v2/posts",
            auth=self.auth,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


def resolve_category_id(wp_url: str, username: str, app_password: str, slug: str) -> int:
    response = requests.get(
        f"{wp_url.rstrip('/')}/wp-json/wp/v2/categories",
        auth=(username, app_password),
        params={"slug": slug, "per_page": 100},
        timeout=30,
    )
    response.raise_for_status()
    items = response.json()
    if not items:
        raise RuntimeError(f"WordPress category slug not found: {slug}")
    return int(items[0]["id"])
