from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from .adapters import build_scene_objects, parse_edge_tts_boundaries
from .graphics import render_headline_overlay, render_lower_third
from .models import RenderConfig, Scene
from .subtitles import generate_ass_subtitles
from .templates import apply_news_template


def _binary(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _probe_duration(path: Path) -> float:
    command = [
        _binary("FFPROBE_PATH", "ffprobe"),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    duration = float(result.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Invalid audio duration for {path}: {duration}")
    return duration


def _filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _safe_threads(config: RenderConfig) -> int:
    try:
        return max(1, int(config.ffmpeg_threads))
    except (TypeError, ValueError):
        return 1


def _create_fallback_background(path: Path, width: int, height: int, index: int) -> Path:
    image = Image.new("RGBA", (width, height), (12, 24, 48, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    top = (12 + index * 8 % 30, 24 + index * 5 % 35, 48 + index * 9 % 45, 255)
    bottom = (42, 18, 38 + index * 7 % 35, 255)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(top[channel] * (1 - ratio) + bottom[channel] * ratio) for channel in range(4))
        draw.line((0, y, width, y), fill=color)
    image.save(path, "PNG")
    return path


def _motion_filter(scene: Scene, frame_count: int, config: RenderConfig) -> str:
    last_frame = max(frame_count - 1, 1)
    progress = f"on/{last_frame}"
    zoom_in = f"min(1.0+0.12*{progress},1.12)"
    zoom_out = f"max(1.0,1.12-0.12*{progress})"
    center_y = "(ih-ih/zoom)/2"
    left_to_right = f"(iw-iw/zoom)*{progress}"
    right_to_left = f"(iw-iw/zoom)*(1-{progress})"
    movement = {
        "zoom_in": (zoom_in, "(iw-iw/zoom)/2", center_y),
        "pan_left": ("1.08", left_to_right, center_y),
        "zoom_out": (zoom_out, "(iw-iw/zoom)/2", center_y),
        "pan_right": ("1.08", right_to_left, center_y),
    }
    zoom, x, y = movement.get(scene.motion, movement["zoom_in"])
    return (
        f"scale={config.width * 2}:{config.height * 2}:force_original_aspect_ratio=increase,"
        f"crop={config.width * 2}:{config.height * 2},"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={config.width}x{config.height}:fps={config.fps},"
        "format=yuv420p"
    )


def _build_video_filter(
    scenes: list[Scene],
    config: RenderConfig,
    input_indexes: list[int],
    overlay_indexes: list[list[int]],
    subtitle_path: Path,
) -> str:
    parts: list[str] = []
    labels: list[str] = []
    for index, scene in enumerate(scenes):
        frame_count = max(1, round((scene.end_seconds - scene.start_seconds) * config.fps))
        label = f"scene{index}"
        parts.append(
            f"[{input_indexes[index]}:v]{_motion_filter(scene, frame_count, config)}[{label}]"
        )
        current = label
        for overlay_number, overlay_index in enumerate(overlay_indexes[index]):
            output = f"{label}overlay{overlay_number}"
            parts.append(f"[{current}][{overlay_index}:v]overlay=shortest=1:x=(W-w)/2:y=0[{output}]")
            current = output
        labels.append(current)

    current = labels[0]
    elapsed = scenes[0].end_seconds - scenes[0].start_seconds
    for index in range(1, len(labels)):
        output = f"transition{index}"
        transition = min(
            max(0.05, config.transition_duration),
            max(0.05, scenes[index].end_seconds - scenes[index].start_seconds),
        )
        offset = max(0.0, elapsed - transition)
        parts.append(
            f"[{current}][{labels[index]}]xfade=transition=fade:duration={transition:.3f}:"
            f"offset={offset:.3f}[{output}]"
        )
        current = output
        elapsed += scenes[index].end_seconds - scenes[index].start_seconds - transition

    parts.append(f"[{current}]ass='{_filter_path(subtitle_path)}'[vout]")
    return ";".join(parts)


def _validate_output(path: Path, config: RenderConfig, expected_duration: float) -> None:
    command = [
        _binary("FFPROBE_PATH", "ffprobe"),
        "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    metadata = json.loads(result.stdout)
    streams = metadata.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise ValueError("Rendered video must contain both video and audio streams")
    if int(video.get("width", 0)) != config.width or int(video.get("height", 0)) != config.height:
        raise ValueError("Rendered video dimensions do not match configuration")
    if video.get("codec_name") != "h264" or video.get("pix_fmt") != "yuv420p":
        raise ValueError("Rendered video codec or pixel format is invalid")
    if audio.get("codec_name") != "aac":
        raise ValueError("Rendered audio codec is invalid")
    duration = float(metadata.get("format", {}).get("duration", 0.0))
    if duration <= 0 or abs(duration - expected_duration) > max(2.0, expected_duration * 0.15):
        raise ValueError(f"Rendered duration is invalid: {duration}")


def render_news_video(
    scenes_text: list[str],
    output_path: Path,
    config: RenderConfig,
    voiceover_path: Path,
    boundaries_json_path: Path,
    bg_music_path: Path | None = None,
) -> Path:
    """Render a NEWS EXPLAINER video and validate the resulting MP4."""
    if config.width <= 0 or config.height <= 0 or config.fps <= 0:
        raise ValueError("Render dimensions and FPS must be positive")
    if not voiceover_path.is_file():
        raise FileNotFoundError(voiceover_path)

    audio_duration = _probe_duration(voiceover_path)
    word_timings = parse_edge_tts_boundaries(boundaries_json_path)
    scenes = apply_news_template(
        build_scene_objects(scenes_text, audio_duration, word_timings), config
    )
    if not scenes:
        raise ValueError("At least one scene is required")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="motion-video-", dir=output_path.parent) as temp_dir:
        temp = Path(temp_dir)
        active_color = os.getenv("SOCIAL_VIDEO_SUBTITLE_ACTIVE_COLOR", "&H00D7FF&").strip()
        subtitle_path = generate_ass_subtitles(
            scenes,
            temp / "captions.ass",
            active_color=active_color or "&H00D7FF&",
        )
        input_indexes: list[int] = []
        overlay_indexes: list[list[int]] = []
        ffmpeg_inputs: list[str] = []
        input_index = 0
        for index, scene in enumerate(scenes):
            background = scene.background_path if scene.background_path and scene.background_path.is_file() else None
            background = background or _create_fallback_background(temp / f"background-{index:02d}.png", config.width * 2, config.height * 2, index)
            duration = max(0.05, scene.end_seconds - scene.start_seconds)
            ffmpeg_inputs.extend(["-loop", "1", "-framerate", str(config.fps), "-t", f"{duration:.3f}", "-i", str(background)])
            input_indexes.append(input_index)
            input_index += 1
            overlays: list[int] = []
            if scene.headline:
                render_headline_overlay(scene.headline, temp / f"headline-{index:02d}.png", config.width, 300)
                ffmpeg_inputs.extend(["-loop", "1", "-t", f"{duration:.3f}", "-i", str(temp / f"headline-{index:02d}.png")])
                overlays.append(input_index)
                input_index += 1
            if scene.lower_third:
                render_lower_third(scene.lower_third, temp / f"lower-third-{index:02d}.png", config.width, 150)
                ffmpeg_inputs.extend(["-loop", "1", "-t", f"{duration:.3f}", "-i", str(temp / f"lower-third-{index:02d}.png")])
                overlays.append(input_index)
                input_index += 1
            overlay_indexes.append(overlays)

        voice_index = input_index
        ffmpeg_inputs.extend(["-i", str(voiceover_path)])
        input_index += 1
        music_index = None
        if bg_music_path and bg_music_path.is_file():
            music_index = input_index
            ffmpeg_inputs.extend(["-stream_loop", "-1", "-i", str(bg_music_path)])

        video_filter = _build_video_filter(scenes, config, input_indexes, overlay_indexes, subtitle_path)
        audio_filter = f"[{voice_index}:a]aformat=sample_rates=44100:channel_layouts=mono[narration]"
        audio_map = "[narration]"
        if music_index is not None:
            audio_filter += (
                ";[narration]asplit=2[narration_mix][narration_sidechain];"
                f"[{music_index}:a]volume=0.10[music];[music][narration_sidechain]"
                "sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[ducked];"
                "[narration_mix][ducked]amix=inputs=2:duration=first[aout]"
            )
            audio_map = "[aout]"

        temporary_output = temp / "final_video.mp4"
        command = [
            _binary("FFMPEG_PATH", "ffmpeg"), "-y", *ffmpeg_inputs,
            "-filter_complex", f"{video_filter};{audio_filter}",
            "-map", "[vout]", "-map", audio_map,
            "-t", f"{audio_duration:.3f}", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", str(config.crf),
            "-threads", str(_safe_threads(config)), "-pix_fmt", "yuv420p",
            "-r", str(config.fps), "-c:a", "aac", "-ar", "44100",
            "-movflags", "+faststart", str(temporary_output),
        ]
        subprocess.run(command, check=True)
        _validate_output(temporary_output, config, audio_duration)
        os.replace(temporary_output, output_path)

    return output_path