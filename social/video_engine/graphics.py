from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    from social.image_generation.image_builder import (
        _draw_text_with_shadow,
        _font,
        _textbbox,
        _wrap,
    )
except ImportError:  # pragma: no cover - used only when optional image helpers are unavailable
    _draw_text_with_shadow = None
    _font = None
    _textbbox = None
    _wrap = None


def _contains_bengali(text: str) -> bool:
    return any("\u0980" <= char <= "\u09ff" for char in text)


def _fallback_font(size: int, bold: bool):
    configured = os.getenv(
        "SOCIAL_FONT_BENGALI_BOLD_PATH" if bold else "SOCIAL_FONT_BENGALI_REGULAR_PATH",
        "",
    ).strip()
    candidates = [
        configured,
        str(Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NotoSansBengali.ttf"),
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            return ImageFont.truetype(candidate, size=size, layout_engine=ImageFont.Layout.RAQM)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()


def _get_font(size: int, bold: bool, text: str):
    return _font(size, bold=bold, text=text) if _font else _fallback_font(size, bold)


def _bbox(draw: ImageDraw.ImageDraw, text: str, font):
    if _textbbox:
        return _textbbox(draw, text, font)
    options = {"direction": "ltr", "language": "bn"} if _contains_bengali(text) else {}
    try:
        return draw.textbbox((0, 0), text, font=font, **options)
    except (TypeError, ValueError):
        return draw.textbbox((0, 0), text, font=font)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    if _wrap:
        return _wrap(draw, text, font, max_width)
    lines: list[str] = []
    current = ""
    for word in (text or "").split():
        candidate = word if not current else f"{current} {word}"
        if _bbox(draw, candidate, font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_label(draw: ImageDraw.ImageDraw, position, text: str, font, fill, stroke_width=2):
    if _draw_text_with_shadow:
        _draw_text_with_shadow(
            draw,
            position,
            text,
            font=font,
            fill=fill,
            shadow_offset=(3, 3),
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0, 220),
        )
        return
    draw.text(
        position,
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, 220),
    )


def _render_text_overlay(
    text: str,
    output_path: Path,
    width: int,
    height: int,
    *,
    fill: tuple[int, int, int, int],
    text_size: int,
    max_lines: int,
) -> Path:
    image = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=min(28, height // 3),
        fill=fill,
        outline=(255, 255, 255, 90),
        width=2,
    )
    font = _get_font(text_size, bold=True, text=text)
    lines = _wrap_text(draw, text.strip(), font, max(1, width - 64))[:max_lines]
    line_height = max((_bbox(draw, line, font)[3] for line in lines), default=text_size)
    total_height = line_height * len(lines) + max(0, len(lines) - 1) * 8
    y = (height - total_height) // 2
    for line in lines:
        box = _bbox(draw, line, font)
        x = (width - (box[2] - box[0])) // 2
        _draw_label(draw, (x, y), line, font, (255, 255, 255, 255))
        y += line_height + 8

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")
    return output_path


def render_headline_overlay(
    headline_text: str,
    output_path: Path,
    width: int = 1080,
    height: int = 300,
) -> Path:
    return _render_text_overlay(
        headline_text,
        output_path,
        width,
        height,
        fill=(12, 24, 48, 225),
        text_size=64,
        max_lines=3,
    )


def render_lower_third(
    label_text: str,
    output_path: Path,
    width: int = 1080,
    height: int = 150,
) -> Path:
    return _render_text_overlay(
        label_text,
        output_path,
        width,
        height,
        fill=(219, 52, 65, 225),
        text_size=42,
        max_lines=2,
    )