from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from social.models import SocialPost


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "social" / "cache" / "generated_images"

SOCIAL_LOGO_PATH = os.getenv(
    "SOCIAL_LOGO_PATH",
    str(REPO_ROOT / "social" / "assets" / "germanysupport_logo.png"),
)

SOCIAL_FONT_REGULAR_PATH = os.getenv("SOCIAL_FONT_REGULAR_PATH", "").strip()
SOCIAL_FONT_BOLD_PATH = os.getenv("SOCIAL_FONT_BOLD_PATH", "").strip()


def _font(size: int, bold: bool = False):
    """
    Load font with priority:
    1. ENV-configured font paths
    2. Repo-local fonts
    3. System fallbacks
    4. PIL default
    """
    candidates = []

    env_path = SOCIAL_FONT_BOLD_PATH if bold else SOCIAL_FONT_REGULAR_PATH
    if env_path:
        candidates.append(env_path)

    repo_fonts_dir = REPO_ROOT / "social" / "assets" / "fonts"
    candidates.append(str(repo_fonts_dir / ("Roboto-Bold.ttf" if bold else "Roboto-Regular.ttf")))
    candidates.append(str(repo_fonts_dir / ("roboto-bold.ttf" if bold else "roboto-regular.ttf")))

    candidates.extend(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
    )

    for path in candidates:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue

    print("WARNING: Falling back to default PIL font")
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return []

    lines: list[str] = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
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


def _fit_title(draw: ImageDraw.ImageDraw, title: str, max_width: int, max_lines: int = 3):
    for size in [104, 96, 88, 80, 72, 66, 60]:
        font = _font(size, bold=True)
        lines = _wrap(draw, title, font, max_width)
        if len(lines) <= max_lines:
            return font, lines[:max_lines]

    font = _font(56, bold=True)
    lines = _wrap(draw, title, font, max_width)[:max_lines]
    if lines:
        lines[-1] = _truncate_line(lines[-1], 34)
    return font, lines


def _fit_summary(draw: ImageDraw.ImageDraw, summary: str, max_width: int, max_lines: int = 2):
    for size in [38, 36, 34, 32]:
        font = _font(size, bold=False)
        lines = _wrap(draw, summary, font, max_width)
        if len(lines) <= max_lines:
            return font, lines[:max_lines]

    font = _font(30, bold=False)
    lines = _wrap(draw, summary, font, max_width)[:max_lines]
    if lines:
        lines[-1] = _truncate_line(lines[-1], 48)
    return font, lines


def _hash_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _make_fallback_background(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), (5, 10, 30))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, size, size), fill=(5, 10, 30))
    draw.ellipse((-200, -120, 780, 700), fill=(22, 56, 120, 60))
    draw.ellipse((300, 120, 1250, 1080), fill=(10, 96, 180, 40))
    draw.rectangle((0, 700, size, size), fill=(3, 8, 22, 110))
    return image


def _load_background(background_image_path: str | None, size: int) -> Image.Image:
    if background_image_path and Path(background_image_path).exists():
        try:
            bg = Image.open(background_image_path).convert("RGB")
            w, h = bg.size
            scale = max(size / w, size / h) * 1.08
            new_w = int(w * scale)
            new_h = int(h * scale)
            bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left = max((new_w - size) // 2, 0)
            top = max((new_h - size) // 2, 0)
            return bg.crop((left, top, left + size, top + size))
        except Exception:
            pass

    return _make_fallback_background(size)


def _add_vertical_gradient_overlay(
    image: Image.Image,
    top_rgba=(6, 10, 22, 40),
    bottom_rgba=(4, 8, 18, 220),
) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px = overlay.load()

    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top_rgba[0] * (1 - t) + bottom_rgba[0] * t)
        g = int(top_rgba[1] * (1 - t) + bottom_rgba[1] * t)
        b = int(top_rgba[2] * (1 - t) + bottom_rgba[2] * t)
        a = int(top_rgba[3] * (1 - t) + bottom_rgba[3] * t)
        for x in range(width):
            px[x, y] = (r, g, b, a)

    image.alpha_composite(overlay)


def _add_left_dark_fade(image: Image.Image, max_alpha: int = 65) -> None:
    width, height = image.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px = overlay.load()

    for x in range(width):
        t = min(x / (width * 0.70), 1.0)
        alpha = int(max_alpha * (1 - t))
        for y in range(height):
            px[x, y] = (0, 0, 0, alpha)

    image.alpha_composite(overlay)


def _draw_badge(draw: ImageDraw.ImageDraw, text: str, x_right: int, y_top: int, font) -> None:
    text = _truncate_line((text or "").upper(), 24)
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    pad_x = 24
    pad_y = 12
    x1 = x_right - width - pad_x * 2
    y1 = y_top
    x2 = x_right
    y2 = y_top + height + pad_y * 2

    draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(255, 255, 255, 245))
    draw.text((x1 + pad_x, y1 + pad_y - 1), text, fill=(29, 78, 216), font=font)


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
    bg = Image.new("RGBA", (w + pad * 2, h + pad * 2), (255, 255, 255, 238))

    mask = Image.new("L", bg.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, bg.size[0], bg.size[1]), radius=22, fill=255)

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
    x, y = pos
    sx, sy = shadow_offset
    draw.text((x + sx, y + sy), text, font=font, fill=shadow_fill)
    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill if stroke_width > 0 else None,
    )


