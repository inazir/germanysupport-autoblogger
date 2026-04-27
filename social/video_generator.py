# social/video_generator.py
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional

import requests
from PIL import Image, ImageDraw

from social.models import SocialPost
from social.image_builder import (
    REPO_ROOT,
    _add_glass_panel,
    _draw_text_with_shadow,
    _font,
    _load_logo,
    _paste_logo,
    _wrap,
)

# ---------------------------------------------------------------------------
# Config — all tuneable via .env
# ---------------------------------------------------------------------------

# Full absolute path to ffmpeg binary (required on Hostinger shared hosting
# because ffmpeg is not on $PATH).  Example:
#   FFMPEG_PATH=/home/u989113309/ffmpeg/ffmpeg-7.0.2-amd64-static/ffmpeg
FFMPEG_PATH = os.getenv(
    "FFMPEG_PATH",
    "ffmpeg",   # fallback: works locally if ffmpeg is on $PATH
)

PEXELS_KEY  = os.getenv("PEXELS_KEY", "")
BRAND_TEXT  = os.getenv("SOCIAL_BRAND_TEXT", "GermanySupport.de")

# Output canvas: 1080×1920 — standard portrait / Reels / Stories size
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 24

# Seconds each scene frame is shown.  4 s × 6 scenes ≈ 24 s — well within
# Facebook Reels limits.
SCENE_DURATION = 4

# ---------------------------------------------------------------------------
# Background image fetching from Pexels
# ---------------------------------------------------------------------------

def _fetch_pexels_backgrounds(query: str, count: int, out_dir: Path) -> List[Path]:
    """
    Download up to `count` portrait-oriented photos from Pexels matching
    `query`.  Images are cached under `out_dir` so repeated runs of the
    same article do not re-download.
    Returns a list of local Paths (may be shorter than `count` if Pexels
    returns fewer results or the API key is missing).
    """
    if not PEXELS_KEY:
        print("WARNING: PEXELS_KEY not set — video will use fallback dark background")
        return []

    paths: List[Path] = []
    try:
        headers = {"Authorization": PEXELS_KEY}
        params  = {"query": query, "per_page": min(count, 10), "orientation": "portrait"}
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers,
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        for i, photo in enumerate(data.get("photos", [])[:count]):
            cache_path = out_dir / f"bg_{i}.jpg"
            if cache_path.exists():
                # Re-use cached image — avoids re-downloading on re-runs
                paths.append(cache_path)
                continue
            img_url  = photo["src"]["large2x"]
            img_data = requests.get(img_url, timeout=20).content
            cache_path.write_bytes(img_data)
            paths.append(cache_path)

    except Exception as exc:
        print(f"WARNING: Pexels background fetch failed: {exc}")

    return paths


# ---------------------------------------------------------------------------
# Scene text splitting
# ---------------------------------------------------------------------------

def _build_scenes(post: SocialPost) -> List[str]:
    """
    Split the article title + summary into at most 6 short text scenes.
    The last scene is always the fixed CTA.
    """
    CTA = "Visit GermanySupport.de — link in bio / comments"

    scenes: List[str] = [post.title]

    summary = (post.summary or "").strip()
    if summary:
        # Split on sentence boundaries first
        sentences = re.split(r"(?<=[.!?])\s+", summary)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            # If a sentence is very long, break it into ≤60-char chunks
            if len(sentence) > 70:
                import textwrap
                chunks = textwrap.wrap(sentence, width=65)
                scenes.extend(chunks)
            else:
                scenes.append(sentence)

    # Reserve the last slot for CTA; allow max 5 content scenes + 1 CTA = 6
    content_scenes = [s for s in scenes if s][:5]
    content_scenes.append(CTA)
    return content_scenes


# ---------------------------------------------------------------------------
# Single-frame renderer
# ---------------------------------------------------------------------------

