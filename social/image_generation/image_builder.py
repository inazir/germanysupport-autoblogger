"""
social/image_generation/image_builder.py

Parameterised branded image builder.

This is the NEW builder. The original social/image_builder.py is
NOT modified — it continues to serve articles and tips.

Use this for: daily news, tips (future), deals (future), any new module.

Quick usage
-----------
from social.image_generation.image_builder import generate_branded_image_v2

# News
path = generate_branded_image_v2(post, brand_text="GermanySupport.de", layout="news")

# Tips (no summary text on image)
path = generate_branded_image_v2(post, brand_text="GermanySupport.de", layout="tip")

# Deal with custom CTA
path = generate_branded_image_v2(
    post, brand_text="GermanySupport.de",
    layout="deal", cta_text="View deal now →"
)

Layout presets
--------------
layout      show_summary    default CTA
article     True            Read full guide on GermanySupport.de
news        True            Read the full story at GermanySupport.de
tip         False           Follow GermanySupport for daily Germany tips
deal        True            View deal at GermanySupport.de
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from social.models import SocialPost


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "social" / "cache" / "generated_images"

SOCIAL_LOGO_PATH         = os.getenv(
    "SOCIAL_LOGO_PATH",
    str(REPO_ROOT / "social" / "assets" / "germanysupport_logo.png"),
)
SOCIAL_FONT_REGULAR_PATH = os.getenv("SOCIAL_FONT_REGULAR_PATH", "").strip()
SOCIAL_FONT_BOLD_PATH    = os.getenv("SOCIAL_FONT_BOLD_PATH",    "").strip()
SOCIAL_FONT_BENGALI_REGULAR_PATH = os.getenv("SOCIAL_FONT_BENGALI_REGULAR_PATH", "").strip()
SOCIAL_FONT_BENGALI_BOLD_PATH = os.getenv("SOCIAL_FONT_BENGALI_BOLD_PATH", "").strip()

# NEW: Image provider mode
SOCIAL_IMAGE_BACKGROUND = os.getenv("SOCIAL_IMAGE_BACKGROUND", "").strip().lower()


# ---------------------------------------------------------------------------
# Layout presets
# ---------------------------------------------------------------------------
_LAYOUT_DEFAULTS: dict[str, dict] = {
    "article": {
        "cta_text":     "Read full guide on GermanySupport.de",
        "show_summary": True,
    },
    "news": {
        "cta_text":     "Read the full story at GermanySupport.de",
        "show_summary": True,
    },
    "tip": {
        "cta_text":     "Follow GermanySupport for daily Germany tips 🇩🇪",
        "show_summary": False,
    },
    "deal": {
        "cta_text":     "View deal at GermanySupport.de",
        "show_summary": True,
    },
}


# ---------------------------------------------------------------------------
# Font loader — identical priority logic to social/image_builder.py
# ---------------------------------------------------------------------------
def _contains_bengali(text: str) -> bool:
    return any("\u0980" <= char <= "\u09ff" for char in text)


def _text_options(text: str) -> dict:
    if _contains_bengali(text):
        return {"direction": "ltr", "language": "bn"}
    return {}


def _textbbox(draw: ImageDraw.ImageDraw, text: str, font, **kwargs):
    options = _text_options(text)
    options.update(kwargs)
    try:
        return draw.textbbox((0, 0), text, font=font, **options)
    except (TypeError, ValueError):
        return draw.textbbox((0, 0), text, font=font)


def _draw_text(draw: ImageDraw.ImageDraw, position, text: str, font, **kwargs) -> None:
    options = _text_options(text)
    options.update(kwargs)
    try:
        draw.text(position, text, font=font, **options)
    except (TypeError, ValueError):
        draw.text(position, text, font=font, **kwargs)


def render_bengali_text_card(
    text: str,
    font_path: str,
    font_size: int = 62,
    text_color=(255, 255, 255, 255),
    bg_color=(0, 0, 0, 0),
    padding: int = 20,
) -> Image.Image:
    """Render shaped Bengali text into a transparent PNG-ready RGBA image."""
    font = ImageFont.truetype(font_path, font_size, layout_engine=ImageFont.Layout.RAQM)
    lines = (text or "").splitlines() or [""]
    probe = Image.new("RGBA", (4096, 4096), bg_color)
    probe_draw = ImageDraw.Draw(probe)
    boxes = [_textbbox(probe_draw, line, font) for line in lines]
    width = max((box[2] - box[0] for box in boxes), default=0) + padding * 2
    line_height = max((box[3] - box[1] for box in boxes), default=font_size)
    height = line_height * len(lines) + padding * 2
    image = Image.new("RGBA", (max(width, 1), max(height, 1)), bg_color)
    draw = ImageDraw.Draw(image)
    y = padding
    for line, box in zip(lines, boxes):
        x = (image.width - (box[2] - box[0])) // 2
        _draw_text(
            draw,
            (x, y),
            line,
            font=font,
            fill=text_color,
            stroke_width=3,
            stroke_fill=(0, 0, 0, 190),
        )
        y += line_height
    return image


def _has_ai_background(post: SocialPost) -> bool:
    provider = (getattr(post, "background_image_provider", None) or "").lower()
    if provider:
        return provider != "pexels"
    background_path = Path(getattr(post, "background_image_path", "") or "")
    return background_path.is_file() and background_path.stem.endswith("_ai")


def _font(size: int, bold: bool = False, text: str = ""):
    candidates: list[str] = []

    if _contains_bengali(text):
        bengali_env_path = (
            SOCIAL_FONT_BENGALI_BOLD_PATH if bold else SOCIAL_FONT_BENGALI_REGULAR_PATH
        )
        if bengali_env_path:
            candidates.append(bengali_env_path)
        repo_fonts = REPO_ROOT / "social" / "assets" / "fonts"
        candidates.extend(
            [
                str(repo_fonts / "NotoSansBengali.ttf"),
                str(repo_fonts / ("NotoSansBengali-Bold.ttf" if bold else "NotoSansBengali-Regular.ttf")),
                "/usr/share/fonts/truetype/noto/NotoSansBengali.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
            ]
        )

    env_path = SOCIAL_FONT_BOLD_PATH if bold else SOCIAL_FONT_REGULAR_PATH
    if env_path:
        candidates.append(env_path)

    repo_fonts = REPO_ROOT / "social" / "assets" / "fonts"
    candidates.append(str(repo_fonts / ("Roboto-Bold.ttf"    if bold else "Roboto-Regular.ttf")))
    candidates.append(str(repo_fonts / ("roboto-bold.ttf"    if bold else "roboto-regular.ttf")))
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"           if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"  if bold else
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]

    for path in candidates:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue

    print("WARNING [image_builder_v2]: Falling back to default PIL font")
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# NEW: Attribution logic (Pexels only)
# ---------------------------------------------------------------------------
def _should_add_pexels_credit(post: SocialPost) -> bool:
    return SOCIAL_IMAGE_BACKGROUND in {"pexels", "ai_with_pexels_fallback"} and bool(
        getattr(post, "background_image_photographer", None)
    )


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return []
    lines:   list[str] = []
    current: str       = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        bbox = _textbbox(draw, candidate, font)
        if (bbox[2] - bbox[0]) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _truncate_line(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _fit_title(draw, title: str, max_width: int, max_lines: int = 3):
    for size in [104, 96, 88, 80, 72, 66, 60]:
        font  = _font(size, bold=True, text=title)
        lines = _wrap(draw, title, font, max_width)
        if len(lines) <= max_lines:
            return font, lines[:max_lines]
    font  = _font(56, bold=True, text=title)
    lines = _wrap(draw, title, font, max_width)[:max_lines]
    if lines:
        lines[-1] = _truncate_line(lines[-1], 34)
    return font, lines


def _fit_summary(draw, summary: str, max_width: int, max_lines: int = 2):
    for size in [38, 36, 34, 32]:
        font  = _font(size, bold=False, text=summary)
        lines = _wrap(draw, summary, font, max_width)
        if len(lines) <= max_lines:
            return font, lines[:max_lines]
    font  = _font(30, bold=False, text=summary)
    lines = _wrap(draw, summary, font, max_width)[:max_lines]
    if lines:
        lines[-1] = _truncate_line(lines[-1], 48)
    return font, lines


def _hash_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Background helpers
# ---------------------------------------------------------------------------
def _make_fallback_background(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), (7, 14, 30))
    draw  = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, size, size),    fill=(7,  14,  30,  255))
    draw.ellipse((-200, -120, 780, 700),  fill=(44, 88,  180, 60))
    draw.ellipse((300,   120, 1250, 1080), fill=(30, 120, 220, 40))
    draw.rectangle((0, 700, size, size),  fill=(4,  10,  24,  60))
    return image


def _load_background(background_image_path: str | None, size: int) -> Image.Image:
    if background_image_path and Path(background_image_path).exists():
        try:
            bg    = Image.open(background_image_path).convert("RGB")
            w, h  = bg.size
            scale = max(size / w, size / h) * 1.08
            new_w, new_h = int(w * scale), int(h * scale)
            bg    = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left  = max((new_w - size) // 2, 0)
            top   = max((new_h - size) // 2, 0)
            return bg.crop((left, top, left + size, top + size))
        except Exception:
            pass
    return _make_fallback_background(size)


def _add_vertical_gradient_overlay(
    image: Image.Image,
    top_rgba=(8, 14, 28, 2),
    bottom_rgba=(5, 10, 20, 28),
) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px      = overlay.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        px_val = (
            int(top_rgba[0] * (1 - t) + bottom_rgba[0] * t),
            int(top_rgba[1] * (1 - t) + bottom_rgba[1] * t),
            int(top_rgba[2] * (1 - t) + bottom_rgba[2] * t),
            int(top_rgba[3] * (1 - t) + bottom_rgba[3] * t),
        )
        for x in range(width):
            px[x, y] = px_val
    image.alpha_composite(overlay)


def _add_left_dark_fade(image: Image.Image, max_alpha: int = 4) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px      = overlay.load()
    for x in range(width):
        alpha = int(max_alpha * (1 - min(x / (width * 0.62), 1.0)))
        for y in range(height):
            px[x, y] = (0, 0, 0, alpha)
    image.alpha_composite(overlay)


def _load_logo(max_w: int = 104, max_h: int = 104) -> Image.Image | None:
    logo_path = Path(SOCIAL_LOGO_PATH)
    if not logo_path.exists():
        return None
    try:
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        return logo
    except Exception:
        return None


def _paste_logo(base: Image.Image, logo: Image.Image, x: int, y: int) -> None:
    pad = 12
    w, h = logo.size
    bg   = Image.new("RGBA", (w + pad * 2, h + pad * 2), (255, 255, 255, 220))
    mask = Image.new("L", bg.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, bg.size[0], bg.size[1]), radius=22, fill=255)
    rounded_bg = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    rounded_bg.paste(bg, (0, 0), mask)
    rounded_bg.alpha_composite(logo, (pad, pad))
    base.alpha_composite(rounded_bg, (x, y))


def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    pos: tuple[int, int],
    text: str,
    font,
    fill,
    shadow_fill=(0, 0, 0, 180),
    shadow_offset=(3, 4),
    stroke_width: int = 0,
    stroke_fill=(0, 0, 0, 220),
) -> None:
    x, y   = pos
    sx, sy = shadow_offset
    _draw_text(draw, (x + sx, y + sy), text, font=font, fill=shadow_fill)
    _draw_text(
        draw, (x, y), text, font=font, fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill if stroke_width > 0 else None,
    )


def _add_glass_panel(
    base: Image.Image,
    box: tuple[int, int, int, int],
    *,
    radius: int = 40,
    blur_radius: int = 18,
    fill=(20, 30, 60, 55),
    edge=(255, 255, 255, 90),
    highlight_alpha: int = 22,
) -> None:
    x1, y1, x2, y2 = box
    width, height   = x2 - x1, y2 - y1
    if width <= 0 or height <= 0:
        return

    crop    = base.crop(box)
    blurred = crop.filter(ImageFilter.GaussianBlur(radius=blur_radius)).convert("RGBA")

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width, height), radius=radius, fill=255)

    panel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    panel.alpha_composite(blurred)
    panel.alpha_composite(Image.new("RGBA", (width, height), fill))

    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gpx      = gradient.load()
    for y in range(height):
        t     = y / max(height - 1, 1)
        alpha = int(10 * (1 - t) + 36 * t)
        for x in range(width):
            gpx[x, y] = (10, 18, 40, alpha)
    panel.alpha_composite(gradient)

    highlight = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(highlight, "RGBA").rectangle(
        (0, 0, width, int(height * 0.28)),
        fill=(255, 255, 255, highlight_alpha),
    )
    panel.alpha_composite(highlight)

    clipped = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    clipped.paste(panel, (0, 0), mask)
    base.alpha_composite(clipped, (x1, y1))

    draw = ImageDraw.Draw(base, "RGBA")
    draw.rounded_rectangle(box, radius=radius, outline=edge, width=1)
    draw.rounded_rectangle(
        (x1 + 1, y1 + 1, x2 - 1, y2 - 1),
        radius=radius, outline=(255, 255, 255, 24), width=1,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_branded_image_v2(
    post: SocialPost,
    brand_text: str,
    output_dir: str | Path | None = None,
    filename_prefix: Optional[str] = None,
    *,
    layout: str = "article",
    show_summary: Optional[bool] = None,
    cta_text: Optional[str] = None,
) -> str:
    brand_text = brand_text.replace("Brown Guy Germany", "BrownGuyGermany")
    follow_text = os.getenv("SOCIAL_IMAGE_FOLLOW_TEXT", "Follow @brownguygermany").strip()

    preset           = _LAYOUT_DEFAULTS.get(layout, _LAYOUT_DEFAULTS["article"])
    resolved_summary = show_summary if show_summary is not None else preset["show_summary"]
    resolved_cta     = (cta_text or "").strip() or preset["cta_text"]

    out_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix      = filename_prefix or layout
    file_name   = f"{prefix}_{_hash_name(post.external_id)}.png"
    output_path = out_dir / file_name

    size    = 1080
    bg_path = getattr(post, "background_image_path", None)

    # ---- canvas ----
    image = _load_background(bg_path, size).convert("RGBA")
    _add_vertical_gradient_overlay(image)
    _add_left_dark_fade(image)

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (44, 44, size - 44, size - 44),
        radius=44, outline=(255, 255, 255, 72), width=2,
    )

    # ---- header bar ----
    _add_glass_panel(
        image, (66, 72, size - 66, 190),
        radius=34, blur_radius=10,
        fill=(22, 32, 60, 28), edge=(255, 255, 255, 85), highlight_alpha=16,
    )

    draw = ImageDraw.Draw(image, "RGBA")

    brand_font  = _font(34, bold=True, text=brand_text)
    follow_font = _font(20, bold=False, text=follow_text)
    footer_font = _font(22, bold=False)

    logo    = _load_logo()
    brand_x = 112
    brand_y = 101
    if logo:
        _paste_logo(image, logo, 92, 82)
        brand_x = 230

    _draw_text_with_shadow(
        draw, (brand_x, brand_y), brand_text,
        font=brand_font, fill=(255, 255, 255),
        shadow_fill=(0, 0, 0, 55), shadow_offset=(2, 3),
    )
    if follow_text:
        _draw_text_with_shadow(
            draw, (brand_x, brand_y + 43), follow_text,
            font=follow_font, fill=(230, 236, 244, 225),
            shadow_fill=(0, 0, 0, 70), shadow_offset=(1, 2),
        )

    # ---- content panel ----
    panel_left, panel_top, panel_right, panel_bottom = 68, 470, size - 68, 980
    _add_glass_panel(
        image, (panel_left, panel_top, panel_right, panel_bottom),
        radius=40, blur_radius=4,
        fill=(22, 32, 60, 10), edge=(255, 255, 255, 78), highlight_alpha=10,
    )

    draw = ImageDraw.Draw(image, "RGBA")

    inner_left      = panel_left + 38
    inner_right     = panel_right - 42
    title_max_width = inner_right - inner_left
    footer_y        = panel_bottom - 110

    title_font, title_lines = _fit_title(draw, post.title or "", title_max_width)

    title_line_heights = [
        _textbbox(draw, line, title_font, stroke_width=4)[3]
        - _textbbox(draw, line, title_font, stroke_width=4)[1]
        for line in title_lines
    ]

    title_line_gap = 10
    title_block_h  = sum(title_line_heights) + title_line_gap * max(len(title_lines) - 1, 0)

    summary_font = summary_lines = None
    summary_block_h = 0
    summary_line_heights = []

    if resolved_summary:
        raw = (getattr(post, "promo_text", None) or post.summary or "").strip()
        if raw:
            summary_font, summary_lines = _fit_summary(draw, raw, title_max_width)
            for line in summary_lines:
                b = _textbbox(draw, line, summary_font, stroke_width=1)
                summary_line_heights.append(b[3] - b[1])
            summary_block_h = sum(summary_line_heights)

    total_content_h = title_block_h + summary_block_h
    start_y = panel_top + 52

    y = start_y
    for i, line in enumerate(title_lines):
        _draw_text_with_shadow(draw, (inner_left, y), line, title_font, (255, 255, 255))
        y += title_line_heights[i] + title_line_gap

    if summary_font and summary_lines:
        sy = y + 24
        for i, line in enumerate(summary_lines):
            _draw_text_with_shadow(draw, (inner_left, sy), line, summary_font, (238, 243, 250))
            sy += summary_line_heights[i] + 8

    # ---- CTA ----
    cta_font = _font(26, bold=True, text=resolved_cta)
    cta_box = (panel_left + 36, panel_bottom - 50, panel_right - 36, panel_bottom - 6)
    _add_glass_panel(image, cta_box, radius=22, blur_radius=10)

    cta_bbox = _textbbox(draw, resolved_cta, cta_font)
    cta_x = cta_box[0] + ((cta_box[2] - cta_box[0]) - (cta_bbox[2] - cta_bbox[0])) // 2
    cta_y = cta_box[1] + 8

    _draw_text_with_shadow(draw, (cta_x, cta_y), resolved_cta, cta_font, (255, 255, 255))

    # ---- PHOTO CREDIT (NEW: PEXELS ONLY) ----
    print("DEBUG provider:", SOCIAL_IMAGE_BACKGROUND)
    print("DEBUG photographer:", getattr(post, "background_image_photographer", None))
    print("DEBUG credit condition:", _should_add_pexels_credit(post))
    print("DEBUG post fields:", dir(post))
    print("DEBUG photographer raw:", getattr(post, "background_image_photographer", "MISSING"))
    if _should_add_pexels_credit(post):
        photographer = getattr(post, "background_image_photographer", None)
        if photographer:
            credit = f"Photo: {photographer} / Pexels"

            credit_bbox = _textbbox(draw, credit, footer_font)
            credit_w = credit_bbox[2] - credit_bbox[0]

            credit_x = size - 78 - credit_w
            credit_y = size - 82

            _draw_text_with_shadow(
                draw,
                (credit_x, credit_y),
                credit,
                font=footer_font,
                fill=(225, 232, 241),
                shadow_fill=(0, 0, 0, 90),
                shadow_offset=(1, 2),
            )

    if _has_ai_background(post):
        disclaimer = "AI Generated Image"
        disclaimer_font = _font(14, bold=False, text=disclaimer)
        disclaimer_bbox = _textbbox(draw, disclaimer, disclaimer_font)
        disclaimer_width = disclaimer_bbox[2] - disclaimer_bbox[0]
        disclaimer_height = disclaimer_bbox[3] - disclaimer_bbox[1]
        disclaimer_box = (
            size - disclaimer_width - 62,
            size - disclaimer_height - 42,
            size - 16,
            size - 12,
        )
        _add_glass_panel(
            image,
            disclaimer_box,
            radius=9,
            blur_radius=4,
            fill=(5, 10, 20, 145),
            edge=(255, 255, 255, 72),
            highlight_alpha=8,
        )
        draw = ImageDraw.Draw(image, "RGBA")
        draw.text(
            (disclaimer_box[0] + 23, disclaimer_box[1] + 5),
            disclaimer,
            font=disclaimer_font,
            fill=(235, 240, 246, 220),
        )

    image.convert("RGB").save(output_path, format="PNG")
    print(f"INFO [image_builder_v2]: saved → {output_path}")
    return str(output_path)


def generate_branded_image(
    post: SocialPost,
    brand_text: str,
    output_dir: str | Path | None = None,
    filename_prefix: Optional[str] = None,
    cta_text: Optional[str] = None,
) -> str:
    """Backward-compatible entry point for article, tip, and viral images."""
    return generate_branded_image_v2(
        post=post,
        brand_text=brand_text,
        output_dir=output_dir,
        filename_prefix=filename_prefix,
        layout="article",
        show_summary=True,
        cta_text=cta_text,
    )


def export_platform_image(
    source_path: str | Path,
    output_size: tuple[int, int],
    filename_prefix: str,
) -> str:
    source = Path(source_path)
    width, height = output_size
    output_path = source.parent / f"{filename_prefix}_{source.stem}_{width}x{height}.png"

    with Image.open(source) as source_image:
        image = source_image.convert("RGB")
        if image.size == output_size:
            image.save(output_path, format="PNG")
            return str(output_path)

        background = ImageOps.fit(image, output_size, method=Image.Resampling.LANCZOS)
        background = background.filter(ImageFilter.GaussianBlur(radius=24))
        overlay = Image.new("RGBA", output_size, (0, 0, 0, 70))
        background = Image.alpha_composite(background.convert("RGBA"), overlay)

        foreground = ImageOps.contain(image, output_size, method=Image.Resampling.LANCZOS)
        left = (width - foreground.width) // 2
        top = (height - foreground.height) // 2
        background.alpha_composite(foreground.convert("RGBA"), (left, top))
        background.convert("RGB").save(output_path, format="PNG")

    return str(output_path)
