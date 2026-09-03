from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QDialog, QMainWindow, QWidget

from livevoicebridge.infrastructure.config_repository import default_config
from livevoicebridge.paths import COMMENT_WINDOW_UI_FILE, MAIN_UI_FILE, SETTINGS_UI_FILE, TASK_MANAGER_UI_FILE
from livevoicebridge.presentation.comment_window import CommentWindow
from livevoicebridge.presentation.task_manager_widget import TaskManagerWidget


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
        (
            COMMENT_WINDOW_UI_FILE,
            QWidget,
            ["headerBar", "closeButton", "contentSplitter"],
        ),
        (
            TASK_MANAGER_UI_FILE,
            QWidget,
            ["graphGroup", "commentQueueLabel", "youtubeConnectionLabel"],
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


def test_designer_backed_composite_widgets_initialize(qtbot: Any) -> None:
    task_manager = TaskManagerWidget()
    qtbot.addWidget(task_manager)
    assert task_manager.cpu_graph is not None

    main_app = SimpleNamespace(
        config=default_config(),
        save_config=lambda: None,
        set_comment_popout=lambda _enabled: None,
        append_log=lambda _message: None,
    )
    comment_window = CommentWindow(cast(Any, main_app))
    qtbot.addWidget(comment_window)
    assert comment_window.content_splitter is not None
