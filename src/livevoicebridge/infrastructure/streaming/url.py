from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def extract_video_id(text: str) -> str:
    text = text.strip()
    if "youtube.com" not in text and "youtu.be" not in text:
        return text

    url = urlparse(text)

    if "youtu.be" in url.netloc:
        return url.path.strip("/").split("/")[0]

    if url.path == "/watch":
        return parse_qs(url.query).get("v", [""])[0]

    parts = url.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"live", "embed", "shorts"}:
        return parts[1]

    return text