def generate_branded_image(
    post: SocialPost,
    brand_text: str,
    output_dir: str | Path | None = None,
    filename_prefix: Optional[str] = None,
) -> str:
    out_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{filename_prefix or 'social'}_{_hash_name(post.external_id)}.png"
    output_path = out_dir / file_name

    size = 1080
    bg_path = getattr(post, "background_image_path", None)

    image = _load_background(bg_path, size).convert("RGBA")
    _add_vertical_gradient_overlay(image)
    _add_left_dark_fade(image)

    draw = ImageDraw.Draw(image, "RGBA")

    draw.rounded_rectangle(
        (44, 44, size - 44, size - 44),
        radius=44,
        outline=(255, 255, 255, 64),
        width=2,
    )

    # Header
    header_top = 72
    header_bottom = 190
    header_left = 66
    header_right = size - 66

    draw.rounded_rectangle(
        (header_left, header_top, header_right, header_bottom),
        radius=34,
        fill=(7, 18, 45, 178),
    )

    draw.rounded_rectangle(
        (header_left, header_top, header_left + 22, header_bottom),
        radius=14,
        fill=(59, 130, 246, 255),
    )

    brand_font = _font(34, bold=True)
    badge_font = _font(24, bold=True)
    footer_font = _font(22, bold=False)
    footer_bold = _font(26, bold=True)

    logo = _load_logo()
    brand_x = 112
    brand_y = 101

    if logo:
        _paste_logo(image, logo, 92, 82)
        brand_x = 230

    _draw_text_with_shadow(
        draw,
        (brand_x, brand_y),
        brand_text,
        font=brand_font,
        fill=(255, 255, 255),
        shadow_fill=(0, 0, 0, 110),
        shadow_offset=(2, 3),
    )

    badge = (getattr(post, "category_label", None) or getattr(post, "content_type", None) or "ARTICLE").strip()
    _draw_badge(draw, badge, x_right=size - 98, y_top=94, font=badge_font)

    # Main content panel
    panel_left = 68
    panel_top = 420      # was 500
    panel_right = size - 68
    panel_bottom = 950   # was 900

    draw.rounded_rectangle(
        (panel_left, panel_top, panel_right, panel_bottom),
        radius=40,
        fill=(7, 18, 45, 162),
    )

    draw.rounded_rectangle(
        (panel_left + 24, panel_top + 28, panel_left + 42, panel_bottom - 28),
        radius=10,
        fill=(59, 130, 246, 255),
    )

    inner_left = panel_left + 66
    inner_right = panel_right - 48
    title_max_width = inner_right - inner_left

    # Fixed footer height reservation
    footer_height = 62
    footer_y = panel_bottom - footer_height

    # --- MEASURE everything before drawing ---

    title_font, title_lines = _fit_title(draw, post.title or "", max_width=title_max_width, max_lines=3)

    # Measure total title block height
    title_line_heights = []
    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font, stroke_width=3)
        title_line_heights.append(bbox[3] - bbox[1])
    title_line_gap = 10
    title_block_height = sum(title_line_heights) + title_line_gap * (len(title_line_heights) - 1)

    summary = (getattr(post, "promo_text", None) or post.summary or "").strip()
    summary_font = summary_lines = None
    summary_block_height = 0
    summary_line_heights = []
    summary_line_gap = 8

    if summary:
        summary_font, summary_lines = _fit_summary(draw, summary, max_width=title_max_width, max_lines=2)
        for line in summary_lines:
            bbox = draw.textbbox((0, 0), line, font=summary_font, stroke_width=1)
            summary_line_heights.append(bbox[3] - bbox[1])
        summary_block_height = sum(summary_line_heights) + summary_line_gap * (len(summary_line_heights) - 1)

    # Gap between title and summary — scales with title font size
    title_summary_gap = max(24, title_font.size // 3)

    # Total content height
    total_content_height = title_block_height
    if summary_block_height:
        total_content_height += title_summary_gap + summary_block_height

    # Available vertical space inside panel (between top padding and footer)
    panel_content_top = panel_top + 52
    panel_content_bottom = footer_y - 16
    available_height = panel_content_bottom - panel_content_top

    # Vertically centre content if it fits; otherwise pin to top
    if total_content_height <= available_height:
        start_y = panel_content_top + (available_height - total_content_height) // 2
    else:
        start_y = panel_content_top

    # --- DRAW title ---
    y = start_y
    for i, line in enumerate(title_lines):
        _draw_text_with_shadow(
            draw,
            (inner_left, y),
            line,
            font=title_font,
            fill=(255, 255, 255),
            shadow_fill=(0, 0, 0, 200),
            shadow_offset=(4, 6),
            stroke_width=3,
            stroke_fill=(0, 0, 0, 232),
        )
        y += title_line_heights[i] + (title_line_gap if i < len(title_lines) - 1 else 0)

    # --- DRAW summary ---
    if summary_font and summary_lines:
        summary_y = y + title_summary_gap
        for i, line in enumerate(summary_lines):
            _draw_text_with_shadow(
                draw,
                (inner_left, summary_y),
                line,
                font=summary_font,
                fill=(224, 232, 242),
                shadow_fill=(0, 0, 0, 145),
                shadow_offset=(2, 3),
                stroke_width=1,
                stroke_fill=(0, 0, 0, 160),
            )
            summary_y += summary_line_heights[i] + (summary_line_gap if i < len(summary_lines) - 1 else 0)

    # Footer row — photo credit only
    photographer = getattr(post, "background_image_photographer", None)
    if photographer:
        credit = f"Photo: {photographer} / Pexels"
        credit_bbox = draw.textbbox((0, 0), credit, font=footer_font)
        credit_width = credit_bbox[2] - credit_bbox[0]
        credit_x = panel_right - 44 - credit_width
        _draw_text_with_shadow(
            draw,
            (credit_x, footer_y + 2),
            credit,
            font=footer_font,
            fill=(203, 213, 225),
            shadow_fill=(0, 0, 0, 110),
            shadow_offset=(1, 2),
        )

    image.convert("RGB").save(output_path, format="PNG")
    return str(output_path)