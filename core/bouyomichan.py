import socket
import struct
import io
import wave
from core.tts_engines import BaseTTSEngine

class BouyomiChanEngine(BaseTTSEngine):
    """棒読みちゃん（TCP接続）用の音声合成エンジン。"""
    DEFAULT_URL = "127.0.0.1:50001"

    @classmethod
    def migrate_config(cls, config: dict, loaded_config: dict) -> None:
        """旧フラット構造の設定を 棒読みちゃん 用のネスト構造にマイグレーションする。"""
        if "bouyomichan" not in config or not isinstance(config["bouyomichan"], dict):
            config["bouyomichan"] = {
                "url": cls.DEFAULT_URL,
                "path": "",
                "speaker_id": 0
            }
        
        # 既存の設定から移行できるキーがあれば処理（必要に応じて拡張）
        if "bouyomichan_url" in loaded_config:
            config["bouyomichan"]["url"] = loaded_config["bouyomichan_url"]
        if "bouyomichan_path" in loaded_config:
            config["bouyomichan"]["path"] = loaded_config["bouyomichan_path"]

        config.pop("bouyomichan_url", None)
        config.pop("bouyomichan_path", None)

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
            with socket.create_connection((self.host, self.port), timeout=1) as sock:
                return True
        except Exception:
            return False

    def synthesize_wav(self, text: str, speed: float = None, pitch: float = None, volume: float = None, speaker_id: int = None) -> bytes | None:
        # パラメータのマッピング
        # 速度 (50〜300, -1: デフォルト)
        b_speed = int(speed * 100) if speed is not None else -1
        b_speed = max(50, min(b_speed, 300)) if b_speed != -1 else -1

        # 音程 (50〜200, -1: デフォルト)
        # pitch は通常 -0.15〜0.15 程度のため、200倍して 70〜130 付近にマッピング
        b_pitch = int(100 + pitch * 200) if pitch is not None else -1
        b_pitch = max(50, min(b_pitch, 200)) if b_pitch != -1 else -1

        # 音量 (0〜100, -1: デフォルト)
        b_volume = int(volume * 100) if volume is not None else -1
        b_volume = max(0, min(b_volume, 100)) if b_volume != -1 else -1

        # 声種 (0: デフォルト, 1〜8...)
        b_voice = int(speaker_id) if speaker_id is not None else 0

        # TCP経由で棒読みちゃんにコマンド送信
        try:
            with socket.create_connection((self.host, self.port), timeout=2) as sock:
                text_bytes = text.encode("utf-8")
                text_len = len(text_bytes)
                # コマンド(2B: 0x0001=発声) / 速度(2B) / 音程(2B) / 音量(2B) / 声種(2B) / 文字コード(1B: 0=UTF-8) / 文字列長(4B)
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
        with wave.open(buf, 'wb') as w:
            w.setparams((1, 2, framerate, num_samples, 'NONE', 'not compressed'))
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
                ]
            }
        ]
