from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path

from .models import RenderConfig, Scene, WordTiming


logger = logging.getLogger(__name__)

_TICKS_PER_SECOND = 10_000_000.0
_MOTION_PRESETS = ("zoom_in", "pan_left", "zoom_out", "pan_right", "pan_zoom")


def _seconds_from_item(item: dict, key: str, raw_key: str) -> float | None:
    value = item.get(key)
    if value is None:
        value = item.get(raw_key)
        if value is not None:
            try:
                value = float(value) / _TICKS_PER_SECOND
            except (TypeError, ValueError):
                return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) else None


def parse_edge_tts_boundaries(json_path: Path) -> list[WordTiming]:
    """Parse Edge TTS word-boundary metadata into normalized timings."""
    try:
        if not json_path.is_file():
            return []
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning("Unable to read Edge TTS boundaries from %s: %s", json_path, exc)
        return []

    if not isinstance(payload, list):
        logger.warning("Edge TTS boundaries must be a JSON list: %s", json_path)
        return []

    timings: list[WordTiming] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "WordBoundary" and "offset_seconds" not in item:
            continue

        start = _seconds_from_item(item, "offset_seconds", "offset")
        duration = _seconds_from_item(item, "duration_seconds", "duration")
        text = str(item.get("text", "")).strip()
        if start is None or duration is None or not text or duration < 0:
            continue

        end = start + duration
        if start < 0 or not math.isfinite(end):
            continue
        timings.append(
            WordTiming(
                text=text,
                start_seconds=start,
                end_seconds=end,
                source="edge-word",
            )
        )

    return timings


def build_scene_objects(
    scenes_text: list[str],
    total_audio_duration: float,
    word_timings: list[WordTiming] | None = None,
) -> list[Scene]:
    """Convert existing scene strings into timed, renderable scene objects."""
    texts = [text.strip() for text in scenes_text if isinstance(text, str) and text.strip()]
    if not texts:
        return []

    try:
        duration = max(0.0, float(total_audio_duration))
    except (TypeError, ValueError):
        duration = 0.0
    if not math.isfinite(duration):
        duration = 0.0

    weights = [max(len(text), 1) for text in texts]
    total_weight = sum(weights)
    scenes: list[Scene] = []
    elapsed = 0.0

    for index, text in enumerate(texts):
        start = elapsed
        if index == len(texts) - 1:
            end = duration
        else:
            end = duration * sum(weights[: index + 1]) / total_weight
        elapsed = min(max(end, start), duration)

        scene_timings = [
            timing
            for timing in word_timings or []
            if start <= timing.start_seconds <= elapsed
            and start <= timing.end_seconds <= elapsed
        ]
        supporting_text = None if index == 0 else text
        scenes.append(
            Scene(
                scene_id=f"scene-{index + 1:02d}",
                text=text,
                start_seconds=start,
                end_seconds=elapsed,
                headline=text if index == 0 else None,
                supporting_text=supporting_text,
                word_timings=scene_timings,
                motion=_MOTION_PRESETS[index % len(_MOTION_PRESETS)],
            )
        )

    return scenes
