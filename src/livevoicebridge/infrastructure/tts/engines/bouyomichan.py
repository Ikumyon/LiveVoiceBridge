import io
import socket
import struct
import wave

from livevoicebridge.infrastructure.tts.base import BaseTTSEngine


class BouyomiChanEngine(BaseTTSEngine):
    """棒読みちゃん（TCP接続）用の音声合成エンジン。"""

    DISPLAY_NAME = "BOUYOMICHAN"
    DEFAULT_URL = "127.0.0.1:50001"

    def __init__(self, url: str, exe_path: str = ""):
        super().__init__(url, exe_path)
        # url が 127.0.0.1:50001 や http://127.0.0.1:50001 に対応
        url_clean = self.url.replace("http://", "").replace("https://", "")
        if ":" in url_clean:
            self.host, port_str = url_clean.split(":", 1)
            try:
                self.port = int(port_str)
            except ValueError:
                self.port = 50001
        else:
            self.host = url_clean or "127.0.0.1"
            self.port = 50001

    def is_running(self) -> bool:
        """TCP 50001番ポートへの接続を試み、棒読みちゃんの起動状態をチェックする。"""
        try:
            with socket.create_connection((self.host, self.port), timeout=1):
                return True
        except Exception:
            return False

    def synthesize_wav(
        self,
        text: str,
        speed: float = None,
        pitch: float = None,
        intonation: float = None,
        volume: float = None,
        pause_length: float = None,
        pre_phoneme_length: float = None,
        post_phoneme_length: float = None,
        speaker_id: int = None,
    ) -> bytes | None:
        # パラメータのマッピング (UIから送られる speed, pitch, volume はすでに整数値である前提)
        b_speed = int(speed) if speed is not None else -1
        b_pitch = int(pitch) if pitch is not None else -1
        b_volume = int(volume) if volume is not None else -1
        b_voice = int(speaker_id) if speaker_id is not None else 0

        # TCP経由で棒読みちゃんにコマンド送信
        try:
            with socket.create_connection((self.host, self.port), timeout=2) as sock:
                text_bytes = text.encode("utf-8")
                text_len = len(text_bytes)
                # 0x0001=発声。速度・音程・音量・声種・文字コード・文字列長を続ける。
                header = struct.pack("<hhhhhbI", 1, b_speed, b_pitch, b_volume, b_voice, 0, text_len)
                sock.sendall(header + text_bytes)
        except Exception as e:
            # 棒読みちゃんに接続できない場合はNoneを返して再生をスキップ
            print(f"[棒読みちゃんエラー] 送信失敗: {e}")
            return None

        # テキストの長さに応じた無音時間を計算（1文字あたり約0.15秒、最低0.5秒）
        duration = max(0.5, len(text) * 0.15)
        framerate = 24000
        num_samples = int(duration * framerate)
        silent_data = b"\x00\x00" * num_samples  # 16-bit PCM mono (00)

        # 無音WAVをメモリ上に生成
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setparams((1, 2, framerate, num_samples, "NONE", "not compressed"))
            w.writeframes(silent_data)

        return buf.getvalue()

    def get_speakers(self) -> list[dict] | None:
        """棒読みちゃんの声種（話者）の固定リストを返す。"""
        return [
            {
                "name": "棒読みちゃん",
                "styles": [
                    {"name": "デフォルト", "id": 0},
                    {"name": "女性1", "id": 1},
                    {"name": "女性2", "id": 2},
                    {"name": "男性1", "id": 3},
                    {"name": "男性2", "id": 4},
                    {"name": "中性", "id": 5},
                    {"name": "ロボット", "id": 6},
                    {"name": "暗黒", "id": 7},
                    {"name": "機械", "id": 8},
                ],
            }
        ]
