"""Backward-compatible imports for the unified image builder."""

from social.image_generation.image_builder import (
    DEFAULT_OUTPUT_DIR,
    REPO_ROOT,
    _add_glass_panel,
    _draw_text_with_shadow,
    _font,
    _load_logo,
    _paste_logo,
    _wrap,
    export_platform_image,
    generate_branded_image,
    generate_branded_image_v2,
)

__all__ = [
    "DEFAULT_OUTPUT_DIR",
    "REPO_ROOT",
    "export_platform_image",
    "generate_branded_image",
    "generate_branded_image_v2",
]
