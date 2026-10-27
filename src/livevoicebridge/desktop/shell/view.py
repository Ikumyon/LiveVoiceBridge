from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication

from livevoicebridge.desktop.monitoring.view import TaskManagerWidget
from livevoicebridge.desktop.resources.forms.ui_main_window import create_form


class ShellView(QObject):
    close_requested = Signal()

    def __init__(self):
        super().__init__()
        self.window = create_form()
        self.task_manager = self.window.findChild(TaskManagerWidget, "taskManagerWidget")
        if self.task_manager is None:
            raise RuntimeError("タスク表示がUIファイルに定義されていません。")
        self._closing = False
        self._completed = False
        self.window.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.window and event.type() == QEvent.Type.Close and not self._completed:
            event.ignore()
            if not self._closing:
                self._closing = True
                self.window.setEnabled(False)
                self.close_requested.emit()
            return True
        return False

    def complete_shutdown(self) -> None:
        self._completed = True
        self.window.removeEventFilter(self)
        self.window.close()
        QApplication.instance().quit()
