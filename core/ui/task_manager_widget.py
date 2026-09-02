from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel, QFrame, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from core.ui.components.performance_graph import PerformanceGraphWidget

class TaskManagerWidget(QWidget):
    """マルチデバイス動的レイアウト型 タスクマネージャーウィジェット"""

    def __init__(self, parent=None):
        super().__init__(parent)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(9, 9, 9, 9)
        main_layout.setSpacing(12)

        # スクロールエリア
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget()
        self.content_layout = QVBoxLayout(scroll_content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)

        # 1. パフォーマンスグラフグループ
        self.graph_group = QGroupBox("システムパフォーマンス（リアルタイム推移）", self)
        self.grid_layout = QGridLayout(self.graph_group)
        self.grid_layout.setSpacing(10)
        self.content_layout.addWidget(self.graph_group)

        # 常時存在する基本メトリクスグラフ
        self.cpu_graph = PerformanceGraphWidget("CPU 使用率", QColor(0, 210, 255), "%", 100.0)
        self.ram_graph = PerformanceGraphWidget("メモリ (RAM) 使用量", QColor(255, 215, 64), "%", 100.0)
        self.net_graph = PerformanceGraphWidget(
            "ネットワーク通信速度", [QColor(255, 145, 0), QColor(0, 210, 255)], "KB/s", 1024.0
        )
        self.concurrent_connections_graph = PerformanceGraphWidget(
            "YouTube 同時接続数", QColor(255, 82, 82), "件", 4.0
        )

        # 動的デバイス用辞書 {id: PerformanceGraphWidget}
        self.gpu_core_graphs = {}
        self.gpu_vram_graphs = {}
        self.npu_graph = None

        # 初期描画要素の登録
        self._rebuild_initial_grid()

        # 2. 下部: タスクキュー & 同時接続数エリア
        info_layout = QHBoxLayout()
        info_layout.setSpacing(10)

        # 内部タスク状態グループ
        task_group = QGroupBox("内部タスク & キュー状態", self)
        task_vbox = QVBoxLayout(task_group)

        self.comment_queue_label = QLabel("コメント受信処理キュー: 0 件", self)
        self.tts_queue_label = QLabel("TTS 音声生成キュー: 0 件", self)
        self.speaking_label = QLabel("現在再生中: (なし)", self)
        self.speaking_label.setWordWrap(True)

        task_vbox.addWidget(self.comment_queue_label)
        task_vbox.addWidget(self.tts_queue_label)
        task_vbox.addWidget(self.speaking_label)
        task_vbox.addStretch()

        # 同時接続数グループ
        conn_group = QGroupBox("接続数 & ストリーム状態", self)
        conn_vbox = QVBoxLayout(conn_group)

        self.yt_conn_label = QLabel("YouTube ストリーム: 停止中 (接続数: 0)", self)
        self.tts_conn_label = QLabel("外部 TTS サーバー接続: 待機中", self)
        self.net_sockets_label = QLabel("プロセス内アクティブソケット: --", self)

        conn_vbox.addWidget(self.yt_conn_label)
        conn_vbox.addWidget(self.tts_conn_label)
        conn_vbox.addWidget(self.net_sockets_label)
        conn_vbox.addStretch()

        info_layout.addWidget(task_group, 1)
        info_layout.addWidget(conn_group, 1)

        self.content_layout.addLayout(info_layout)
        scroll.setWidget(scroll_content)

        main_layout.addWidget(scroll)

    def _rebuild_initial_grid(self):
        """基本グラフの配置（3列均等幅）"""
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 1)
        self.grid_layout.setColumnStretch(2, 1)
        self.grid_layout.addWidget(self.cpu_graph, 0, 0)
        self.grid_layout.addWidget(self.ram_graph, 0, 1)
        self.grid_layout.addWidget(self.net_graph, 0, 2)
        self.grid_layout.addWidget(self.concurrent_connections_graph, 1, 0)

    def update_metrics(self, data: dict):
        """収集されたメトリクスでグラフを更新（動的追加対応）"""
        # 1. 基本メトリクス更新
        self.cpu_graph.add_value(data["cpu_percent"], f"{data['cpu_percent']:.1f} %")

        disp_ram = f"{data['ram_used_gb']:.2f} / {data['ram_total_gb']:.1f} GB ({data['ram_percent']:.1f}%)"
        self.ram_graph.add_value(data["ram_percent"], disp_ram)

        net_send = float(data.get("net_send_speed_kb", 0.0))
        net_recv = float(data.get("net_recv_speed_kb", 0.0))

        def _fmt_speed(kb: float) -> str:
            return f"{kb / 1024.0:.2f} MB/s" if kb >= 1024.0 else f"{kb:.1f} KB/s"

        disp_net = f"↓ {_fmt_speed(net_recv)}  ↑ {_fmt_speed(net_send)}"
        max_speed = max((net_send + net_recv) * 1.5, 100.0)
        self.net_graph.add_value([net_recv, net_send], disp_net, dynamic_max=max_speed)

        # 2. GPU群の動的配置 & 更新 (Core + VRAM マルチライン統合)
        gpus = data.get("gpus", [])

        for idx, gpu_info in enumerate(gpus):
            gpu_id = gpu_info.get("id", f"gpu_{idx}")
            raw_name = gpu_info.get("name", f"GPU {idx}")
            # 名前をスッキリ整形 (長いカッコや redundant 表記の整理)
            clean_name = raw_name.replace("GPU 0 (", "GPU 0: ").replace("GPU 1 (", "GPU 1: ").rstrip(")")
            clean_name = clean_name.replace(" (8GB)", "").replace("(TM)", "").replace("(R)", "")

            if gpu_id not in self.gpu_core_graphs:
                # 2色のマルチライン (緑: Core利用率, ピンク: VRAM使用率)
                gpu_graph = PerformanceGraphWidget(
                    clean_name,
                    [QColor(0, 230, 118), QColor(255, 64, 129)],
                    "%",
                    100.0,
                    self.graph_group
                )
                self.gpu_core_graphs[gpu_id] = gpu_graph
                graph_pos = 4 + idx
                row = graph_pos // 3
                col = graph_pos % 3
                self.grid_layout.addWidget(gpu_graph, row, col)

            gpu_perc = gpu_info.get("gpu_percent", 0.0)
            vram_perc = gpu_info.get("vram_percent", 0.0)
            vram_used = gpu_info.get("vram_used_gb", 0.0)
            vram_total = gpu_info.get("vram_total_gb", 0.0)

            if gpu_info.get("has_vram", False):
                vals = [gpu_perc, vram_perc]
                disp_text = f"Core: {gpu_perc:.1f}% | VRAM: {vram_used:.2f}/{vram_total:.1f}GB"
            else:
                vals = [gpu_perc]
                disp_text = f"Core: {gpu_perc:.1f}%"

            self.gpu_core_graphs[gpu_id].add_value(vals, disp_text)

        # 3. NPU の動的配置 & 更新（搭載時のみ表示）
        if data.get("has_npu", False):
            if self.npu_graph is None:
                self.npu_graph = PerformanceGraphWidget("NPU 使用率", QColor(179, 136, 255), "%", 100.0, self.graph_group)
                # グリッドの末尾に追加
                next_pos = self.grid_layout.count()
                row = next_pos // 3
                col = next_pos % 3
                self.grid_layout.addWidget(self.npu_graph, row, col)

            self.npu_graph.add_value(data["npu_percent"], f"{data['npu_percent']:.1f} %")

    def update_task_info(self, comment_queue_len: int, tts_queue_len: int, current_text: str):
        """タスクキューおよび再生情報の更新"""
        self.comment_queue_label.setText(f"コメント受信処理キュー: {comment_queue_len} 件")
        self.tts_queue_label.setText(f"TTS 音声生成キュー: {tts_queue_len} 件")
        text_disp = current_text if current_text else "(なし)"
        self.speaking_label.setText(f"現在再生中: {text_disp}")

    def update_connection_info(self, is_yt_connected: bool, active_connections_count: int, tts_engine_name: str, socket_count: int):
        """同時接続数および通信状態の更新"""
        yt_status = "接続中" if is_yt_connected else "停止中"
        yt_count = 1 if is_yt_connected else 0
        self.yt_conn_label.setText(f"YouTube ストリーム: {yt_status} (同時接続数: {yt_count})")
        self.concurrent_connections_graph.add_value(
            yt_count,
            f"{yt_count} 件",
            dynamic_max=max(4.0, yt_count * 1.5),
        )

        self.tts_conn_label.setText(f"TTS エンジン: {tts_engine_name} (アクティブ接続: {active_connections_count})")
        self.net_sockets_label.setText(f"プロセス内アクティブソケット: {socket_count} 個")
