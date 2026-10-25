"""Edit and preview presentation settings independently of the settings shell."""

from dataclasses import replace

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QHeaderView,
    QPushButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from livevoicebridge.core.settings.models import PresentationConfig
from livevoicebridge.desktop.monitoring.popup import POPUP_METRIC_MODES, POPUP_METRIC_PLACEMENTS


class PresentationEditor(QObject):
    changed = Signal()

    def __init__(self, window: QWidget, config: PresentationConfig, catalog: list):
        super().__init__(window)
        self.dialog_window = window
        self.config = config
        self._bind_popout_widgets()
        for slider, spin, value in (
            (self.opacity_slider, self.opacity_spin, config.comment_opacity),
            (self.header_opacity_slider, self.header_opacity_spin, config.header_opacity),
            (self.border_opacity_slider, self.border_opacity_spin, config.border_opacity),
        ):
            slider.setValue(int(value * 100))
            spin.setValue(slider.value())
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(lambda _: self.changed.emit())
        self.bg_color_hex = config.background_color
        self.border_color_hex = config.border_color
        self.update_color_button_style(self.bg_color_button, self.bg_color_hex)
        self.update_color_button_style(self.border_color_button, self.border_color_hex)
        self.bg_color_button.clicked.connect(self.select_bg_color)
        self.border_color_button.clicked.connect(self.select_border_color)
        index = self.popup_metrics_placement_combo.findData(config.popup_metrics.placement)
        self.popup_metrics_placement_combo.setCurrentIndex(max(0, index))
        self._popup_metric_display_modes = dict(config.popup_metrics.display_modes)
        self.refresh_popup_metric_catalog(catalog)
        self.popup_metrics_placement_combo.currentIndexChanged.connect(lambda _: self.changed.emit())

    def read(self) -> PresentationConfig:
        placement = self.popup_metrics_placement_combo.currentData()
        popup = replace(
            self.config.popup_metrics,
            placement=placement if placement in POPUP_METRIC_PLACEMENTS else "top",
            display_modes=tuple(sorted(self.get_popup_display_modes().items())),
        )
        return replace(
            self.config,
            comment_opacity=self.opacity_slider.value() / 100,
            header_opacity=self.header_opacity_slider.value() / 100,
            border_opacity=self.border_opacity_slider.value() / 100,
            background_color=self.bg_color_hex,
            border_color=self.border_color_hex,
            popup_metrics=popup,
        )

    def _bind_popout_widgets(self) -> None:
        # UIからPiP設定ウィジェットを取得
        self.opacity_slider: QSlider = self.dialog_window.findChild(QSlider, "opacitySlider")
        self.opacity_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "opacitySpinBox")
        self.header_opacity_slider: QSlider = self.dialog_window.findChild(QSlider, "headerOpacitySlider")
        self.header_opacity_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "headerOpacitySpinBox")
        self.border_opacity_slider: QSlider = self.dialog_window.findChild(QSlider, "borderOpacitySlider")
        self.border_opacity_spin: QSpinBox = self.dialog_window.findChild(QSpinBox, "borderOpacitySpinBox")
        self.bg_color_button: QPushButton = self.dialog_window.findChild(QPushButton, "bgColorButton")
        self.border_color_button: QPushButton = self.dialog_window.findChild(QPushButton, "borderColorButton")
        self.popup_metrics_placement_combo: QComboBox = self.dialog_window.findChild(
            QComboBox, "popupMetricsPlacementComboBox"
        )
        self.popup_metrics_table: QTableWidget = self.dialog_window.findChild(QTableWidget, "popupMetricsTableWidget")
        self.popup_metrics_placement_combo.clear()
        for placement, label in POPUP_METRIC_PLACEMENTS.items():
            self.popup_metrics_placement_combo.addItem(label, placement)
        self.popup_metrics_table.setColumnCount(2)
        self.popup_metrics_table.setHorizontalHeaderLabels(["項目", "表示"])
        self.popup_metrics_table.verticalHeader().setVisible(False)
        self.popup_metrics_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.popup_metrics_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.popup_metrics_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.popup_metrics_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._popup_metric_display_modes = {}
        self._popup_metric_combos: dict[str, QComboBox] = {}

    def refresh_popup_metric_catalog(self, catalog: list) -> None:
        """検出済みメトリクスを設定表へ反映し、編集中の選択を保持する。"""
        if getattr(self, "_rendered_catalog", None) == catalog:
            return
        self._rendered_catalog = list(catalog)
        current_modes = self.get_popup_display_modes()
        self._popup_metric_display_modes.update(current_modes)
        self.popup_metrics_table.setRowCount(len(catalog))
        self._popup_metric_combos.clear()

        for row, entry in enumerate(catalog):
            metric_id = str(entry.get("id", ""))
            title = str(entry.get("title", metric_id))
            item = QTableWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, metric_id)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.popup_metrics_table.setItem(row, 0, item)

            combo = QComboBox(self.popup_metrics_table)
            for mode, label in POPUP_METRIC_MODES.items():
                combo.addItem(label, mode)
            selected_mode = self._popup_metric_display_modes.get(metric_id, "hidden")
            mode_index = combo.findData(selected_mode)
            combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _, key=metric_id, widget=combo: self._on_popup_metric_mode_changed(key, widget)
            )
            self._popup_metric_combos[metric_id] = combo
            self.popup_metrics_table.setCellWidget(row, 1, combo)

        self._fit_popup_metrics_table_to_contents()

    def _fit_popup_metrics_table_to_contents(self) -> None:
        """内側をスクロールさせず、全メトリクス行が収まる高さにする。"""
        self.popup_metrics_table.resizeRowsToContents()
        rows_height = sum(self.popup_metrics_table.rowHeight(row) for row in range(self.popup_metrics_table.rowCount()))
        header_height = self.popup_metrics_table.horizontalHeader().height()
        frame_height = self.popup_metrics_table.frameWidth() * 2
        self.popup_metrics_table.setFixedHeight(header_height + rows_height + frame_height)

    def _on_popup_metric_mode_changed(self, metric_id: str, combo: QComboBox) -> None:
        self._popup_metric_display_modes[metric_id] = combo.currentData()
        self.changed.emit()

    def get_popup_display_modes(self) -> dict[str, str]:
        modes = dict(self._popup_metric_display_modes)
        for metric_id, combo in self._popup_metric_combos.items():
            mode = combo.currentData()
            modes[metric_id] = mode if mode in POPUP_METRIC_MODES else "hidden"
        return modes

    def select_bg_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.bg_color_hex), self.dialog_window, "背景色を選択")
        if color.isValid():
            self.bg_color_hex = color.name()
            self.update_color_button_style(self.bg_color_button, self.bg_color_hex)
            self.changed.emit()

    def select_border_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.border_color_hex), self.dialog_window, "縁色を選択")
        if color.isValid():
            self.border_color_hex = color.name()
            self.update_color_button_style(self.border_color_button, self.border_color_hex)
            self.changed.emit()

    def update_color_button_style(self, button: QPushButton, hex_color: str) -> None:
        color = QColor(hex_color)
        luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255.0
        text_color = "#000000" if luminance > 0.5 else "#ffffff"
        button.setStyleSheet(
            f"background-color: {hex_color}; color: {text_color}; border: 1px solid #555555; font-weight: bold;"
        )
