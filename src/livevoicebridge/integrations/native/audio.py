import io
from dataclasses import dataclass

import requests

from livevoicebridge import _native
from livevoicebridge.core.speech.models import AudioData, SpeechControls


@dataclass(frozen=True, slots=True)
class NativePcmBuffer:
    clip: _native.AudioClip

    @property
    def byte_length(self) -> int:
        return self.clip.byte_length


def decode_wav(wav: bytes, controls: SpeechControls, max_bytes: int) -> AudioData:
    if len(wav) > max_bytes + 65536:
        raise ValueError("合成音声が容量上限を超えました。")
    clip = _native.AudioClip.from_wav(wav, max_bytes, controls.echo, controls.yamabiko, controls.panning)
    return AudioData(NativePcmBuffer(clip))


def decode_response(response: requests.Response, controls: SpeechControls, max_bytes: int) -> AudioData:
    limit = max_bytes + 65536
    try:
        response.raise_for_status()
        with io.BytesIO() as data:
            for chunk in response.iter_content(65536):
                if data.tell() + len(chunk) > limit:
                    raise ValueError("音声応答が容量上限を超えました。")
                data.write(chunk)
            clip = _native.AudioClip.from_wav(
                data.getvalue(), max_bytes, controls.echo, controls.yamabiko, controls.panning
            )
        return AudioData(NativePcmBuffer(clip))
    finally:
        response.close()
