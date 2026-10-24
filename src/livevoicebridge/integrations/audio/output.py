from pathlib import Path

from livevoicebridge import _native
from livevoicebridge.core.speech.models import AudioData, SpeechControls
from livevoicebridge.integrations.native.audio import NativePcmBuffer


class SystemAudioOutput:
    def __init__(self, sounds: Path):
        self._player = _native.AudioPlayer(str(sounds))

    def play(self, audio: AudioData, controls: SpeechControls) -> None:
        if not isinstance(audio.buffer, NativePcmBuffer):
            raise TypeError("Rust所有のPCMバッファが必要です。")
        self._player.play(audio.buffer.clip)

    def sound(self, filename: str, overlap: bool) -> None:
        self._player.sound(filename, overlap)

    def drain_errors(self) -> tuple[str, ...]:
        return tuple(self._player.drain_errors())

    def close(self) -> None:
        self._player.close()
