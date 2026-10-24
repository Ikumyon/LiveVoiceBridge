"""YouTube transport publishes source events; it has no speech or Qt dependencies."""

from collections import deque
from threading import Event, Thread

import requests

from livevoicebridge.core.chat.models import CommentEvent
from livevoicebridge.integrations.youtube.url import extract_video_id

GRPC_TARGET = "dns:///youtube.googleapis.com:443"
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeSource:
    def __init__(self):
        self._stop = Event()
        self._channel = None
        self._thread = None

    def start(self, config, on_comment, on_status, on_error, on_closed, on_connection):
        self._config = config
        self._on_comment = on_comment
        self._on_status = on_status
        self._on_error = on_error
        self._on_closed = on_closed
        self._on_connection = on_connection
        self._thread = Thread(target=self._run, name="youtube-stream")
        self._thread.start()

    def _run(self):
        try:
            video_id = extract_video_id(self._config.youtube_source)
            self._on_status(f"video_id: {video_id}")
            chat_id = self.get_live_chat_id(video_id)
            self.stream_chat(chat_id)
        except Exception as exc:
            if not self._stop.is_set():
                self._on_error(str(exc))
        finally:
            self._on_closed()

    def close(self):
        self._stop.set()
        channel = self._channel
        if channel is not None:
            channel.close()
        if self._thread is not None:
            self._thread.join()

    def get_live_chat_id(self, video_id: str) -> str:
        response = requests.get(
            f"{YOUTUBE_API_BASE}/videos",
            params={
                "key": self._config.youtube_api_key,
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

    def stream_chat(self, live_chat_id: str) -> None:
        import grpc

        from livevoicebridge.integrations.youtube.generated import stream_list_pb2, stream_list_pb2_grpc

        metadata = (("x-goog-api-key", self._config.youtube_api_key),)
        next_page_token = None
        first_response = True
        seen_ids: set[str] = set()
        seen_order: deque[str] = deque()
        reconnect_wait = 1

        while not self._stop.is_set():
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

                self._on_status("接続中。コメント待機中です。")
                for response in stub.StreamList(request, metadata=metadata):
                    if self._stop.is_set():
                        return
                    self._on_connection(True)

                    reconnect_wait = 1
                    if response.next_page_token:
                        next_page_token = response.next_page_token

                    if response.offline_at:
                        self._on_status("配信がオフラインになりました。")
                        return

                    for item in response.items:
                        if self._stop.is_set():
                            return

                        if item.id in seen_ids:
                            continue
                        seen_ids.add(item.id)
                        seen_order.append(item.id)
                        if len(seen_order) > 10000:
                            seen_ids.remove(seen_order.popleft())

                        message_type = int(item.snippet.type)
                        if message_type not in {1, 15, 16, 17}:
                            continue
                        self._on_comment(
                            CommentEvent(
                                author=item.author_details.display_name or "匿名",
                                message=item.snippet.display_message,
                                profile_image_url=item.author_details.profile_image_url or "",
                                history=first_response,
                                paid=message_type != 1,
                                identifier=item.id,
                            )
                        )
                    first_response = False

                if not self._stop.is_set():
                    self._on_status("ストリームが閉じました。再接続します。")

            except grpc.RpcError as exc:
                if self._stop.is_set():
                    return
                self._on_status(f"gRPC切断: {exc.code()} / {exc.details()}")
                self._on_status(f"{reconnect_wait}秒後に再接続します。")
                self._stop.wait(reconnect_wait)
                reconnect_wait = min(reconnect_wait * 2, 10)
            except Exception as exc:
                if self._stop.is_set():
                    return
                self._on_status(f"エラー: {exc}")
                self._on_status(f"{reconnect_wait}秒後に再接続します。")
                self._stop.wait(reconnect_wait)
                reconnect_wait = min(reconnect_wait * 2, 10)
            finally:
                self._on_connection(False)
                if self._channel is not None:
                    try:
                        self._channel.close()
                    except Exception:
                        pass
                    self._channel = None
