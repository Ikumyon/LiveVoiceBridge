from __future__ import annotations

import html
import re

import emoji
from livevoicebridge_native import (
    DictionaryMatcher as NativeDictionaryMatcher,
    hiragana_to_katakana,
    parse_comment,
    split_sentences,
)


READ_BLOCK_TYPES = {"author", "message", "text"}
DEFAULT_READ_BLOCKS = [{"type": "message"}]


class DictionaryMatcher:
    """辞書変更時にだけ構築するRust製の最長一致置換器。"""

    def __init__(self, word_list: list[dict] | None = None):
        entries = [
            (str(item.get("word", "")), str(item.get("reading", "")))
            for item in (word_list or [])
            if item.get("word")
        ]
        self._native = NativeDictionaryMatcher(entries)

    def replace(self, text: str) -> str:
        return self._native.replace(text)


def replace_emojis(text: str) -> str:
    emojis = emoji.emoji_list(text)
    if not emojis:
        return text

    sorted_emojis = sorted(emojis, key=lambda item: item["match_start"], reverse=True)
    chars = list(text)
    for item in sorted_emojis:
        replacement = emoji.demojize(item["emoji"], language="ja").strip(":")
        chars[item["match_start"]:item["match_end"]] = list(replacement)
    return "".join(chars)


def parse_comment_into_segments(message: str) -> tuple[list[dict], list[str]]:
    return parse_comment(message)


def normalize_read_blocks(blocks: object) -> list[dict]:
    if not isinstance(blocks, list):
        return [block.copy() for block in DEFAULT_READ_BLOCKS]

    normalized = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type not in READ_BLOCK_TYPES:
            continue
        if block_type == "text":
            value = str(block.get("value", ""))
            if value:
                normalized.append({"type": "text", "value": value})
        else:
            normalized.append({"type": block_type})
    return normalized or [block.copy() for block in DEFAULT_READ_BLOCKS]


def build_read_text(read_blocks: list[dict], author: str, message: str) -> str:
    parts = []
    for block in normalize_read_blocks(read_blocks):
        block_type = block["type"]
        if block_type == "author":
            parts.append(author)
        elif block_type == "message":
            parts.append(message)
        elif block_type == "text":
            parts.append(block.get("value", ""))
    return "".join(parts).strip()


def split_speech_segments(segments: list[dict]) -> list[dict]:
    queue_items = []
    for segment in segments:
        sentences = split_sentences(str(segment.get("text", "")))
        for index, sentence in enumerate(sentences):
            queue_item = dict(segment)
            queue_item["text"] = sentence
            if index != len(sentences) - 1:
                queue_item.pop("action", None)
                queue_item.pop("word", None)
                queue_item.pop("reading", None)
            queue_items.append(queue_item)
    return queue_items


def clean_comment(text: str, max_len: int) -> str:
    text = html.unescape(text)
    text = re.sub(r"https?://\S+", "URL", text)
    text = re.sub(r"\s+", " ", text).strip()
    if max_len != -1 and len(text) > max_len:
        text = text[:max_len] + "、以下略"
    return text
