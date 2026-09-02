from __future__ import annotations

import platform
import shutil
import subprocess

from livevoicebridge_native import apply_audio_effects


def play_wav(path: str) -> None:
    system = platform.system()

    if system == "Windows":
        import winsound

        winsound.PlaySound(path, winsound.SND_FILENAME)
        return

    if system == "Linux":
        for command in ("pw-play", "paplay", "aplay"):
            exe = shutil.which(command)
            if not exe:
                continue
            if command == "aplay":
                subprocess.run([exe, "-q", path], check=False)
            else:
                subprocess.run([exe, path], check=False)
            return
        raise RuntimeError("Linuxの音声再生コマンドが見つかりません。alsa-utils等を入れてください。")

    if system == "Darwin":
        exe = shutil.which("afplay")
        if exe:
            subprocess.run([exe, path], check=False)
            return

    raise RuntimeError(f"未対応OSです: {system}")
