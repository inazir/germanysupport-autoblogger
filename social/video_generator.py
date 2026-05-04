# social/video_generator.py
from __future__ import annotations

from openai import OpenAI
import os
import re
import subprocess
import random
from pathlib import Path
from typing import List, Optional

import requests
from PIL import Image, ImageDraw
import asyncio
import edge_tts

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
# Config — tuneable via .env
# ---------------------------------------------------------------------------

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
PEXELS_KEY  = os.getenv("PEXELS_KEY", "")
BRAND_TEXT  = os.getenv("SOCIAL_BRAND_TEXT", "GermanySupport.de")

# Output canvas: 1080×1920 (Portrait)
VIDEO_W, VIDEO_H = 1080, 1920
FPS = 24

# ---------------------------------------------------------------------------
# Audio Helpers
# ---------------------------------------------------------------------------

def _get_audio_duration(file_path: Path) -> float:
    """Uses ffprobe to find the exact duration of the voice-over MP3."""
    # Look for the path in .env, otherwise try the global 'ffprobe' command
    ffprobe_path = os.getenv("FFPROBE_PATH", "ffprobe")
    
    cmd = [
        ffprobe_path, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        print(f"WARNING: ffprobe failed at {ffprobe_path}. Error: {e}")
        return 20.0 # Fallback

def _generate_voiceover(scenes: List[str], out_dir: Path) -> Path:
    full_text = ". ".join(scenes)

    clean_text = re.sub(r'https?://\S+', '', full_text)
    clean_text = clean_text.replace("GermanySupport.de", "Germany Support dot de")

    voices = [
        "en-US-AriaNeural",
        "en-US-JennyNeural",
        "en-GB-SoniaNeural",
        "en-AU-NatashaNeural",
        "en-US-GuyNeural",
    ]

    voice = random.choice(voices)
    print(f"INFO: Selected voice: {voice}")

    audio_path = out_dir / "voiceover.mp3"

    async def _run():
        communicate = edge_tts.Communicate(
            text=clean_text,
            voice=voice,
            rate="+8%",
            volume="+0%"
        )
        await communicate.save(str(audio_path))

    asyncio.run(_run())

    return audio_path

def _get_random_music() -> Optional[Path]:
    """Picks a random mp3 from the assets folder for background music."""
    music_dir = REPO_ROOT / "social" / "assets" / "background-music"
    if not music_dir.exists():
        music_dir.mkdir(parents=True, exist_ok=True)
        return None
        
    mp3_files = list(music_dir.glob("*.mp3"))
    if not mp3_files:
        return None
    return random.choice(mp3_files)

# ---------------------------------------------------------------------------
# Background image fetching from Pexels
# ---------------------------------------------------------------------------

def _fetch_pexels_backgrounds(query: str, count: int, out_dir: Path) -> List[Path]:
    if not PEXELS_KEY:
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
# Scene text generation via Deepseek
# ---------------------------------------------------------------------------
def _build_scenes(post: SocialPost) -> List[str]:
    # Initialize DeepSeek Client
    api_key = os.getenv("DEEPSEEK_API_KEY")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    prompt = f"""
Create text for a 20-second social media video.

TITLE: {post.title}
SUMMARY: {post.summary}

REQUIREMENTS:
1. Output language MUST be English only.
2. Rewrite any German content into natural English.
3. 5 lines total exactly:
   - Line 1 = Strong scroll-stopping Hook
   - Line 2 = Important useful point
   - Line 3 = Surprising / money-saving / helpful point
   - Line 4 = Actionable takeaway or warning
   - Line 5 = Call To Action
4. Each line max 75 characters.
5. Strictly NO emojis.
6. Strictly NO bullet points.
7. Strictly NO numbering.
8. Use short clear spoken language.
9. Make it highly engaging for Facebook / Instagram reels.
10. Hook should create curiosity instantly.
11. Use urgency when relevant (new rules, changes, deadlines, costs).
12. Encourage likes/comments/shares naturally.
13. Tone should feel helpful, smart, trustworthy.
"""

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8
        )

        raw_text = response.choices[0].message.content.strip()

        lines = [
            line.strip().strip("•-*1234567890. ")
            for line in raw_text.split("\n")
            if line.strip()
        ]

        # Force exactly 5 lines
        lines = lines[:5]

        while len(lines) < 5:
            lines.append("Visit GermanySupport.de")

        return lines

    except Exception as e:
        print(f"ERROR: DeepSeek Video Text Generation failed: {e}")
        return [
            "Important Germany update",
            "New rules may affect you",
            "Check latest details now",
            "Simple guide available",
            "Visit GermanySupport.de"
        ]

# ---------------------------------------------------------------------------
# Single-frame renderer
# ---------------------------------------------------------------------------

