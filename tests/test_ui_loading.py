from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QDialog, QMainWindow, QWidget

from core.app_config import MAIN_UI_FILE, SETTINGS_UI_FILE


@pytest.mark.parametrize(
    ("ui_path", "expected_type", "required_names"),
    [
        (
            MAIN_UI_FILE,
            QMainWindow,
            ["urlLineEdit", "startButton", "stopButton", "commentListWidget", "statusLabel"],
        ),
        (
            SETTINGS_UI_FILE,
            QDialog,
            ["settingsTabWidget", "ttsEngineComboBox", "wordTableWidget", "buttonBox"],
        ),
    ],
)
def test_designer_ui_loads_with_required_widgets(
    qtbot: Any,
    ui_path: Any,
    expected_type: type[QWidget],
    required_names: list[str],
) -> None:
    loader = QUiLoader()
    ui_file = QFile(str(ui_path))
    assert ui_file.open(QFile.OpenModeFlag.ReadOnly)
    try:
        widget = loader.load(ui_file)
    finally:
        ui_file.close()

    assert isinstance(widget, expected_type)
    qtbot.addWidget(widget)
    for object_name in required_names:
        assert widget.findChild(QWidget, object_name) is not None
