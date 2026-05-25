"""
social/image_generation/factory.py

ImageProviderFactory: reads .env, instantiates providers, builds fallback chain.

Environment variables
---------------------
IMAGE_PROVIDER          : primary provider  (default: pollinations)
IMAGE_FALLBACK_PROVIDER : fallback provider (default: pollinations)
POLLINATIONS_ENABLED    : true/false        (default: true)
OPENAI_API_KEY          : required for openai provider
STABILITY_API_KEY       : required for stability provider
REPLICATE_API_TOKEN     : required for replicate provider
FLUX_API_KEY            : required for flux provider
"""
from __future__ import annotations

import importlib
import os
from typing import List, Optional

from social.image_generation.base import BaseImageProvider


# ---------------------------------------------------------------------------
# Registry
# All provider names map to their full dotted class path.
# Add new providers here — nothing else needs to change.
# ---------------------------------------------------------------------------
_PROVIDER_REGISTRY: dict[str, str] = {
    "pollinations": "social.image_generation.providers.pollinations_provider.PollinationsProvider",
    "pexels":       "social.image_generation.providers.pexels_provider.PexelsProvider",
    "openai":       "social.image_generation.providers.openai_provider.OpenAIProvider",
    "stability":    "social.image_generation.providers.stability_provider.StabilityProvider",
    "replicate":    "social.image_generation.providers.replicate_provider.ReplicateProvider",
    "flux":         "social.image_generation.providers.flux_provider.FluxProvider",
}


def _load_provider(name: str) -> Optional[BaseImageProvider]:
    """
    Dynamically import and instantiate a provider by name.
    Returns None if the name is unknown or the import fails.
    """
    class_path = _PROVIDER_REGISTRY.get(name.lower())
    if not class_path:
        print(f"  [factory] Unknown provider: '{name}' — skipping")
        return None

    module_path, class_name = class_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        instance: BaseImageProvider = cls()
        return instance
    except Exception as exc:
        print(f"  [factory] Failed to load provider '{name}': {exc}")
        return None


class ImageProviderFactory:
    """
    Builds an ordered list of providers from .env config.
    Providers are checked for availability before being added to the chain.
    """

    @staticmethod
    def build_provider_chain() -> List[BaseImageProvider]:
        """
        Returns [primary, fallback, ...] in priority order.
        Unavailable or unknown providers are silently skipped.
        Pollinations is always appended as last-resort if nothing else works.
        """
        primary_name  = os.getenv("IMAGE_PROVIDER",          "pollinations").strip().lower()
        fallback_name = os.getenv("IMAGE_FALLBACK_PROVIDER",  "pollinations").strip().lower()

        seen: set[str]            = set()
        chain: List[BaseImageProvider] = []

        for name in [primary_name, fallback_name]:
            if name in seen:
                continue
            seen.add(name)
            provider = _load_provider(name)
            if provider and provider.is_available():
                chain.append(provider)
                print(f"  [factory] Provider ready: {provider.provider_name}")
            else:
                reason = "unavailable" if provider else "unknown/import-failed"
                print(f"  [factory] Skipped '{name}' ({reason})")

        # Always ensure pollinations is available as final fallback
        if not any(p.provider_name == "pollinations" for p in chain):
            fallback = _load_provider("pollinations")
            if fallback and fallback.is_available():
                chain.append(fallback)
                print("  [factory] Pollinations appended as last-resort fallback")

        if not chain:
            print("  [factory] WARNING: No image providers available")

        return chain

    @staticmethod
    def list_registered_providers() -> List[str]:
        return list(_PROVIDER_REGISTRY.keys())
