from __future__ import annotations

from pykakasi import kakasi
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QPushButton, QWidget

from livevoicebridge.core.speech.models import Speaker

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


def group_speakers_by_kana(
    speakers_data: dict[str, list[tuple[str, str]]],
) -> dict[str, dict[str, list[tuple[str, str]]]]:
    grouped_speakers: dict[str, dict[str, list[tuple[str, str]]]] = {
        group_name: {} for group_name in SPEAKER_GROUP_ORDER
    }
    for speaker_name, styles in speakers_data.items():
        group = get_speaker_group(speaker_name)
        if group not in grouped_speakers:
            group = "その他"
        grouped_speakers[group][speaker_name] = styles
    return grouped_speakers


class SpeakerMenu(QObject):
    changed = Signal()
    requested = Signal()

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.dialog_window = window
        self.speaker_button = window.findChild(QPushButton, "speakerButton")
        self.speakers_data: dict[str, list[tuple[str, str]]] = {}
        self.current_speaker_id = "0"
        self.speaker_menu = QMenu(window)
        self.speaker_button.setMenu(self.speaker_menu)
        self.speaker_menu.aboutToShow.connect(self.requested.emit)

    def receive(self, speakers: tuple[Speaker, ...]) -> None:
        self.speakers_data = {}
        for speaker in speakers:
            self.speakers_data.setdefault(speaker.name, []).append((speaker.style, speaker.identifier))
        self.rebuild_speaker_menu()
        self.set_speaker_button_id(self.current_speaker_id)

    def select_engine(self, identifier: str) -> None:
        self.speakers_data = {}
        self.rebuild_speaker_menu()
        self.set_speaker_button_id(identifier)

    def rebuild_speaker_menu(self) -> None:
        self.speaker_menu.clear()
        grouped_speakers = group_speakers_by_kana(self.speakers_data)

        # グループごとにメニューを作成
        for group_name in SPEAKER_GROUP_ORDER:
            speakers_in_group = grouped_speakers[group_name]
            if not speakers_in_group:
                continue

            # 五十音グループのサブメニューを作成 (例: "あ行")
            group_menu = self.speaker_menu.addMenu(group_name)

            sorted_speakers = sorted(speakers_in_group.keys(), key=speaker_sort_key)

            for speaker_name in sorted_speakers:
                styles = speakers_in_group[speaker_name]
                char_menu = group_menu.addMenu(speaker_name)
                for style_name, style_id in styles:
                    action = QAction(style_name, self.dialog_window)
                    action.setData(style_id)
                    action.triggered.connect(
                        lambda checked=False, s_name=speaker_name, st_name=style_name, s_id=style_id: (
                            self.on_style_selected(s_name, st_name, s_id)
                        )
                    )
                    char_menu.addAction(action)

    def on_style_selected(self, speaker_name: str, style_name: str, speaker_id: str) -> None:
        self.current_speaker_id = speaker_id
        self.speaker_button.setText(f"{speaker_name} ({style_name})")
        self.changed.emit()

    def set_speaker_button_id(self, speaker_id: str) -> None:
        self.current_speaker_id = speaker_id
        found = False
        for speaker_name, styles in self.speakers_data.items():
            for style_name, style_id in styles:
                if style_id == speaker_id:
                    self.speaker_button.setText(f"{speaker_name} ({style_name})")
                    found = True
                    break
            if found:
                break

        if not found:
            self.speaker_button.setText(f"カスタム (ID: {speaker_id})")
