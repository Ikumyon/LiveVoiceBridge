from __future__ import annotations

import sys

from livevoicebridge.paths import PB2_FILE, PB2_GRPC_FILE, PROTO_FILE, STREAMING_DIR

GRPC_TARGET = "dns:///youtube.googleapis.com:443"

if str(STREAMING_DIR) not in sys.path:
    sys.path.append(str(STREAMING_DIR))


def ensure_grpc_files() -> None:
    """Generate stream_list_pb2.py files on first run if they are missing."""
    if PB2_FILE.exists() and PB2_GRPC_FILE.exists():
        return

    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "gRPC用PythonファイルがEXEに同梱されていません。"
            "stream_list_pb2.py と stream_list_pb2_grpc.py を含めてビルドしてください。"
        )

    try:
        from grpc_tools import protoc
    except ImportError as exc:
        raise RuntimeError(
            "gRPC用Pythonファイルがありません。先に `pip install -r requirements.txt` を実行してください。"
        ) from exc

    result = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{STREAMING_DIR}",
            f"--python_out={STREAMING_DIR}",
            f"--grpc_python_out={STREAMING_DIR}",
            str(PROTO_FILE),
        ]
    )
    if result != 0:
        raise RuntimeError("stream_list.proto からgRPC用Pythonファイルを生成できませんでした。")
