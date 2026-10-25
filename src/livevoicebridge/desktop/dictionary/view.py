"""Dictionary widgets and user intent, independent of the settings shell."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QWidget,
)

from livevoicebridge.core.dictionary.models import DictionaryConfig
from livevoicebridge.desktop.dictionary.delegates import HiraganaDelegate
from livevoicebridge.desktop.dictionary.model import DictionaryTableModel


class DictionaryView(QObject):
    settings_changed = Signal()
    dictionary_requested = Signal(str, object)

    def __init__(self, window: QWidget, config: DictionaryConfig):
        super().__init__(window)
        self.dialog_window = window
        self.button_box = window.findChild(QDialogButtonBox, "buttonBox")
        self._bind_dictionary_widgets()
        self._setup_dictionary_table()
        self.current_active_group_name = config.active_group
        self._dictionary_view_loaded = self.settings_tabs.currentWidget() is self.dictionary_tab
        self.add_word_button.clicked.connect(self.add_word_row)
        self.delete_word_button.clicked.connect(self.delete_word_row)
        self.import_word_button.clicked.connect(self.import_words)
        self.add_group_button.clicked.connect(self.add_dictionary_group)
        self.rename_group_button.clicked.connect(self.rename_dictionary_group)
        self.delete_group_button.clicked.connect(self.delete_dictionary_group)
        self.group_combo.currentTextChanged.connect(self.on_group_changed)
        self.settings_tabs.currentChanged.connect(self.on_settings_tab_changed)

    def read(self) -> DictionaryConfig:
        return DictionaryConfig(active_group=self.group_combo.currentText() or self.current_active_group_name)

    def _bind_dictionary_widgets(self) -> None:
        # 読み替え辞書UIのバインド
        self.settings_tabs: QTabWidget = self.dialog_window.findChild(QTabWidget, "settingsTabWidget")
        self.dictionary_tab: QWidget = self.dialog_window.findChild(QWidget, "dictionaryTab")
        self.word_table: QTableView = self.dialog_window.findChild(QTableView, "wordTableView")
        self.add_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "addWordButton")
        self.delete_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "deleteWordButton")
        self.import_word_button: QPushButton = self.dialog_window.findChild(QPushButton, "importWordButton")
        self.group_combo: QComboBox = self.dialog_window.findChild(QComboBox, "dictionaryGroupComboBox")
        self.add_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "addGroupButton")
        self.rename_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "renameGroupButton")
        self.delete_group_button: QPushButton = self.dialog_window.findChild(QPushButton, "deleteGroupButton")

    def _setup_dictionary_table(self) -> None:
        self.word_model = DictionaryTableModel(self.word_table)
        self.word_table.setModel(self.word_model)
        self.word_table.horizontalHeader().setStretchLastSection(True)
        self.word_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.word_table.verticalHeader().setSectionsMovable(False)
        # 読み列（0列目）をひらがな限定に制限
        self.word_table.setItemDelegateForColumn(0, HiraganaDelegate(self.word_table))

    def on_group_changed(self, new_group_name: str) -> None:
        self.current_active_group_name = new_group_name
        self.dictionary_requested.emit("select", self.group_combo.currentData())

    def on_settings_tab_changed(self, _index: int) -> None:
        if self.settings_tabs.currentWidget() is self.dictionary_tab:
            self._load_dictionary_view()

    def _load_dictionary_view(self) -> None:
        self._dictionary_view_loaded = True
        self.dictionary_requested.emit("load", None)

    def add_word_row(self) -> None:
        self.dictionary_requested.emit("append", None)

    def delete_word_row(self) -> None:
        entry = self.word_model.entry(self.word_table.currentIndex().row())
        if entry is not None:
            self.dictionary_requested.emit("delete", entry)

    def import_words(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.dialog_window,
            "辞書インポート",
            "",
            "JSON Files (*.json);;CSV Files (*.csv);;Text Files (*.txt)",
        )
        if path:
            self.dictionary_requested.emit("import", path)

    def add_dictionary_group(self) -> None:
        name, accepted = QInputDialog.getText(self.dialog_window, "グループ追加", "新しい辞書グループ名:")
        if accepted and name.strip():
            self.dictionary_requested.emit("add_group", name.strip())

    def rename_dictionary_group(self) -> None:
        name, accepted = QInputDialog.getText(
            self.dialog_window,
            "グループ名変更",
            "新しいグループ名:",
            QLineEdit.EchoMode.Normal,
            self.group_combo.currentText(),
        )
        if accepted and name.strip():
            self.dictionary_requested.emit("rename_group", name.strip())

    def delete_dictionary_group(self) -> None:
        if (
            QMessageBox.question(
                self.dialog_window,
                "グループ削除",
                f"グループ「{self.group_combo.currentText()}」を削除しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.dictionary_requested.emit("delete_group", None)
