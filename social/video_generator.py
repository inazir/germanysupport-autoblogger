# social/video_generator.py
from __future__ import annotations
import hashlib
import os
import re
import subprocess
import requests
from pathlib import Path
from typing import List, Optional, Tuple
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

# --- CONFIG ---
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
PEXELS_KEY = os.getenv("PEXELS_KEY", "")
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 24
BRAND_TEXT = "GermanySupport.de"

def _fetch_pexels_backgrounds(query: str, count: int, out_dir: Path) -> List[Path]:
    """Fetches relevant portrait images from Pexels."""
    if not PEXELS_KEY:
        return []
    
    paths = []
    try:
        headers = {"Authorization": PEXELS_KEY}
        params = {"query": query, "per_page": count, "orientation": "portrait"}
        r = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=10)
        data = r.json()
        
        for i, photo in enumerate(data.get("photos", [])):
            img_url = photo["src"]["large2x"]
            img_data = requests.get(img_url).content
            path = out_dir / f"bg_{i}.jpg"
            path.write_bytes(img_data)
            paths.append(path)
    except Exception as e:
        print(f"Pexels fetch failed: {e}")
    return paths

def _build_dynamic_scenes(post: SocialPost) -> List[str]:
    """Splits the summary into logical scenes for the video."""
    scenes = [post.title]
    
    summary = (post.summary or "").strip()
    if summary:
        # Split by sentences but keep them short
        parts = re.split(r'(?<=[.!?]) +', summary)
        for p in parts:
            if len(p) > 10:
                # Further wrap if the sentence is too long for one frame
                scenes.extend(_wrap_into_chunks(p, 60))
    
    scenes.append("Link in Bio / Comments or visit GermanySupport.de")
    return [s for s in scenes if s][:6] # Limit to ~6 scenes for engagement

def _wrap_into_chunks(text: str, max_chars: int) -> List[str]:
    import textwrap
    return textwrap.wrap(text, width=max_chars)

def _draw_branded_frame(text: str, bg_path: Optional[Path], out_path: Path):
    # 1. Background logic
    if bg_path and bg_path.exists():
        img = Image.open(bg_path).convert("RGBA").resize((VIDEO_W, VIDEO_H))
    else:
        img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (15, 20, 40, 255))

    # 2. Add dark overlay for readability
    overlay = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 80))
    img = Image.alpha_composite(img, overlay)

    # 3. Add Logo (Top Center)
    logo = _load_logo(max_w=150, max_h=150)
    if logo:
        _paste_logo(img, logo, (VIDEO_W // 2) - 85, 100)

    # 4. Main Text Glass Panel (Center)
    panel_margin = 80
    panel_box = (panel_margin, 600, VIDEO_W - panel_margin, 1300)
    _add_glass_panel(img, panel_box, radius=40, fill=(22, 32, 60, 180))

    # 5. Draw Scene Text
    draw = ImageDraw.Draw(img)
    font = _font(70, bold=True)
    wrapped_text = "\n".join(_wrap(draw, text, font, VIDEO_W - 200))
    
    # Calculate centering
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_pos = ((VIDEO_W - text_w) // 2, (panel_box[1] + panel_box[3] - text_h) // 2)

    _draw_text_with_shadow(draw, text_pos, wrapped_text, font, (255, 255, 255))

    # 6. Brand Name (Bottom)
    brand_font = _font(40, bold=True)
    draw.text((VIDEO_W // 2, VIDEO_H - 150), BRAND_TEXT, font=brand_font, fill=(200, 200, 200), anchor="mm")

    img.convert("RGB").save(out_path, "JPEG", quality=90)

def generate_short_video(post: SocialPost) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", post.title.lower())[:40]
    out_dir = REPO_ROOT / "social" / "cache" / "generated_videos" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = out_dir / "final_video.mp4"
    if output_file.exists(): return str(output_file)

    # Prepare Content
    scenes = _build_dynamic_scenes(post)
    bgs = _fetch_pexels_backgrounds(post.title, len(scenes), out_dir)
    
    frame_paths = []
    for i, text in enumerate(scenes):
        frame_path = out_dir / f"frame_{i}.jpg"
        bg = bgs[i] if i < len(bgs) else (bgs[0] if bgs else None)
        _draw_branded_frame(text, bg, frame_path)
        frame_paths.append(frame_path)

    # Render with FFmpeg (Resource Efficient for Hostinger)
    list_file = out_dir / "concat.txt"
    with open(list_file, "w") as f:
        for p in frame_paths:
            f.write(f"file '{p.resolve()}'\nduration 4\n")
        f.write(f"file '{frame_paths[-1].resolve()}'\n")

    cmd = [
        FFMPEG_PATH, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-vf", f"scale=1080:1920,fps={FPS},format=yuv420p",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-threads", "1", str(output_file)
    ]
    subprocess.run(cmd, check=True)
    
    return str(output_file)