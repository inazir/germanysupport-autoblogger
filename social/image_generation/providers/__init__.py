"""
social/image_generation/providers/__init__.py

Registry of all available image generation providers.
"""

from social.image_generation.providers.pollinations_provider import PollinationsProvider
from social.image_generation.providers.cloudflare_provider   import CloudflareProvider
from social.image_generation.providers.pexels_provider       import PexelsProvider
from social.image_generation.providers.openai_provider       import OpenAIProvider
from social.image_generation.providers.stability_provider    import StabilityProvider
from social.image_generation.providers.replicate_provider    import ReplicateProvider
from social.image_generation.providers.flux_provider         import FluxProvider

__all__ = [
    "PollinationsProvider",
    "CloudflareProvider",
    "PexelsProvider",
    "OpenAIProvider",
    "StabilityProvider",
    "ReplicateProvider",
    "FluxProvider",
]

# ---------------------------------------------------------------------------
# Provider registry — used by factory.py
# ---------------------------------------------------------------------------
PROVIDER_REGISTRY = {
    "pollinations": PollinationsProvider,
    "cloudflare":   CloudflareProvider,
    "pexels":       PexelsProvider,
    "openai":       OpenAIProvider,
    "stability":    StabilityProvider,
    "replicate":    ReplicateProvider,
    "flux":         FluxProvider,
}


def get_provider(name: str):
    """Return an instantiated provider by name, or raise ValueError."""
    provider_cls = PROVIDER_REGISTRY.get(name.lower())
    if not provider_cls:
        raise ValueError(f"Unknown image provider: '{name}'. Available: {list(PROVIDER_REGISTRY)}")
    return provider_cls()
