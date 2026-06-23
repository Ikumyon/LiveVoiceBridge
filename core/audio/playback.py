from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile


def apply_audio_effects(wav_path: str, echo_level: int = None, yamabiko_level: int = None, panning: str = None) -> str:
    if not echo_level and not yamabiko_level and not panning:
        return wav_path

    import struct
    import wave

    try:
        with wave.open(wav_path, "rb") as w_in:
            params = w_in.getparams()
            nchannels, sampwidth, framerate, nframes, comptype, compname = params

            if sampwidth != 2:
                return wav_path

            raw_data = w_in.readframes(nframes)

        samples = list(struct.unpack(f"<{nframes * nchannels}h", raw_data))

        if echo_level or yamabiko_level:
            delay_seconds = 0.15 if echo_level else 0.35
            delay_frames = int(framerate * delay_seconds)
            delay_samples = delay_frames * nchannels

            if yamabiko_level:
                decay = min(max(yamabiko_level / 100.0, 0.1), 0.8)
                repetitions = 3
            else:
                decay = min(max(echo_level / 100.0, 0.1), 0.8)
                repetitions = 1

            extra_samples = delay_samples * repetitions
            out_samples = [0] * (len(samples) + extra_samples)

            for i in range(len(samples)):
                out_samples[i] += samples[i]
                for r in range(1, repetitions + 1):
                    delay_idx = i + r * delay_samples
                    if delay_idx < len(out_samples):
                        echo_val = int(samples[i] * (decay ** r))
                        out_samples[delay_idx] += echo_val
            samples = out_samples

        clipped_samples = []
        for sample in samples:
            if sample > 32767:
                clipped_samples.append(32767)
            elif sample < -32768:
                clipped_samples.append(-32768)
            else:
                clipped_samples.append(int(sample))

        if panning in ("left", "right"):
            panned_samples = []
            if nchannels == 1:
                nchannels = 2
                for sample in clipped_samples:
                    if panning == "left":
                        panned_samples.extend([sample, 0])
                    else:
                        panned_samples.extend([0, sample])
            elif nchannels == 2:
                for i in range(0, len(clipped_samples), 2):
                    left_val = clipped_samples[i]
                    right_val = clipped_samples[i + 1]
                    if panning == "left":
                        panned_samples.extend([left_val, 0])
                    else:
                        panned_samples.extend([0, right_val])
            clipped_samples = panned_samples

        out_data = struct.pack(f"<{len(clipped_samples)}h", *clipped_samples)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp_out:
            new_wav_path = fp_out.name

        with wave.open(new_wav_path, "wb") as w_out:
            w_out.setparams((nchannels, sampwidth, framerate, len(clipped_samples) // nchannels, comptype, compname))
            w_out.writeframes(out_data)

        try:
            os.remove(wav_path)
        except OSError:
            pass

        return new_wav_path
    except Exception as e:
        print(f"Effect processing error: {e}")
        return wav_path


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
