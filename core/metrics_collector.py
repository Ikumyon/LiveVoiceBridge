import logging
import time
from PySide6.QtCore import QThread, Signal
from livevoicebridge_native import RustMetricsCollector

logger = logging.getLogger(__name__)

class MetricsCollector:
    """共通Rustネイティブコアを用いた高速メトリクス収集クラス。"""

    def __init__(self):
        self._rust_collector = RustMetricsCollector()

    def collect(self) -> dict:
        """システムリソース（CPU, RAM, ネットワーク, GPU, NPU）のスナップショットを取得"""
        return self._rust_collector.collect()


class MetricsWorker(QThread):
    """バックグラウンドで Rust メトリクスを定期収集しシグナルを発行するワーカースレッド"""

    metrics_collected = Signal(dict)

    def __init__(self, interval_sec: float = 1.0, parent=None):
        super().__init__(parent)
        self.interval_sec = max(0.1, float(interval_sec))
        self.running = True
        self.collector = None

    def run(self) -> None:
        if self.collector is None:
            self.collector = MetricsCollector()

        while self.running:
            try:
                data = self.collector.collect()
                self.metrics_collected.emit(data)
            except Exception as e:
                logger.error(f"Error in MetricsWorker: {e}")

            sleep_chunks = int(self.interval_sec * 10)
            for _ in range(max(1, sleep_chunks)):
                if not self.running:
                    break
                time.sleep(0.1)

    def stop(self) -> None:
        self.running = False
        self.wait(1000)
