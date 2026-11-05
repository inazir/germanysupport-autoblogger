from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WordTiming:
    text: str
    start_seconds: float
    end_seconds: float
    source: str


@dataclass
class Scene:
    scene_id: str
    text: str
    start_seconds: float
    end_seconds: float
    background_path: Path | None = None
    headline: str | None = None
    supporting_text: str | None = None
    lower_third: str | None = None
    keywords: list[str] = field(default_factory=list)
    word_timings: list[WordTiming] = field(default_factory=list)
    motion: str = "zoom_in"
    transition: str = "fade"


@dataclass
class RenderConfig:
    mode: str = "legacy"
    width: int = 1080
    height: int = 1920
    fps: int = 25
    crf: int = 26
    ffmpeg_threads: int = 1
    transition_duration: float = 0.35
    subtitle_position: str = "lower_safe"
    animation_intensity: float = 1.0
    template: str = "news"
