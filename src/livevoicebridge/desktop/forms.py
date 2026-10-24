from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QFile
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget

from livevoicebridge.desktop.resources import UI_DIR


class _FormLoader(QUiLoader):
    def __init__(self, root: QWidget | None, widgets: tuple[type[QWidget], ...]):
        super().__init__()
        self._root = root
        self._widgets = {widget.__name__: widget for widget in widgets}
        self.deferred: list[QWidget] = []

    def createWidget(self, class_name, parent=None, name=""):  # noqa: N802
        if parent is None and self._root is not None:
            widget = self._root
        elif class_name in self._widgets:
            widget_type = self._widgets[class_name]
            if hasattr(widget_type, "initialize_form"):
                factory = cast(Callable[..., QWidget], widget_type)
                widget = factory(parent=parent, defer_form=True)
                self.deferred.append(widget)
            else:
                widget = widget_type(parent=parent)
        else:
            widget = super().createWidget(class_name, parent, name)
        widget.setObjectName(name)
        return widget


def load_form(name: str, root: QWidget | None = None, widgets: tuple[type[QWidget], ...] = ()) -> QWidget:
    path = UI_DIR / f"{name}.ui"
    source = QFile(str(path))
    if not source.open(QFile.OpenModeFlag.ReadOnly):
        raise RuntimeError(f"UIファイルを開けません: {path}")
    loader = _FormLoader(root, widgets)
    root_name = root.objectName() if root is not None else ""
    try:
        widget = loader.load(source)
        if widget is None:
            raise RuntimeError(f"UI読み込み失敗: {path}: {loader.errorString()}")
        if root is not None and root_name:
            root.setObjectName(root_name)
        # Nested QUiLoader.load calls during createWidget destroy child widgets.
        # Materialize promoted forms only after their containing load returns.
        for promoted in loader.deferred:
            promoted.initialize_form()
        return widget
    finally:
        source.close()
