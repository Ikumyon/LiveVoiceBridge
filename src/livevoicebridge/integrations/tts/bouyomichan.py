import socket
import struct
from urllib.parse import urlparse

from livevoicebridge.core.speech.models import BouyomiConfig, EngineConfig, Speaker, SpeechControls
from livevoicebridge.integrations.processes.owned import OwnedProcess


class BouyomiChanEngine:
    def __init__(self, config: EngineConfig):
        address = urlparse(config.url if "://" in config.url else f"tcp://{config.url}")
        if not address.hostname or not address.port:
            raise ValueError("棒読みちゃんの接続先はhost:portで指定してください。")
        self._address = (address.hostname, address.port)
        self._process = OwnedProcess(config.executable_path)

    def _probe(self) -> bool:
        try:
            with socket.create_connection(self._address, timeout=1):
                return True
        except OSError:
            return False

    def ensure_ready(self) -> None:
        self._process.ensure(self._probe)

    def speakers(self) -> tuple[Speaker, ...]:
        return tuple(
            Speaker(index, name)
            for index, name in enumerate(
                ("デフォルト", "女性1", "女性2", "男性1", "男性2", "中性", "ロボット", "暗黒", "機械")
            )
        )

    def send(self, text: str, controls: SpeechControls, config: EngineConfig) -> None:
        if not isinstance(config, BouyomiConfig):
            raise TypeError("棒読みちゃんの設定が必要です。")
        speed = int(controls.speed * 100) if controls.speed is not None else config.speed
        pitch = int(controls.pitch / 0.15 * 100 + 100) if controls.pitch is not None else config.pitch
        volume = int(controls.volume * 100) if controls.volume is not None else config.volume
        voice = controls.speaker_id if controls.speaker_id is not None else config.speaker_id
        content = text.encode("utf-8")
        header = struct.pack("<hhhhhbI", 1, speed, pitch, volume, voice, 0, len(content))
        with socket.create_connection(self._address, timeout=2) as connection:
            connection.sendall(header + content)

    def close(self) -> None:
        self._process.close()