def _draw_branded_frame(text: str, bg_path: Optional[Path], out_path: Path) -> None:
    if bg_path and bg_path.exists():
        try:
            bg = Image.open(bg_path).convert("RGBA")
            bw, bh = bg.size
            scale  = max(VIDEO_W / bw, VIDEO_H / bh)
            new_w, new_h = int(bw * scale), int(bh * scale)
            bg = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
            left, top = (new_w - VIDEO_W) // 2, (new_h - VIDEO_H) // 2
            img = bg.crop((left, top, left + VIDEO_W, top + VIDEO_H))
        except Exception:
            img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (15, 20, 40, 255))
    else:
        img = Image.new("RGBA", (VIDEO_W, VIDEO_H), (15, 20, 40, 255))

    overlay = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 110))
    img = Image.alpha_composite(img, overlay)

    logo = _load_logo(max_w=160, max_h=160)
    if logo:
        lw, lh = logo.size
        logo_x = (VIDEO_W - lw) // 2 - 12
        _paste_logo(img, logo, logo_x, 80)

    panel_margin, panel_top, panel_bottom = 72, 520, 1380
    panel_box = (panel_margin, panel_top, VIDEO_W - panel_margin, panel_bottom)
    _add_glass_panel(img, panel_box, radius=44, blur_radius=18, fill=(22, 32, 60, 175), edge=(255, 255, 255, 90), highlight_alpha=20)

    draw = ImageDraw.Draw(img)
    text_font = _font(68, bold=True)
    max_text_w = VIDEO_W - panel_margin * 2 - 80
    wrapped_lines = _wrap(draw, text, text_font, max_text_w)

    line_h = draw.textbbox((0, 0), "Ag", font=text_font)[3]
    line_gap = 14
    block_h = line_h * len(wrapped_lines) + line_gap * max(len(wrapped_lines) - 1, 0)
    start_y = ((panel_top + panel_bottom) // 2) - (block_h // 2)

    for i, line in enumerate(wrapped_lines):
        bbox = draw.textbbox((0, 0), line, font=text_font)
        x = (VIDEO_W - (bbox[2] - bbox[0])) // 2
        y = start_y + i * (line_h + line_gap)
        _draw_text_with_shadow(draw, (x, y), line, font=text_font, fill=(255, 255, 255), shadow_fill=(0, 0, 0, 190), shadow_offset=(4, 5), stroke_width=3, stroke_fill=(0, 0, 0, 230))

    brand_font = _font(38, bold=True)
    brand_bbox = draw.textbbox((0, 0), BRAND_TEXT, font=brand_font)
    brand_w = brand_bbox[2] - brand_bbox[0]
    _draw_text_with_shadow(draw, ((VIDEO_W - brand_w) // 2, VIDEO_H - 130), BRAND_TEXT, font=brand_font, fill=(210, 218, 235), shadow_fill=(0, 0, 0, 160), shadow_offset=(2, 3))

    img.convert("RGB").save(out_path, "JPEG", quality=90)

# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def generate_short_video(post: SocialPost) -> str:
    """Generates a complete video synced perfectly to the AI voice duration."""
    
    # 1. Setup paths
    slug = re.sub(r"[^a-z0-9]+", "-", (post.title or "video").lower()).strip("-")[:40]
    out_dir = REPO_ROOT / "social" / "cache" / "generated_videos" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    output_file = out_dir / "final_video.mp4"

    if output_file.exists():
        print(f"INFO: Video cache hit — reusing {output_file}")
        return str(output_file)

    # 2. Get AI-generated text and Audio
    scenes = _build_scenes(post)
    voice_path = _generate_voiceover(scenes, out_dir)
    
    # 3. Measure Voice Duration for perfect sync
    audio_duration = _get_audio_duration(voice_path)
    video_total_time = audio_duration + 0.8  # Tiny buffer at the end
    per_scene_duration = video_total_time / len(scenes)

    # 4. Fetch Backgrounds and Draw Frames
    bgs = _fetch_pexels_backgrounds(post.title, len(scenes), out_dir)
    frame_paths = []
    for i, text in enumerate(scenes):
        frame_path = out_dir / f"frame_{i:02d}.jpg"
        bg = bgs[i % len(bgs)] if bgs else None
        _draw_branded_frame(text, bg, frame_path)
        frame_paths.append(frame_path)

    # 5. Create concat list for FFmpeg with calculated timing
    concat_file = out_dir / "concat.txt"
    with open(concat_file, "w") as f:
        for p in frame_paths:
            f.write(f"file '{p.resolve()}'\n")
            f.write(f"duration {per_scene_duration}\n")
        # Repeating the last frame is an FFmpeg requirement for concat
        f.write(f"file '{frame_paths[-1].resolve()}'\n")

    # 6. Mix Video, Voice, and Background Music
    music_path = _get_random_music()
    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(voice_path),
    ]

    if music_path:
        print(f"INFO: Mixing music: {music_path.name}")
        cmd.extend(["-stream_loop", "-1", "-i", str(music_path)])
        # Voice at 100%, Music at 15%
        filter_str = "[1:a]volume=1.0[v];[2:a]volume=0.15[m];[v][m]amix=inputs=2:duration=first[a]"
        cmd.extend(["-filter_complex", filter_str, "-map", "0:v", "-map", "[a]"])
    else:
        cmd.extend(["-map", "0:v", "-map", "1:a"])
    # 7. Set output parameters - LIGHTWEIGHT MODE for Shared Hosting
    cmd.extend([
        "-t", str(video_total_time),
        "-c:v", "libx264",
        "-preset", "ultrafast",   # Least CPU usage possible
        "-crf", "32",             # Slightly lower quality, much less RAM/CPU
        "-threads", "1",          # CRITICAL: Prevent Hostinger from killing multi-thread spikes
        "-pix_fmt", "yuv420p",    # Standard compatibility
        "-c:a", "aac",
        "-b:a", "96k",            # Lower bitrate to save memory
        "-movflags", "+faststart",
        str(output_file)
    ])

    print(f"INFO: Executing FFmpeg for '{post.title[:30]}' (Time: {video_total_time:.2f}s)")
    subprocess.run(cmd, check=True)
    return str(output_file)
