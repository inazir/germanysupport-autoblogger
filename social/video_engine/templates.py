from __future__ import annotations

import re

from .models import RenderConfig, Scene


_MOTIONS = ("zoom_in", "pan_left", "zoom_out", "pan_right")
_TRANSITIONS = ("fade", "fade", "fade", "fade")


def _headline_for(scenes: list[Scene]) -> str:
    if not scenes:
        return ""
    return scenes[0].headline or scenes[0].text


def _keywords(text: str) -> list[str]:
    tokens = [token.strip(".,!?;:()[]{}\"'") for token in re.split(r"\s+", text)]
    meaningful = [token for token in tokens if len(token) >= 5]
    return meaningful[:3]


def apply_news_template(scenes: list[Scene], config: RenderConfig) -> list[Scene]:
    """Apply consistent NEWS EXPLAINER presentation metadata to scenes."""
    if not scenes:
        return []

    headline = _headline_for(scenes)
    for index, scene in enumerate(scenes):
        scene.motion = _MOTIONS[index % len(_MOTIONS)]
        scene.transition = _TRANSITIONS[index % len(_TRANSITIONS)]
        scene.keywords = scene.keywords or _keywords(scene.text)
        scene.headline = scene.headline or (headline if index == 0 else None)
        scene.supporting_text = scene.supporting_text or (scene.text if index > 0 else None)
        scene.lower_third = scene.lower_third or (
            "GermanySupport.de | News Explainer" if index == 0 else f"GermanySupport.de | {index + 1:02d}"
        )
    return scenes