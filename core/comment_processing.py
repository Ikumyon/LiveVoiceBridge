from __future__ import annotations

import html
import re

import emoji


READ_BLOCK_TYPES = {"author", "message", "text"}
DEFAULT_READ_BLOCKS = [{"type": "message"}]


def replace_words(text: str, word_list: list[dict]) -> str:
    if not word_list:
        return text
    sorted_words = sorted(word_list, key=lambda x: len(x.get("word", "")), reverse=True)
    for item in sorted_words:
        word = item.get("word", "")
        reading = item.get("reading", "")
        if word and word in text:
            text = text.replace(word, reading)
    return text


def replace_emojis(text: str) -> str:
    emojis = emoji.emoji_list(text)
    if not emojis:
        return text

    sorted_emojis = sorted(emojis, key=lambda x: x["match_start"], reverse=True)
    chars = list(text)

    for item in sorted_emojis:
        em = item["emoji"]
        start = item["match_start"]
        end = item["match_end"]

        demo = emoji.demojize(em, language="ja")
        replacement = demo.strip(":")
        chars[start:end] = list(replacement)

    return "".join(chars)


def parse_education_command(text: str, start_pos: int) -> tuple[str, str, int] | tuple[None, None, None]:
    open_paren = text.find("(", start_pos + 2)
    if open_paren == -1:
        return None, None, None

    result_chars = []
    i = open_paren + 1
    escaped = False
    equal_idx = -1

    while i < len(text):
        char = text[i]
        if escaped:
            result_chars.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "=" and equal_idx == -1:
            equal_idx = len(result_chars)
        elif char == ")":
            if equal_idx != -1:
                word = "".join(result_chars[:equal_idx]).strip()
                reading = "".join(result_chars[equal_idx:]).strip()
                return word, reading, i + 1
            return None, None, None
        else:
            result_chars.append(char)
        i += 1

    return None, None, None


def parse_forget_command(text: str, start_pos: int) -> tuple[str, int] | tuple[None, None]:
    open_paren = text.find("(", start_pos + 2)
    if open_paren == -1:
        return None, None

    result_chars = []
    i = open_paren + 1
    escaped = False

    while i < len(text):
        char = text[i]
        if escaped:
            result_chars.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ")":
            word = "".join(result_chars).strip()
            return word, i + 1
        else:
            result_chars.append(char)
        i += 1

    return None, None


def parse_comment_into_segments(message: str) -> tuple[list[dict], list[str]]:
    segments = []
    current_states = {
        "speed": None,
        "pitch": None,
        "volume": None,
        "speaker_id": None,
        "echo": None,
        "yamabiko": None,
        "panning": None,
    }

    i = 0
    text_accum = []
    play_files = []

    while i < len(message):
        if message.startswith("教育", i):
            word, reading, end_pos = parse_education_command(message, i)
            if word is not None and reading is not None:
                if text_accum:
                    clean_txt = "".join(text_accum).strip()
                    if clean_txt:
                        segments.append({"text": clean_txt, **current_states})
                    text_accum = []
                segments.append({
                    "text": f"{word}が{reading}に辞書登録されました。",
                    "action": "add_dict",
                    "word": word,
                    "reading": reading,
                    **current_states,
                })
                i = end_pos
                continue

        if message.startswith("忘却", i):
            word, end_pos = parse_forget_command(message, i)
            if word is not None:
                if text_accum:
                    clean_txt = "".join(text_accum).strip()
                    if clean_txt:
                        segments.append({"text": clean_txt, **current_states})
                    text_accum = []
                segments.append({
                    "text": f"{word}が辞書から削除されました。",
                    "action": "del_dict",
                    "word": word,
                    **current_states,
                })
                i = end_pos
                continue

        play_match = re.match(r"^(?:再生|音|sound)\(", message[i:])
        if play_match:
            open_paren = i + play_match.end() - 1
            result_chars = []
            k = open_paren + 1
            escaped = False
            found_end = False
            while k < len(message):
                char = message[k]
                if escaped:
                    result_chars.append(char)
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == ")":
                    found_end = True
                    end_pos = k + 1
                    break
                else:
                    result_chars.append(char)
                k += 1
            if found_end:
                play_files.append("".join(result_chars).strip())
                i = end_pos
                continue

        for command, field, converter in (
            ("速度", "speed", lambda value: float(value) / 100.0),
            ("音程", "pitch", lambda value: (float(value) - 100.0) / 100.0 * 0.15),
            ("音量", "volume", lambda value: float(value) / 100.0),
            ("声", "speaker_id", int),
            ("エコー", "echo", int),
            ("やまびこ", "yamabiko", int),
        ):
            match = re.match(rf"^{command}\((\d+)\)", message[i:])
            if not match:
                continue
            if text_accum:
                clean_txt = "".join(text_accum).strip()
                if clean_txt:
                    segments.append({"text": clean_txt, **current_states})
                text_accum = []
            current_states[field] = converter(match.group(1))
            i += match.end()
            break
        else:
            pan_match = re.match(r"^(左|右|両)(?:\)|）)", message[i:])
            if pan_match:
                if text_accum:
                    clean_txt = "".join(text_accum).strip()
                    if clean_txt:
                        segments.append({"text": clean_txt, **current_states})
                    text_accum = []
                direction = pan_match.group(1)
                current_states["panning"] = {"左": "left", "右": "right", "両": "both"}[direction]
                i += pan_match.end()
                continue

            text_accum.append(message[i])
            i += 1
            continue
        continue

    if text_accum:
        clean_txt = "".join(text_accum).strip()
        if clean_txt:
            segments.append({"text": clean_txt, **current_states})

    return segments, play_files


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


def clean_comment(text: str, max_len: int) -> str:
    text = html.unescape(text)
    text = re.sub(r"https?://\S+", "URL", text)
    text = re.sub(r"\s+", " ", text).strip()
    if max_len != -1 and len(text) > max_len:
        text = text[:max_len] + "、以下略"
    return text
