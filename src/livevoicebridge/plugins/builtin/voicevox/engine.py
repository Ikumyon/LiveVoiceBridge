import requests

from livevoicebridge.core.speech.models import AudioData, EngineConfig, Speaker, SpeechControls
from livevoicebridge.integrations.native.audio import decode_response
from livevoicebridge.integrations.processes.owned import OwnedProcess


class VoicevoxEngine:
    def __init__(self, config: EngineConfig):
        self._url = str(config.settings["url"]).rstrip("/")
        self._process = OwnedProcess(str(config.settings["executable_path"]))

    def _probe(self) -> bool:
        try:
            return requests.get(f"{self._url}/speakers", timeout=(1, 1)).ok
        except requests.RequestException:
            return False

    def ensure_ready(self) -> None:
        self._process.ensure(self._probe)

    def speakers(self) -> tuple[Speaker, ...]:
        response = requests.get(f"{self._url}/speakers", timeout=(2, 5))
        response.raise_for_status()
        return tuple(
            Speaker(str(style["id"]), str(speaker["name"]), str(style["name"]))
            for speaker in response.json()
            for style in speaker["styles"]
        )

    def synthesize(self, text: str, controls: SpeechControls, config: EngineConfig, max_bytes: int) -> AudioData:
        speaker = int(controls.speaker_id) if controls.speaker_id is not None else int(config.speaker_id)
        response = requests.post(
            f"{self._url}/audio_query",
            params={"text": text, "speaker": speaker},
            timeout=(2, 10),
        )
        response.raise_for_status()
        query = response.json()
        query.update(
            {
                "speedScale": controls.speed if controls.speed is not None else float(str(config.settings["speed"])),
                "pitchScale": controls.pitch if controls.pitch is not None else float(str(config.settings["pitch"])),
                "volumeScale": controls.volume
                if controls.volume is not None
                else float(str(config.settings["volume"])),
                "intonationScale": float(str(config.settings["intonation"])),
                "pauseLengthScale": float(str(config.settings["pause_length"])),
                "prePhonemeLength": float(str(config.settings["pre_phoneme_length"])),
                "postPhonemeLength": float(str(config.settings["post_phoneme_length"])),
            }
        )
        response = requests.post(
            f"{self._url}/synthesis", params={"speaker": speaker}, json=query, timeout=(2, 30), stream=True
        )
        return decode_response(response, controls, max_bytes)

    def close(self) -> None:
        self._process.close()
