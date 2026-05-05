from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from social.models import SocialPost, SocialTarget


class PlatformError(RuntimeError):
    pass


@dataclass
class PublishResult:
    remote_post_id: str
    first_comment_id: Optional[str] = None
    reel_id: Optional[str] = None
    story_id: Optional[str] = None


class BasePlatformPublisher(ABC):
    def __init__(self, target: SocialTarget) -> None:
        self.target = target

    @abstractmethod
    def publish(self, post: SocialPost) -> PublishResult:
        raise NotImplementedError

    def publish_story(
        self,
        post: SocialPost,
        *,
        image_path: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> str:
        raise PlatformError(
            f"Stories are not implemented for platform '{self.target.platform}'"
        )