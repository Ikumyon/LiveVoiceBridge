from PySide6.QtWidgets import QGridLayout, QGroupBox, QLabel, QWidget

from livevoicebridge.core.telemetry.models import MetricFrame
from livevoicebridge.desktop.forms import load_form
from livevoicebridge.desktop.monitoring.graph import PerformanceGraphWidget


class TaskManagerWidget(QWidget):
    """マルチデバイス動的レイアウト型 タスクマネージャーウィジェット"""

    def __init__(self, parent=None, defer_form=False):
        super().__init__(parent)
        if not defer_form:
            self.initialize_form()

    def initialize_form(self):
        self._content = load_form("task_manager", root=self, widgets=(PerformanceGraphWidget,))
        self.graph_group: QGroupBox = self._content.findChild(QGroupBox, "graphGroup")
        self.grid_layout: QGridLayout = self._content.findChild(QGridLayout, "gridLayout")
        self.comment_queue_label: QLabel = self._content.findChild(QLabel, "commentQueueLabel")
        self.tts_queue_label: QLabel = self._content.findChild(QLabel, "ttsQueueLabel")
        self.speaking_label: QLabel = self._content.findChild(QLabel, "speakingLabel")
        self.yt_conn_label: QLabel = self._content.findChild(QLabel, "youtubeConnectionLabel")
        self.tts_conn_label: QLabel = self._content.findChild(QLabel, "ttsConnectionLabel")
        self.net_sockets_label: QLabel = self._content.findChild(QLabel, "socketLabel")

        self.cpu_graph = self.findChild(PerformanceGraphWidget, "cpuGraph")
        self.ram_graph = self.findChild(PerformanceGraphWidget, "ramGraph")
        self.net_graph = self.findChild(PerformanceGraphWidget, "networkGraph")
        self.concurrent_connections_graph = self.findChild(PerformanceGraphWidget, "connectionsGraph")
        self._fixed_graphs = {
            "cpu": self.cpu_graph,
            "ram": self.ram_graph,
            "network": self.net_graph,
            "youtube_connections": self.concurrent_connections_graph,
        }
        self._gpu_graphs: dict[str, PerformanceGraphWidget] = {}

    def update_metrics(self, frames: tuple[MetricFrame, ...]) -> None:
        wanted = {frame.identifier for frame in frames if frame.identifier not in self._fixed_graphs}
        changed = wanted != set(self._gpu_graphs)
        for key in tuple(self._gpu_graphs):
            if key not in wanted:
                removed_graph = self._gpu_graphs.pop(key)
                self.grid_layout.removeWidget(removed_graph)
                removed_graph.deleteLater()
        for frame in frames:
            graph = self._fixed_graphs.get(frame.identifier)
            if graph is None:
                if frame.identifier not in self._gpu_graphs:
                    self._gpu_graphs[frame.identifier] = PerformanceGraphWidget(parent=self.graph_group)
                graph = self._gpu_graphs[frame.identifier]
            graph.set_frame(frame)
        if changed:
            for index, key in enumerate(sorted(self._gpu_graphs), 4):
                self.grid_layout.addWidget(self._gpu_graphs[key], index // 3, index % 3)

    def update_task_info(self, comment_queue_len: int, tts_queue_len: int, current_text: str, external: bool = False):
        """タスクキューおよび再生情報の更新"""
        self.comment_queue_label.setText(f"コメント受信処理キュー: {comment_queue_len} 件")
        self.tts_queue_label.setText(f"TTS 音声生成キュー: {tts_queue_len} 件")
        text_disp = current_text if current_text else "(なし)"
        label = "外部へ送信中" if external else "現在再生中"
        self.speaking_label.setText(f"{label}: {text_disp}")

    def update_connection_info(
        self, is_yt_connected: bool, active_connections_count: int, tts_engine_name: str, socket_count: int | None
    ):
        """同時接続数および通信状態の更新"""
        yt_status = "接続中" if is_yt_connected else "停止中"
        yt_count = 1 if is_yt_connected else 0
        self.yt_conn_label.setText(f"YouTube ストリーム: {yt_status} (同時接続数: {yt_count})")

        self.tts_conn_label.setText(f"TTS エンジン: {tts_engine_name} (アクティブ接続: {active_connections_count})")
        sockets = f"{socket_count} 個" if socket_count is not None else "取得不可"
        self.net_sockets_label.setText(f"プロセス内アクティブソケット: {sockets}")
