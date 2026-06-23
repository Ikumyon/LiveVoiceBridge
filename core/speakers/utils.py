from __future__ import annotations

from pykakasi import kakasi


_kks = kakasi()

SPEAKER_GROUP_ORDER = ["あ行", "か行", "さ行", "た行", "な行", "は行", "ま行", "や行", "ら行", "わ行", "その他"]

KNOWN_SPEAKER_GROUPS = {
    "四国めたん": "さ行",
    "ずんだもん": "さ行",
    "春日部つむぎ": "か行",
    "雨晴はう": "あ行",
    "波音リツ": "は行",
    "玄野武宏": "か行",
    "白上虎太郎": "さ行",
    "青山龍星": "あ行",
    "冥鳴ひまり": "ま行",
    "九州そら": "か行",
    "もち子さん": "ま行",
    "剣崎めすの": "か行",
}


def to_hiragana(text: str) -> str:
    result = _kks.convert(text)
    return "".join(item["hira"] for item in result)


def get_speaker_group(name: str) -> str:
    if not name:
        return "その他"

    if name in KNOWN_SPEAKER_GROUPS:
        return KNOWN_SPEAKER_GROUPS[name]

    hira_name = to_hiragana(name)
    if not hira_name:
        return "その他"

    first_char = hira_name[0]

    if first_char in "あいうえおぁぃぅぇぉ":
        return "あ行"
    if first_char in "かきくけこがぎぐげご":
        return "か行"
    if first_char in "さしすせそざじずぜぞ":
        return "さ行"
    if first_char in "たちつてとだぢづでどっ":
        return "た行"
    if first_char in "なにぬねの":
        return "な行"
    if first_char in "はひふへほばびぶべぼぱぴぷぺぽ":
        return "は行"
    if first_char in "まみむめも":
        return "ま行"
    if first_char in "やゆよゃゅょ":
        return "や行"
    if first_char in "らりるれろ":
        return "ら行"
    if first_char in "わをんゐゑ":
        return "わ行"

    return "その他"


def speaker_sort_key(name: str) -> str:
    return to_hiragana(name)


def group_speakers_by_kana(speakers_data: dict[str, list[tuple[str, int]]]) -> dict[str, dict[str, list[tuple[str, int]]]]:
    grouped_speakers = {group_name: {} for group_name in SPEAKER_GROUP_ORDER}
    for speaker_name, styles in speakers_data.items():
        group = get_speaker_group(speaker_name)
        if group not in grouped_speakers:
            group = "その他"
        grouped_speakers[group][speaker_name] = styles
    return grouped_speakers
