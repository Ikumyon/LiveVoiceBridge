import time
from collections.abc import Callable

from livevoicebridge import _native


class OwnedProcess:
    """Readiness belongs to HTTP; process ownership belongs to Rust."""

    def __init__(self, executable: str):
        self._executable = executable
        self._process = _native.ManagedProcess()

    def ensure(self, probe: Callable[[], bool]) -> None:
        if probe():
            return
        if not self._executable:
            raise RuntimeError("接続できません。外部エンジンを起動するか、実行ファイルを指定してください。")
        self._process.start(self._executable)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if not self._process.is_running():
                break
            if probe():
                return
            time.sleep(0.1)
        self.close()
        raise TimeoutError("音声エンジンの起動を確認できませんでした。")

    def close(self) -> None:
        self._process.close()
