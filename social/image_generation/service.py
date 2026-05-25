"""
social/image_generation/service.py

ImageGenerationService — the ONLY entry point used by all modules.

Usage (anywhere in the project):
    from social.image_generation.service import ImageGenerationService

    # Get a URL
    url = ImageGenerationService.generate(prompt)

    # Get a local file path (downloads the image)
    path = ImageGenerationService.generate_to_file(prompt, filename_prefix="news")
"""
from __future__ import annotations

import time
from typing import List, Optional

from social.image_generation.base import BaseImageProvider


class ImageGenerationService:
    """
    Singleton-style service (class methods only — no instantiation needed).
    Provider chain is built lazily on first call and cached for the process lifetime.
    """

    _chain: Optional[List[BaseImageProvider]] = None
    _initialized: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def generate(cls, prompt: str, context: dict = None) -> Optional[str]:
        """
        Generate an image for the given prompt.

        Returns
        -------
        str  : image URL on success
        None : if all providers fail — caller must handle gracefully
        """
        if not prompt or not prompt.strip():
            print("  [ImageService] Empty prompt — skipping image generation")
            return None

        chain = cls._get_chain()
        if not chain:
            print("  [ImageService] No providers configured — returning None")
            return None

        t_start = time.monotonic()

        for i, provider in enumerate(chain):
            label = "primary" if i == 0 else "fallback"
            print(f"  [ImageService] Trying {label} provider: {provider.provider_name}")

            try:
                result = provider.generate_image(prompt)
                
                # -------------------------------
                # NORMALIZATION LAYER (NEW)
                # -------------------------------
                if isinstance(result, dict):
                    url = result.get("url")
                
                    # attach metadata to post if available
                    if context is not None:
                        context.setdefault("image_metadata", {})
                        context["image_metadata"] = {
                            "provider": provider.provider_name,
                            "photographer": result.get("photographer"),
                            "photographer_url": result.get("photographer_url"),
                            "source": result.get("source"),
                        }
                else:
                    url = result
            except Exception as exc:
                print(f"  [ImageService] {provider.provider_name} raised unexpectedly: {exc}")
                url = None

            if url:
                elapsed = time.monotonic() - t_start
                print(
                    f"  [ImageService] Success via {provider.provider_name} "
                    f"({elapsed:.2f}s)"
                )
                return url

            print(f"  [ImageService] {provider.provider_name} returned None")
            if i < len(chain) - 1:
                print(f"  [ImageService] Falling back to: {chain[i + 1].provider_name}")

        elapsed = time.monotonic() - t_start
        print(f"  [ImageService] All providers failed after {elapsed:.2f}s — returning None")
        return None

    @classmethod
    def generate_to_file(
        cls,
        prompt: str,
        filename_prefix: str = "ai",
        context: dict = None,
    ) -> Optional[str]:
        """
        Generate an image and save it to the local cache folder.

        Returns local file path string, or None on failure.
        This is more useful than generate() when you need a file on disk
        (e.g. for branded image background, or Instagram upload).
        """
        url = cls.generate(prompt, context=context)
        if not url:
            return None
        return cls.download_to_cache(url, filename_prefix=filename_prefix)

    @classmethod
    def download_to_cache(
        cls,
        image_url: str,
        filename_prefix: str = "ai",
    ) -> Optional[str]:
        """
        Download a remote image URL into the Pexels/generated_images cache folder.

        Returns local path string, or None on failure.
        """
        import hashlib
        import requests
        from pathlib import Path

        # Use the same output dir as the image builders
        try:
            from social.image_builder import DEFAULT_OUTPUT_DIR
        except Exception:
            from pathlib import Path as _P
            DEFAULT_OUTPUT_DIR = _P(__file__).resolve().parents[2] / "social" / "cache" / "generated_images"

        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()

            digest   = hashlib.sha256(image_url.encode()).hexdigest()[:16]
            filename = f"{filename_prefix}_{digest}_ai.jpg"
            out_path = Path(DEFAULT_OUTPUT_DIR) / filename
            out_path.parent.mkdir(parents=True, exist_ok=True)

            out_path.write_bytes(resp.content)
            print(f"  [ImageService] Cached AI image → {out_path}")
            return str(out_path)

        except Exception as e:
            print(f"  [ImageService] download_to_cache failed: {e}")
            return None

    @classmethod
    def reset(cls) -> None:
        """Force re-initialisation of the provider chain (useful in tests)."""
        cls._chain       = None
        cls._initialized = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @classmethod
    def _get_chain(cls) -> List[BaseImageProvider]:
        if not cls._initialized:
            from social.image_generation.factory import ImageProviderFactory
            cls._chain       = ImageProviderFactory.build_provider_chain()
            cls._initialized = True
        return cls._chain or []
