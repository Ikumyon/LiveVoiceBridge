from __future__ import annotations

import queue
import time

import requests
from PySide6.QtCore import QThread, Signal

from core.comment_processing import (
    build_read_text,
    clean_comment,
    normalize_read_blocks,
    parse_comment_into_segments,
)
from core.streaming.youtube.grpc import GRPC_TARGET, ensure_grpc_files
from core.streaming.youtube.url import extract_video_id


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

TEXT_MESSAGE_EVENT = 1
SUPER_CHAT_EVENT = 15
SUPER_STICKER_EVENT = 16
MEMBER_MILESTONE_CHAT_EVENT = 17


class YouTubeChatStreamWorker(QThread):
    log = Signal(str)
    status = Signal(str)
    error = Signal(str)
    comment_received = Signal(dict)

    def __init__(
        self,
        speech_queue: queue.Queue,
        youtube_url_or_id: str,
        api_key: str,
        skip_history: bool,
        read_super_chat: bool,
        max_length: int,
        read_blocks: list[dict],
    ):
        super().__init__()
        self.speech_queue = speech_queue
        self.youtube_url_or_id = youtube_url_or_id
        self.api_key = api_key
        self.skip_history = skip_history
        self.read_super_chat = read_super_chat
        self.max_length = max_length
        self.read_blocks = normalize_read_blocks(read_blocks)
        self._running = True
        self._channel = None

    def stop(self) -> None:
        self._running = False
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass

    def run(self) -> None:
        try:
            ensure_grpc_files()
            video_id = extract_video_id(self.youtube_url_or_id)
            self.status.emit(f"video_id: {video_id}")
            live_chat_id = self.get_live_chat_id(video_id)
            self.status.emit("liveChatId取得OK。streamListに接続します。")
            self.stream_chat(live_chat_id)
        except Exception as exc:
            if self._running:
                self.error.emit(str(exc))

    def get_live_chat_id(self, video_id: str) -> str:
        response = requests.get(
            f"{YOUTUBE_API_BASE}/videos",
            params={
                "key": self.api_key,
                "part": "liveStreamingDetails",
                "id": video_id,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        if not items:
            raise RuntimeError("動画が見つかりません。URLまたは動画IDを確認してください。")

        live_chat_id = items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
        if not live_chat_id:
            raise RuntimeError("activeLiveChatIdを取得できません。ライブ中か、チャットが有効か確認してください。")
        return live_chat_id

    def should_read_type(self, message_type: int) -> bool:
        if message_type == TEXT_MESSAGE_EVENT:
            return True
        if self.read_super_chat and message_type in {
            SUPER_CHAT_EVENT,
            SUPER_STICKER_EVENT,
            MEMBER_MILESTONE_CHAT_EVENT,
        }:
            return True
        return False

    def stream_chat(self, live_chat_id: str) -> None:
        import grpc
        import stream_list_pb2
        import stream_list_pb2_grpc

        metadata = (("x-goog-api-key", self.api_key),)
        next_page_token = None
        first_response = True
        seen_ids: set[str] = set()
        reconnect_wait = 1

        while self._running:
            try:
                credentials = grpc.ssl_channel_credentials()
                options = [
                    ("grpc.keepalive_time_ms", 30000),
                    ("grpc.keepalive_timeout_ms", 10000),
                    ("grpc.http2.max_pings_without_data", 0),
                ]
                self._channel = grpc.secure_channel(GRPC_TARGET, credentials, options=options)
                stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(self._channel)

                request = stream_list_pb2.LiveChatMessageListRequest(
                    live_chat_id=live_chat_id,
                    part=["snippet", "authorDetails"],
                    max_results=200,
                    page_token=next_page_token or "",
                )

                self.status.emit("接続中。コメント待機中です。")
                for response in stub.StreamList(request, metadata=metadata):
                    if not self._running:
                        return

                    reconnect_wait = 1
                    if response.next_page_token:
                        next_page_token = response.next_page_token

                    if response.offline_at:
                        self.status.emit("配信がオフラインになりました。")
                        return

                    for item in response.items:
                        if not self._running:
                            return

                        if item.id in seen_ids:
                            continue
                        seen_ids.add(item.id)

                        message_type = int(item.snippet.type)
                        if not self.should_read_type(message_type):
                            continue

                        author = item.author_details.display_name or "匿名"
                        profile_image_url = item.author_details.profile_image_url or ""
                        message = clean_comment(item.snippet.display_message, self.max_length)
                        if not message:
                            continue

                        is_skip = first_response and self.skip_history
                        read_text = build_read_text(self.read_blocks, author, message)
                        segments, play_files = parse_comment_into_segments(read_text)
                        clean_msg = "".join([s["text"] for s in segments])

                        self.comment_received.emit({
                            "author": author,
                            "message": message,
                            "profile_image_url": profile_image_url,
                            "is_skip": is_skip,
                            "play_file": play_files[0] if play_files else None,
                            "clean_message": clean_msg,
                        })

                        if not is_skip:
                            self.log.emit(f"{author}: {clean_msg}")
                            self.speech_queue.put(segments)
                    first_response = False

                if self._running:
                    self.status.emit("ストリームが閉じました。再接続します。")

            except grpc.RpcError as exc:
                if not self._running:
                    return
                self.status.emit(f"gRPC切断: {exc.code()} / {exc.details()}")
                self.status.emit(f"{reconnect_wait}秒後に再接続します。")
                time.sleep(reconnect_wait)
                reconnect_wait = min(reconnect_wait * 2, 10)
            except Exception as exc:
                if not self._running:
                    return
                self.status.emit(f"エラー: {exc}")
                self.status.emit(f"{reconnect_wait}秒後に再接続します。")
                time.sleep(reconnect_wait)
                reconnect_wait = min(reconnect_wait * 2, 10)
            finally:
                if self._channel is not None:
                    try:
                        self._channel.close()
                    except Exception:
                        pass
                    self._channel = None
