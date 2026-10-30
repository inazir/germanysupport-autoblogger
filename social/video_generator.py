# social/video_generator.py
from __future__ import annotations

from openai import OpenAI
import json
import os
import re
import subprocess
import random
import hashlib
from pathlib import Path
from typing import List, Optional

import requests
from PIL import Image, ImageDraw
import asyncio
import edge_tts

from social.models import SocialPost
from social.image_generation.image_builder import (
    REPO_ROOT,
    _add_glass_panel,
    _draw_text_with_shadow,
    _font,
    _load_logo,
    _paste_logo,
    render_bengali_text_card,
    _textbbox,
    _wrap,
)

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
PEXELS_KEY  = os.getenv("PEXELS_KEY", "")
BRAND_TEXT  = os.getenv("SOCIAL_BRAND_TEXT", "GermanySupport.de")
VIDEO_STYLE = os.getenv("SOCIAL_VIDEO_STYLE", "classic").strip().lower() or "classic"
VIDEO_RENDERER_VERSION = os.getenv("SOCIAL_VIDEO_RENDERER_VERSION", "1").strip() or "1"
VIDEO_MUSIC_VOLUME = os.getenv("SOCIAL_VIDEO_BG_MUSIC_VOLUME", "0.10").strip() or "0.10"
VIDEO_MUSIC_DUCKING = os.getenv("SOCIAL_VIDEO_BG_MUSIC_DUCKING", "true").strip().lower() in {
    "1", "true", "yes", "on"
}

VIDEO_W, VIDEO_H = 1080, 1920
FPS = 24
PROFESSIONAL_FPS = 30

def _language_env_values(prefix: str, language: str) -> List[str]:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", (language or "").strip()).upper().strip("_")
    primary = normalized.split("_", 1)[0] if normalized else ""
    keys = [f"{prefix}_{normalized}"] if normalized else []
    if primary and primary != normalized:
        keys.append(f"{prefix}_{primary}")
    keys.append(f"{prefix}_DEFAULT")
    return [os.getenv(key, "").strip() for key in keys if os.getenv(key, "").strip()]


def _voice_for_language(language: str) -> str:
    configured = _language_env_values("EDGE_TTS_VOICE", language)
    if not configured:
        raise RuntimeError(
            f"No Edge TTS voice configured for language '{language}'. "
            "Set EDGE_TTS_VOICE_<LANG> or EDGE_TTS_VOICE_DEFAULT."
        )
    voices = [voice.strip() for voice in configured[0].split(",") if voice.strip()]
    if not voices:
        raise RuntimeError(f"Edge TTS voice configuration is empty for language '{language}'")
    return random.choice(voices)


def _spoken_site_name(language: str) -> str:
    configured = _language_env_values("EDGE_TTS_SPOKEN_SITE_NAME", language)
    return configured[0] if configured else "GermanySupport.de"


