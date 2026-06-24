import os
import subprocess
import platform
import requests
import time
from abc import ABC, abstractmethod

class BaseTTSEngine(ABC):
    DEFAULT_URL = ""
    DISPLAY_NAME = "TTS"
    REQUIRES_URL = True
    IS_LOCAL_ENGINE = False

    @classmethod
    def migrate_config(cls, config: dict, loaded_config: dict) -> None:
        pass

    def __init__(self, url: str, exe_path: str = ""):
        self.url = url.rstrip("/")
        self.exe_path = exe_path
        self.process = None

    @abstractmethod
    def synthesize_wav(self, text: str, speed: float = None, pitch: float = None, volume: float = None, speaker_id: int = None) -> bytes | None:
        pass

    @abstractmethod
    def get_speakers(self) -> list[dict] | None:
        pass

    def ensure_running(self) -> bool:
        """接続を確認し、起動していなければ自動起動を試みる。"""
        if self.is_running():
            return True

        if not self.exe_path or not os.path.exists(self.exe_path):
            return False

        try:
            creationflags = 0
            if platform.system() == "Windows":
                creationflags = 0x08000000  # CREATE_NO_WINDOW
            
            self.process = subprocess.Popen(
                [self.exe_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
        except Exception:
            return False

        # 起動を待つ（最大20秒）
        for _ in range(20):
            if self.process.poll() is not None:
                self.process = None
                return False

            if self.is_running():
                return True
            time.sleep(1)

        return False

    def is_running(self) -> bool:
        if not self.REQUIRES_URL:
            return True
        try:
            response = requests.get(f"{self.url}/speakers", timeout=1)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        return False

    def terminate(self) -> None:
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None



