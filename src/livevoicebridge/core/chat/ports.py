from collections.abc import Callable
from typing import Protocol

from livevoicebridge.core.chat.models import CommentEvent, StreamingConfig


class StreamingSource(Protocol):
    def start(
        self,
        config: StreamingConfig,
        on_comment: Callable[[CommentEvent], None],
        on_status: Callable[[str], None],
        on_error: Callable[[str], None],
        on_closed: Callable[[], None],
        on_connection: Callable[[bool], None],
    ) -> None: ...
    def close(self) -> None: ...
