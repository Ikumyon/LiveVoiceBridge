from __future__ import annotations

import queue

from livevoicebridge.infrastructure.streaming.url import extract_video_id
from livevoicebridge.infrastructure.streaming.youtube import (
    MEMBER_MILESTONE_CHAT_EVENT,
    SUPER_CHAT_EVENT,
    SUPER_STICKER_EVENT,
    TEXT_MESSAGE_EVENT,
    YouTubeChatStreamWorker,
)


def test_extract_video_id_supports_current_url_forms() -> None:
    video_id = "abcdefghijk"

    assert extract_video_id(video_id) == video_id
    assert extract_video_id(f"https://www.youtube.com/watch?v={video_id}") == video_id
    assert extract_video_id(f"https://youtu.be/{video_id}") == video_id
    assert extract_video_id(f"https://www.youtube.com/live/{video_id}") == video_id
    assert extract_video_id(f"https://www.youtube.com/embed/{video_id}") == video_id
    assert extract_video_id(f"https://www.youtube.com/shorts/{video_id}") == video_id


def _stream_worker(read_super_chat: bool) -> YouTubeChatStreamWorker:
    return YouTubeChatStreamWorker(
        queue.Queue(),
        "abcdefghijk",
        "api-key",
        True,
        read_super_chat,
        50,
        [{"type": "message"}],
    )


def test_stream_event_filter_always_reads_text() -> None:
    worker = _stream_worker(False)

    assert worker.should_read_type(TEXT_MESSAGE_EVENT)
    assert not worker.should_read_type(SUPER_CHAT_EVENT)


def test_stream_event_filter_includes_paid_events_when_enabled() -> None:
    worker = _stream_worker(True)

    assert worker.should_read_type(SUPER_CHAT_EVENT)
    assert worker.should_read_type(SUPER_STICKER_EVENT)
    assert worker.should_read_type(MEMBER_MILESTONE_CHAT_EVENT)
    assert not worker.should_read_type(999)