def _bengali_font_path() -> Path:
    configured = os.getenv("SOCIAL_FONT_BENGALI_REGULAR_PATH", "").strip()
    candidates = [
        Path(configured) if configured else None,
        REPO_ROOT / "social" / "assets" / "fonts" / "NotoSansBengali.ttf",
        Path("/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansBengali.ttf"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise RuntimeError(
        "No Bengali font found. Set SOCIAL_FONT_BENGALI_REGULAR_PATH "
        "to a valid Bengali TTF file."
    )

def _get_audio_duration(file_path: Path) -> float:
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
        return 20.0

def _generate_voiceover(scenes: List[str], out_dir: Path, language: str = "en") -> Path:
    full_text = ". ".join(scenes)
    clean_text = re.sub(r'https?://\S+', '', full_text)
    clean_text = clean_text.replace("GermanySupport.de", _spoken_site_name(language))
    voice = _voice_for_language(language)
    print(f"INFO: Selected voice: {voice}")
    audio_path = out_dir / "voiceover.mp3"
    timing_path = out_dir / "voiceover-boundaries.json"
    async def _run():
        communicate = edge_tts.Communicate(text=clean_text, voice=voice, rate="+8%", volume="+0%")
        boundaries = []
        with audio_path.open("wb") as audio_file:
            async for event in communicate.stream():
                if event["type"] == "audio":
                    audio_file.write(event["data"])
                elif event["type"] in {"WordBoundary", "SentenceBoundary"}:
                    boundaries.append(
                        {
                            "type": event["type"],
                            "offset_seconds": event["offset"] / 10_000_000,
                            "duration_seconds": event["duration"] / 10_000_000,
                            "text": event.get("text", ""),
                        }
                    )
        timing_path.write_text(json.dumps(boundaries, ensure_ascii=False, indent=2), encoding="utf-8")
    asyncio.run(_run())
    return audio_path


def _split_caption_phrases(text: str, max_words: int = 4) -> List[str]:
    words = [word for word in re.split(r"\s+", text.strip()) if word]
    return [" ".join(words[index:index + max_words]) for index in range(0, len(words), max_words)]


def _caption_windows(
    scenes: List[str],
    audio_duration: float,
    boundaries_path: Path,
) -> List[dict]:
    boundaries = []
    if boundaries_path.exists():
        try:
            boundaries = json.loads(boundaries_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            boundaries = []

    usable_boundaries = [
        item for item in boundaries
        if item.get("type") == "SentenceBoundary" and item.get("duration_seconds", 0) > 0
    ]
    has_one_boundary_per_scene = len(usable_boundaries) == len(scenes)
    windows = []
    scene_duration = audio_duration / len(scenes)

    for scene_index, scene in enumerate(scenes):
        if has_one_boundary_per_scene:
            start = max(0.0, float(usable_boundaries[scene_index]["offset_seconds"]))
            end = min(audio_duration, start + float(usable_boundaries[scene_index]["duration_seconds"]))
        else:
            start = scene_index * scene_duration
            end = min(audio_duration, (scene_index + 1) * scene_duration)

        phrases = _split_caption_phrases(scene)
        phrase_duration = (end - start) / max(len(phrases), 1)
        for phrase_index, phrase in enumerate(phrases):
            phrase_start = start + phrase_index * phrase_duration
            windows.append(
                {
                    "start_seconds": phrase_start,
                    "end_seconds": min(end, phrase_start + phrase_duration),
                    "text": phrase,
                    "timing_source": "sentence-boundary" if has_one_boundary_per_scene else "estimated-scene",
                }
            )
    return windows


def _ass_timestamp(seconds: float) -> str:
    total_centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(total_centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _write_ass_subtitles(caption_windows: List[dict], out_path: Path) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Noto Sans Bengali,62,&H00FFFFFF,&H00FFD700,&H00FFFFFF,&H00000000,1,0,1,3,2,2,70,70,610,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for window in caption_windows:
        start = _ass_timestamp(window["start_seconds"])
        end = _ass_timestamp(window["end_seconds"])
        text = _escape_ass_text(window["text"])
        lines.append(f"Dialogue: 0,{start},{end},Caption,,0,0,0,,{{\\fad(250,250)}}{text}\n")
    out_path.write_text("".join(lines), encoding="utf-8")

def _get_random_music() -> Optional[Path]:
    music_dir = REPO_ROOT / "social" / "assets" / "background-music"
    if not music_dir.exists():
        music_dir.mkdir(parents=True, exist_ok=True)
        return None
    mp3_files = list(music_dir.glob("*.mp3"))
    return random.choice(mp3_files) if mp3_files else None

def _fetch_pexels_backgrounds(query: str, count: int, out_dir: Path) -> List[Path]:
    if not PEXELS_KEY:
        return []
    paths: List[Path] = []
    try:
        headers = {"Authorization": PEXELS_KEY}
        params  = {"query": query, "per_page": min(count, 10), "orientation": "portrait"}
        r = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=15)
        r.raise_for_status()
        for i, photo in enumerate(r.json().get("photos", [])[:count]):
            cache_path = out_dir / f"bg_{i}.jpg"
            if cache_path.exists():
                paths.append(cache_path)
                continue
            cache_path.write_bytes(requests.get(photo["src"]["large2x"], timeout=20).content)
            paths.append(cache_path)
    except Exception as exc:
        print(f"WARNING: Pexels background fetch failed: {exc}")
    return paths

def _build_scenes(
    post: SocialPost,
    topic: Optional[str] = None,
    script: Optional[str] = None,
    scenes: Optional[List[str]] = None,
) -> List[str]:
    if scenes:
        return [scene.strip() for scene in scenes if scene and scene.strip()]

    if script and script.strip():
        script_scenes = [part.strip() for part in re.split(r"\n+|(?<=[.!?।])\s+", script) if part.strip()]
        return script_scenes[:8]

    api_key = os.getenv("DEEPSEEK_API_KEY")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    language = (post.language or "en").strip().lower()
    source_topic = (topic or post.title or "").strip()
    prompt = f"""
Create text for a 20-second social media video.
TOPIC: {source_topic}
SUMMARY: {post.summary}
REQUIREMENTS:
1. Output language MUST match this language code: {language}.
2. Rewrite the source content into natural spoken language for that locale.
3. 5 lines total exactly:
   - Line 1 = Strong scroll-stopping Hook
   - Line 2 = Important useful point
   - Line 3 = Surprising / money-saving / helpful point
   - Line 4 = Actionable takeaway or warning
   - Line 5 = Call To Action
4. Each line max 75 characters.
5. Strictly NO emojis. NO bullet points. NO numbering.
6. Use short clear spoken language.
7. Make it highly engaging for Facebook / Instagram reels.
8. Tone should feel helpful, smart, trustworthy.
"""
    try:
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8
        )
        raw_text = response.choices[0].message.content.strip()
        lines = [line.strip().strip("•-*1234567890. ") for line in raw_text.split("\n") if line.strip()]
        lines = lines[:5]
        while len(lines) < 5:
            lines.append(lines[-1] if lines else post.title)
        return lines
    except Exception as e:
        print(f"ERROR: DeepSeek Video Text Generation failed: {e}")
        source_text = " ".join(filter(None, [post.title, post.summary or ""]))
        fallback = [part.strip() for part in re.split(r"(?<=[.!?।])\s+", source_text) if part.strip()]
        fallback = fallback[:5] or [post.title or "GermanySupport.de"]
        while len(fallback) < 5:
            fallback.append(fallback[-1])
        return fallback

def _draw_branded_frame(text: str, bg_path: Optional[Path], out_path: Path) -> None:
    if bg_path and bg_path.exists():
        try:
            bg = Image.open(bg_path).convert("RGBA")
            bw, bh = bg.size
            scale = max(VIDEO_W / bw, VIDEO_H / bh)
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
        logo_x = (VIDEO_W - logo.size[0]) // 2 - 12
        _paste_logo(img, logo, logo_x, 80)

    panel_margin, panel_top, panel_bottom = 72, 520, 1380
    _add_glass_panel(img, (panel_margin, panel_top, VIDEO_W - panel_margin, panel_bottom),
                     radius=44, blur_radius=18, fill=(22, 32, 60, 175), edge=(255, 255, 255, 90), highlight_alpha=20)

    draw = ImageDraw.Draw(img)
    text_font = _font(68, bold=True, text=text)
    wrapped_lines = _wrap(draw, text, text_font, VIDEO_W - panel_margin * 2 - 80)
    line_h = _textbbox(draw, "অগ", text_font)[3]
    line_gap = 14
    block_h = line_h * len(wrapped_lines) + line_gap * max(len(wrapped_lines) - 1, 0)
    start_y = ((panel_top + panel_bottom) // 2) - (block_h // 2)
    for i, line in enumerate(wrapped_lines):
        bbox = _textbbox(draw, line, text_font)
        x = (VIDEO_W - (bbox[2] - bbox[0])) // 2
        y = start_y + i * (line_h + line_gap)
        _draw_text_with_shadow(draw, (x, y), line, font=text_font, fill=(255, 255, 255),
                               shadow_fill=(0, 0, 0, 190), shadow_offset=(4, 5), stroke_width=3, stroke_fill=(0, 0, 0, 230))

    brand_font = _font(38, bold=True)
    brand_bbox = _textbbox(draw, BRAND_TEXT, brand_font)
    brand_w = brand_bbox[2] - brand_bbox[0]
    _draw_text_with_shadow(draw, ((VIDEO_W - brand_w) // 2, VIDEO_H - 130), BRAND_TEXT,
                           font=brand_font, fill=(210, 218, 235), shadow_fill=(0, 0, 0, 160), shadow_offset=(2, 3))

    # FIX: Save via YCbCr to produce clean limited-range yuv420p JPEG.
    # PIL's default RGB JPEG saves full-range yuvj420p metadata which causes
    # libx264 in FFmpeg 7.x static builds to crash with -22 / "Error while
    # opening encoder". YCbCr conversion removes that metadata entirely.
    img.convert("RGB").convert("YCbCr").save(out_path, "JPEG", quality=90)


def _motion_filter(motion: str, frame_count: int) -> str:
    last_frame = max(frame_count - 1, 1)
    progress = f"on/{last_frame}"
    zoom_in = f"min(1.0+0.12*{progress},1.12)"
    zoom_out = f"max(1.0,1.12-0.12*{progress})"
    center_y = "(ih-ih/zoom)/2"
    left_to_right = f"(iw-iw/zoom)*{progress}"
    right_to_left = f"(iw-iw/zoom)*(1-{progress})"

    expressions = {
        "zoom_in": (zoom_in, "(iw-iw/zoom)/2", center_y),
        "zoom_out": (zoom_out, "(iw-iw/zoom)/2", center_y),
        "pan_left": ("1.08", left_to_right, center_y),
        "pan_right": ("1.08", right_to_left, center_y),
        "pan_zoom": (zoom_in, left_to_right, center_y),
    }
    zoom, x, y = expressions[motion]
    return f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={VIDEO_W}x{VIDEO_H}:fps={PROFESSIONAL_FPS}"


def _render_motion_segment(
    image_path: Path,
    output_path: Path,
    duration: float,
    motion_index: int,
) -> None:
    frame_count = max(1, round(duration * PROFESSIONAL_FPS))
    motions = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_zoom")
    motion = motions[motion_index % len(motions)]
    cmd = [
        FFMPEG_PATH, "-y",
        "-loop", "1", "-i", str(image_path),
        "-vf", f"{_motion_filter(motion, frame_count)},format=yuv420p",
        "-frames:v", str(frame_count),
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "32",
        "-threads", "1",
        "-pix_fmt", "yuv420p",
        "-r", str(PROFESSIONAL_FPS),
        str(output_path),
    ]
    subprocess.run(cmd, check=True)


def _motion_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def generate_short_video(
    post: SocialPost,
    topic: Optional[str] = None,
    script: Optional[str] = None,
    scenes: Optional[List[str]] = None,
    style: Optional[str] = None,
) -> str:
    """Generate a video from a SocialPost or reusable runtime content."""

    cache_title = (topic or post.title or "video").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", cache_title.lower()).strip("-")[:40]
    language = re.sub(r"[^a-z0-9]+", "-", (post.language or "en").lower()).strip("-") or "en"
    video_style = re.sub(r"[^a-z0-9_-]+", "-", (style or VIDEO_STYLE).lower()).strip("-") or "classic"
    cache_key = f"{slug}-{language}-{video_style}-r{VIDEO_RENDERER_VERSION}"
    out_dir = REPO_ROOT / "social" / "cache" / "generated_videos" / cache_key
    out_dir.mkdir(parents=True, exist_ok=True)
    output_file = out_dir / "final_video.mp4"

    # Validate cached video — crashed FFmpeg leaves 0-byte files.
    # Also wipe stale frame JPEGs so the YCbCr fix actually runs on regeneration;
    # keeping old frames caused the old full-range yuvj420p files to be reused.
    if output_file.exists():
        if output_file.stat().st_size > 10_240:
            print(f"INFO: Video cache hit — reusing {output_file}")
            return str(output_file)
        print(f"WARNING: Cached video at {output_file} is corrupt "
              f"({output_file.stat().st_size} bytes). Wiping frames and regenerating.")
        for f in out_dir.glob("frame_*.jpg"):
            f.unlink()
        for f in out_dir.glob("frame_*.png"):
            f.unlink()
        output_file.unlink()

    scene_texts = _build_scenes(post, topic=topic, script=script, scenes=scenes)
    if not scene_texts:
        raise ValueError("Video generation requires at least one non-empty scene")
    voice_path = _generate_voiceover(scene_texts, out_dir, post.language)
    audio_duration = _get_audio_duration(voice_path)
    caption_windows = _caption_windows(
        scene_texts,
        audio_duration,
        out_dir / "voiceover-boundaries.json",
    )
    (out_dir / "caption-timings.json").write_text(
        json.dumps(caption_windows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    subtitle_path = out_dir / "captions.ass"
    caption_paths = []
    if video_style != "classic":
        _write_ass_subtitles(caption_windows, subtitle_path)
        font_path = _bengali_font_path()
        for index, window in enumerate(caption_windows):
            caption_path = out_dir / f"caption_{index:02d}.png"
            render_bengali_text_card(
                window["text"],
                str(font_path),
                font_size=62,
            ).save(caption_path, "PNG")
            caption_paths.append((caption_path, window))
    video_total_time = audio_duration + 0.8
    transition_duration = (
        min(0.4, max(video_total_time / len(scene_texts) / 3, 0.05))
        if video_style != "classic" and len(scene_texts) > 1
        else 0.0
    )
    per_scene_duration = (
        (video_total_time + transition_duration * (len(scene_texts) - 1))
        / len(scene_texts)
    )

    bgs = _fetch_pexels_backgrounds(cache_title, len(scene_texts), out_dir)
    frame_paths = []
    for i, text in enumerate(scene_texts):
        frame_path = out_dir / f"frame_{i:02d}.jpg"
        _draw_branded_frame(
            text if video_style == "classic" else "",
            bgs[i % len(bgs)] if bgs else None,
            frame_path,
        )
        frame_paths.append(frame_path)

    concat_file = out_dir / "concat.txt"
    motion_paths = []
    if video_style == "classic":
        with open(concat_file, "w") as f:
            for p in frame_paths:
                f.write(f"file '{p.resolve()}'\n")
                f.write(f"duration {per_scene_duration}\n")
            f.write(f"file '{frame_paths[-1].resolve()}'\n")
    else:
        motion_seed = _motion_seed(f"{cache_title}|{post.language}|{video_style}")
        for index, frame_path in enumerate(frame_paths):
            motion_path = out_dir / f"motion_{index:02d}.mp4"
            _render_motion_segment(
                frame_path,
                motion_path,
                per_scene_duration,
                motion_seed + index,
            )
            motion_paths.append(motion_path)

    music_path = _get_random_music()
    if video_style == "classic":
        cmd = [
            FFMPEG_PATH, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(voice_path),
        ]
        video_input_label = "0:v"
        voice_input_index = 1
    else:
        cmd = [FFMPEG_PATH, "-y"]
        for motion_path in motion_paths:
            cmd.extend(["-i", str(motion_path)])
        for caption_path, _ in caption_paths:
            cmd.extend(["-loop", "1", "-i", str(caption_path)])
        cmd.extend(["-i", str(voice_path)])
        voice_input_index = len(motion_paths) + len(caption_paths)

        filter_parts = []
        previous_label = "0:v"
        for index in range(1, len(motion_paths)):
            output_label = f"v{index}"
            offset = index * (per_scene_duration - transition_duration)
            filter_parts.append(
                f"[{previous_label}][{index}:v]xfade=transition=fade:"
                f"duration={transition_duration:.3f}:offset={offset:.3f}[{output_label}]"
            )
            previous_label = output_label
        caption_label = previous_label
        for caption_index, (_, window) in enumerate(caption_paths):
            output_label = f"caption{caption_index}"
            input_index = len(motion_paths) + caption_index
            start = float(window["start_seconds"])
            end = float(window["end_seconds"])
            enable = f"between(t\\,{start:.3f}\\,{end:.3f})"
            filter_parts.append(
                f"[{caption_label}][{input_index}:v]overlay="
                f"x=(W-w)/2:y=1260:enable='{enable}'[{output_label}]"
            )
            caption_label = output_label
        filter_parts.append(f"[{caption_label}]format=yuv420p[vout]")
        cmd.extend(["-filter_complex", ";".join(filter_parts)])
        video_input_label = "[vout]"

    if music_path:
        print(f"INFO: Mixing music: {music_path.name}")
        cmd.extend(["-stream_loop", "-1", "-i", str(music_path)])
        music_input_index = voice_input_index + 1
        try:
            music_volume = max(0.0, min(float(VIDEO_MUSIC_VOLUME), 1.0))
        except ValueError:
            music_volume = 0.10
        music_end = max(video_total_time - 0.5, 0.0)
        music_chain = (
            f"volume={music_volume:.3f},"
            "afade=t=in:st=0:d=0.5,"
            f"afade=t=out:st={music_end:.3f}:d=0.5"
        )
        audio_filter = (
            f"[{voice_input_index}:a]aformat=sample_rates=44100:"
            f"channel_layouts=mono,asplit=2[narration_sidechain][narration_mix];"
            f"[{music_input_index}:a]{music_chain}[background_audio]"
        )
        if VIDEO_MUSIC_DUCKING:
            audio_filter += (
                ";[background_audio][narration_sidechain]sidechaincompress=threshold=0.03:"
                "ratio=8:attack=20:release=300[ducked_music];"
                "[narration_mix][ducked_music]amix=inputs=2:duration=first[aout]"
            )
        else:
            audio_filter += "[narration_mix][background_audio]amix=inputs=2:duration=first[aout]"
        if video_style == "classic":
            cmd.extend(["-filter_complex", audio_filter, "-map", "0:v", "-map", "[aout]"])
        else:
            cmd[cmd.index("-filter_complex") + 1] += ";" + audio_filter
            cmd.extend(["-map", video_input_label, "-map", "[aout]"])
    else:
        cmd.extend(["-map", video_input_label, "-map", f"{voice_input_index}:a"])

    cmd.extend([
        "-t", str(video_total_time),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "32",
        "-threads", "1",      # Prevent Hostinger killing multi-thread CPU spikes
        "-pix_fmt", "yuv420p",
        "-r", str(PROFESSIONAL_FPS if video_style != "classic" else 25),
        "-c:a", "aac",
        "-b:a", "96k",
        "-ar", "44100",       # Required by Instagram Reels
        "-movflags", "+faststart",
        str(output_file)
    ])

    print(f"INFO: Executing FFmpeg for '{post.title[:30]}' (Time: {video_total_time:.2f}s)")
    subprocess.run(cmd, check=True)
    return str(output_file)