def _draw_branded_frame(text: str, bg_path: Optional[Path], out_path: Path) -> None:
    """
    Render one 1080×1920 JPEG frame with:
      • Pexels background (or dark fallback)
      • semi-transparent dark overlay for legibility
      • GermanySupport logo (top-centre, using _load_logo / _paste_logo)
      • glass-panel text card in the centre (using _add_glass_panel)
      • brand name footer
    """
    # --- Background ---
    if bg_path and bg_path.exists():
        try:
            bg = Image.open(bg_path).convert("RGBA")
            # Crop-to-fill: scale so the smaller dimension matches the canvas
            bw, bh = bg.size
            scale  = max(VIDEO_W / bw, VIDEO_H / bh)
            new_w  = int(bw * scale)
            new_h  = int(bh * scale)
            bg     = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left   = (new_w - VIDEO_W) // 2
            top    = (new_h - VIDEO_H) // 2
            img    = bg.crop((left, top, left + VIDEO_W, top + VIDEO_H))
        except Exception:
            img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (15, 20, 40, 255))
    else:
        img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (15, 20, 40, 255))

    # --- Dark readability overlay ---
    overlay = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 110))
    img = Image.alpha_composite(img, overlay)

    # --- Logo (top-centre) ---
    # _load_logo respects SOCIAL_LOGO_PATH from .env via image_builder.py
    logo = _load_logo(max_w=160, max_h=160)
    if logo:
        lw, lh = logo.size
        logo_x = (VIDEO_W - lw) // 2 - 12   # -12 to account for _paste_logo padding
        _paste_logo(img, logo, logo_x, 80)

    # --- Glass panel (vertical centre-ish) ---
    panel_margin = 72
    panel_top    = 520
    panel_bottom = 1380
    panel_box    = (panel_margin, panel_top, VIDEO_W - panel_margin, panel_bottom)
    _add_glass_panel(
        img,
        panel_box,
        radius=44,
        blur_radius=18,
        fill=(22, 32, 60, 175),
        edge=(255, 255, 255, 90),
        highlight_alpha=20,
    )

    # --- Scene text ---
    draw       = ImageDraw.Draw(img)
    text_font  = _font(68, bold=True)
    max_text_w = VIDEO_W - panel_margin * 2 - 80   # inner padding

    wrapped_lines = _wrap(draw, text, text_font, max_text_w)

    # Measure total text block height so we can centre it inside the panel
    line_h    = draw.textbbox((0, 0), "Ag", font=text_font)[3]
    line_gap  = 14
    block_h   = line_h * len(wrapped_lines) + line_gap * max(len(wrapped_lines) - 1, 0)

    panel_mid = (panel_top + panel_bottom) // 2
    start_y   = panel_mid - block_h // 2

    for i, line in enumerate(wrapped_lines):
        bbox   = draw.textbbox((0, 0), line, font=text_font)
        line_w = bbox[2] - bbox[0]
        x      = (VIDEO_W - line_w) // 2
        y      = start_y + i * (line_h + line_gap)
        _draw_text_with_shadow(
            draw,
            (x, y),
            line,
            font=text_font,
            fill=(255, 255, 255),
            shadow_fill=(0, 0, 0, 190),
            shadow_offset=(4, 5),
            stroke_width=3,
            stroke_fill=(0, 0, 0, 230),
        )

    # --- Brand name footer ---
    brand_font = _font(38, bold=True)
    brand_bbox = draw.textbbox((0, 0), BRAND_TEXT, font=brand_font)
    brand_w    = brand_bbox[2] - brand_bbox[0]
    _draw_text_with_shadow(
        draw,
        ((VIDEO_W - brand_w) // 2, VIDEO_H - 130),
        BRAND_TEXT,
        font=brand_font,
        fill=(210, 218, 235),
        shadow_fill=(0, 0, 0, 160),
        shadow_offset=(2, 3),
    )

    # Save as JPEG (FFmpeg concat input)
    img.convert("RGB").save(out_path, "JPEG", quality=90)


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def generate_short_video(post: SocialPost) -> str:
    """
    Generate a branded short-form vertical video (1080×1920) for `post`.

    Steps:
      1. Build scene texts from post.title + post.summary
      2. Fetch portrait backgrounds from Pexels (cached per slug)
      3. Render one JPEG frame per scene using image_builder helpers
      4. Stitch frames into an MP4 via FFmpeg with Hostinger-safe settings
         (-threads 1, -preset veryfast, -crf 28)

    Returns the absolute path to the output MP4 as a string.
    Raises subprocess.CalledProcessError if FFmpeg fails.
    """
    # Derive a safe directory name from the article title
    slug    = re.sub(r"[^a-z0-9]+", "-", (post.title or "video").lower()).strip("-")[:40]
    out_dir = REPO_ROOT / "social" / "cache" / "generated_videos" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    output_file = out_dir / "final_video.mp4"

    # Cache-hit: if the video already exists for this slug, return it immediately
    # so we don't burn Pexels quota or CPU time on re-runs.
    if output_file.exists():
        print(f"INFO: Video cache hit — reusing {output_file}")
        return str(output_file)

    # Build scenes and fetch backgrounds
    scenes = _build_scenes(post)
    bgs    = _fetch_pexels_backgrounds(post.title, len(scenes), out_dir)

    # Render one JPEG per scene
    frame_paths: List[Path] = []
    for i, text in enumerate(scenes):
        frame_path = out_dir / f"frame_{i:02d}.jpg"
        # Cycle through available backgrounds; fall back gracefully if none
        bg = bgs[i % len(bgs)] if bgs else None
        _draw_branded_frame(text, bg, frame_path)
        frame_paths.append(frame_path)

    if not frame_paths:
        raise RuntimeError("No frames were generated — cannot produce video")

    # Write FFmpeg concat file
    concat_file = out_dir / "concat.txt"
    with open(concat_file, "w") as f:
        for p in frame_paths:
            f.write(f"file '{p.resolve()}'\n")
            f.write(f"duration {SCENE_DURATION}\n")
        # FFmpeg concat demuxer requires the last entry to be repeated without duration
        f.write(f"file '{frame_paths[-1].resolve()}'\n")

    # FFmpeg command — Hostinger-safe:
    #   -threads 1       avoid hitting shared-hosting CPU limits
    #   -preset veryfast fast enough on a single thread; better than ultrafast
    #                    quality-wise without meaningful extra CPU cost
    #   -crf 28          acceptable quality at small file size for social upload
    #   -movflags +faststart   moves MOOV atom to file start for streaming
    cmd = [
        FFMPEG_PATH,
        "-y",                       # overwrite output without prompting
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,"
               f"pad={VIDEO_W}:{VIDEO_H}:(ow-iw)/2:(oh-ih)/2,"
               f"fps={FPS},"
               f"format=yuv420p",
        "-c:v", "libx264",
        "-preset", "veryfast",      # changed from ultrafast — better quality, safe on Hostinger
        "-crf", "28",
        "-threads", "1",            # mandatory for Hostinger shared hosting
        "-movflags", "+faststart",  # optimise for streaming / upload
        str(output_file),
    ]

    print(f"INFO: Running FFmpeg for '{post.title[:50]}'...")
    subprocess.run(cmd, check=True)
    print(f"INFO: Video generated → {output_file}")

    return str(output_file)
