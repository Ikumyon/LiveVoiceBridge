"""Local, persistent OpenVINO Qwen3-TTS 0.6B CustomVoice service.

Run in a separate environment; no Qt or LiveVoiceBridge imports required.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
VOICES = ("ono_anna", "vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "sohee")
MAX_BODY_BYTES = 32768
MAX_TEXT_LENGTH = 2000


class Synthesizer:
    def __init__(self, model: Path, device: str):
        import openvino as ov
        import openvino_genai

        config = json.loads((model / "config.json").read_text(encoding="utf-8"))
        if config.get("tts_model_type") != "custom_voice" or config.get("tts_model_size") != "0b6":
            raise ValueError("Qwen3-TTS 0.6B CustomVoiceの変換済みモデルを指定してください。")
        if not (model / "openvino_tokenizer.xml").is_file():
            raise ValueError("テキストトークナイザーがありません。prepare_tokenizer.pyで生成してください。")
        devices = ov.Core().available_devices
        if device not in devices:
            raise ValueError(f"指定デバイス {device} がありません: {devices}")
        self.device = device
        self.lock = Lock()
        self.pipeline = openvino_genai.Text2SpeechPipeline(str(model), device, CACHE_DIR=str(model / "compiled_cache"))

    def synthesize(self, text: str, voice_id: int, volume: float) -> bytes:
        import numpy as np
        import soundfile as sf

        result = self.pipeline.generate(text, None, speaker=VOICES[voice_id], language="Japanese")
        if len(result.speeches) != 1:
            raise RuntimeError("音声生成結果が1件ではありません。")
        samples = np.asarray(result.speeches[0].data).reshape(-1)
        if samples.size == 0 or not np.isfinite(samples).all():
            raise RuntimeError("音声生成結果が空、または不正です。")
        buffer = io.BytesIO()
        sf.write(
            buffer, np.clip(samples * volume, -1.0, 1.0), result.output_sample_rate, format="WAV", subtype="PCM_16"
        )
        logging.info("audio_seconds=%.3f", samples.size / result.output_sample_rate)
        return buffer.getvalue()


def handler_for(synth: Synthesizer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def send_body(self, status: int, content: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                logging.info("Client disconnected")

        def send_json(self, status: int, value: object) -> None:
            self.send_body(status, json.dumps(value, ensure_ascii=False).encode("utf-8"))

        def do_GET(self) -> None:
            if self.path == "/health":
                self.send_json(
                    200, {"service": "livevoicebridge-qwen3", "ready": True, "model": MODEL_ID, "device": synth.device}
                )
            elif self.path == "/voices":
                self.send_json(200, [{"id": i, "name": name} for i, name in enumerate(VOICES)])
            else:
                self.send_json(404, {"error": "Unknown endpoint"})

        def do_POST(self) -> None:
            if self.path != "/synthesize":
                self.send_json(404, {"error": "Unknown endpoint"})
                return
            self.connection.settimeout(10)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY_BYTES:
                    raise ValueError("Invalid request length")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Request must be an object")
                text = data.get("text")
                voice_id = data.get("voice_id", 0)
                volume = data.get("volume", 1.0)
                if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH:
                    raise ValueError(f"text must contain 1..{MAX_TEXT_LENGTH} characters")
                if type(voice_id) is not int or not 0 <= voice_id < len(VOICES):
                    raise ValueError("Invalid voice_id")
                if type(volume) not in (int, float) or not math.isfinite(volume) or not 0 <= volume <= 2:
                    raise ValueError("volume must be between 0 and 2")
            except (ValueError, UnicodeError, OSError) as exc:
                self.send_json(400, {"error": str(exc)})
                return
            if not synth.lock.acquire(blocking=False):
                self.send_json(429, {"error": "Synthesis is busy"})
                return
            try:
                start = time.perf_counter()
                wav = synth.synthesize(text, voice_id, volume)
                logging.info("synthesis_seconds=%.3f characters=%d", time.perf_counter() - start, len(text))
            except Exception:
                logging.exception("Synthesis failed")
                self.send_json(500, {"error": "Synthesis failed; see service log"})
            else:
                self.send_body(200, wav, "audio/wav")
            finally:
                synth.lock.release()

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device", choices=("CPU", "GPU"), default="GPU")
    parser.add_argument("--port", type=int, default=50040)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    synth = Synthesizer(args.model.resolve(), args.device)
    logging.info("Warming up %s on %s", MODEL_ID, args.device)
    synth.synthesize("こんにちは。", 0, 1.0)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(synth))
    logging.info("Ready: http://127.0.0.1:%d", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
