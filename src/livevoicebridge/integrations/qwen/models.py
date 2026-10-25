"""Validate local model snapshots without writing to their source folders."""

import json
from pathlib import Path


def validate_model(source: Path) -> str:
    source = source.resolve(strict=True)
    config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    if config.get("tts_model_type") != "custom_voice" or config.get("tts_model_size") != "0b6":
        raise ValueError("対応モデルはQwen3-TTS 0.6B CustomVoiceです。Base・VoiceDesign・1.7Bは使えません。")
    if not (source / "tokenizer_config.json").is_file():
        raise ValueError("tokenizer_config.jsonがありません。モデル全体のフォルダーを指定してください。")
    if (source / "openvino_talker_model.xml").is_file():
        names = (
            "talker_model",
            "talker_embeddings",
            "text_embeddings",
            "code_predictor_model",
            "code_predictor_embeddings",
            "codec_decoder",
            "codec_encoder",
        )
        if any(not (source / f"openvino_{name}.{suffix}").is_file() for name in names for suffix in ("xml", "bin")):
            raise ValueError("OpenVINOモデルのXML/BINファイルが不足しています。")
        if any(
            not (source / f"openvino_{name}.{suffix}").is_file()
            for name in ("tokenizer", "detokenizer")
            for suffix in ("xml", "bin")
        ):
            return "tokenizer"
        return "openvino"
    index = source / "model.safetensors.index.json"
    if index.is_file():
        shards = set(json.loads(index.read_text(encoding="utf-8"))["weight_map"].values())
        for name in shards:
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("モデルの重みパスがフォルダーの外を指しています。")
            (source / relative).resolve(strict=True)
    elif not (source / "model.safetensors").is_file():
        raise ValueError("モデルの重みがありません。ダウンロード済みのモデル全体を指定してください。")
    speech = source / "speech_tokenizer"
    if not (speech / "config.json").is_file() or not list(speech.glob("*.safetensors")):
        raise ValueError("speech_tokenizerの設定または重みが不足しています。")
    return "original"
