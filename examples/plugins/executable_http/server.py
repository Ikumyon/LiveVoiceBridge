"""Build as bin/tts_plugin(.exe). stdout is reserved for the JSON Lines protocol."""

import base64
import json
import sys
from urllib.request import Request, urlopen

MAX_REQUEST = 1024 * 1024


def handle(method: str, params: dict):
    if method == "register":
        if params["api_version"] != 1:
            raise ValueError("Unsupported API version")
        return {
            "id": params["plugin_id"],
            "name": "外部HTTP WAV 作成例",
            "speaker_id": "default",
            "capabilities": {
                "controls": ["speaker_id", "echo", "yamabiko", "panning"],
                "local_audio": True,
                "completion_known": True,
            },
            "fields": [
                {
                    "key": "url",
                    "title": "合成エンドポイント",
                    "kind": "text",
                    "default": "http://127.0.0.1:8000/synthesize",
                }
            ],
        }
    if method in {"prepare", "close"}:
        return None
    if method == "speakers":
        return [{"identifier": "default", "name": "標準話者", "style": "通常"}]
    if method == "synthesize":
        config, controls = params["config"], params["controls"]
        limit = params["max_bytes"] + 65536
        request = Request(
            config["settings"]["url"],
            data=json.dumps(
                {"text": params["text"], "voice": controls["speaker_id"] or config["speaker_id"]}, ensure_ascii=False
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=110) as response:
            wav = response.read(limit + 1)
        if len(wav) > limit:
            raise ValueError("Audio exceeds max_bytes")
        return {"wav_base64": base64.b64encode(wav).decode("ascii")}
    raise ValueError(f"Unsupported method: {method}")


def main() -> None:
    while True:
        line = sys.stdin.buffer.readline(MAX_REQUEST + 1)
        if not line:
            return
        if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
            raise ValueError("Invalid or oversized request")
        request = json.loads(line.decode("utf-8"))
        reply = {"version": 1, "id": request["id"]}
        try:
            if request["version"] != 1:
                raise ValueError("Unsupported protocol version")
            reply["result"] = handle(request["method"], request["params"])
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            reply["error"] = {"code": type(exc).__name__, "message": str(exc)}
        sys.stdout.buffer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
        if request["method"] == "close":
            return


if __name__ == "__main__":
    main()
