from __future__ import annotations

import math
import re
from pathlib import Path

from .models import Scene, WordTiming


_WORDS_PER_WINDOW = 4


def format_ass_time(seconds: float) -> str:
    """Return a non-negative duration in ASS H:MM:SS.cc format."""
    try:
        value = max(0.0, float(seconds))
    except (TypeError, ValueError):
        value = 0.0
    if not math.isfinite(value):
        value = 0.0

    centiseconds = round(value * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, hundredths = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{hundredths:02d}"


def _escape_ass_text(text: str) -> str:
    return (
        str(text)
        .replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def _tokenize(text: str) -> list[str]:
    # Whitespace tokenization keeps Bengali conjuncts and attached punctuation intact.
    return [token for token in re.split(r"\s+", text.strip()) if token]


def _fallback_timings(scene: Scene) -> list[WordTiming]:
    tokens = _tokenize(scene.text)
    if not tokens:
        return []
    duration = max(0.0, scene.end_seconds - scene.start_seconds)
    step = duration / len(tokens) if tokens else 0.0
    return [
        WordTiming(
            text=token,
            start_seconds=scene.start_seconds + index * step,
            end_seconds=scene.start_seconds + (index + 1) * step,
            source="estimated",
        )
        for index, token in enumerate(tokens)
    ]


def _scene_timings(scene: Scene) -> list[WordTiming]:
    timings = [timing for timing in scene.word_timings if timing.text.strip()]
    return timings or _fallback_timings(scene)


def _window_dialogues(timings: list[WordTiming], active_color: str) -> list[str]:
    dialogues: list[str] = []
    for window_start in range(0, len(timings), _WORDS_PER_WINDOW):
        window = timings[window_start:window_start + _WORDS_PER_WINDOW]
        plain_words = [_escape_ass_text(timing.text.strip()) for timing in window]
        for active_index, active in enumerate(window):
            parts = []
            for index, word in enumerate(plain_words):
                if index == active_index:
                    parts.append(f"{{\\c{active_color}}}{word}{{\\r}}")
                else:
                    parts.append(word)
            end = max(active.end_seconds, active.start_seconds + 0.01)
            dialogues.append(
                f"Dialogue: 0,{format_ass_time(active.start_seconds)}"
                f",{format_ass_time(end)},Caption,,0,0,0,,"
                f"{{\\fad(80,80)}}{' '.join(parts)}\n"
            )
    return dialogues


def generate_ass_subtitles(
    scenes: list[Scene],
    output_path: Path,
    active_color: str = "&H00D7FF&",
) -> Path:
    """Generate UTF-8 ASS subtitles with timed active-word highlighting."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Noto Sans Bengali,62,&H00FFFFFF&,&H00FFFFFF&,&H00101010&,&H90000000&,1,0,0,0,100,100,0,0,1,3,2,2,70,70,610,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for scene in scenes:
        lines.extend(_window_dialogues(_scene_timings(scene), active_color))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    return output_path