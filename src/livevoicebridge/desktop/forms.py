"""Construct Designer forms from generated Python without a runtime UI loader."""

from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


class Form(Protocol):
    def setupUi(self, widget: QWidget) -> None: ...  # noqa: N802


def setup_form[W: QWidget](form: Form, root_type: type[W], root: W | None = None) -> W:
    widget = root if root is not None else root_type()
    name = widget.objectName()
    flags = widget.windowFlags()
    attributes = {
        attribute: widget.testAttribute(attribute)
        for attribute in (Qt.WidgetAttribute.WA_TranslucentBackground, Qt.WidgetAttribute.WA_DeleteOnClose)
    }
    form.setupUi(widget)
    if root is not None:
        if name:
            widget.setObjectName(name)
        if widget.windowFlags() != flags:
            widget.setWindowFlags(flags)
        for attribute, enabled in attributes.items():
            if widget.testAttribute(attribute) != enabled:
                widget.setAttribute(attribute, enabled)
    return widget
