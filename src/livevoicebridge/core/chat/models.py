"""Source events preserve the original display text."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamingConfig:
    youtube_api_key: str = ""
    youtube_source: str = ""
    skip_history: bool = True
    read_paid_events: bool = True


@dataclass(frozen=True, slots=True)
class CommentEvent:
    author: str
    message: str
    profile_image_url: str = ""
    history: bool = False
    paid: bool = False
    identifier: str = ""
