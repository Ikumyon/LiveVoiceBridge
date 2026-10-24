import argparse
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from livevoicebridge import _native
from livevoicebridge.desktop.resources import ICON_FILE
from livevoicebridge.host.composition import compose
from livevoicebridge.host.paths import AppPaths


def main() -> int:
    parser = argparse.ArgumentParser(description="LiveVoiceBridge")
    parser.parse_args()
    _native.initialize_platform()
    application = QApplication(sys.argv[:1])
    application.setQuitOnLastWindowClosed(False)
    if ICON_FILE.exists():
        application.setWindowIcon(QIcon(str(ICON_FILE)))
    try:
        presenter = compose(AppPaths.resolve())
    except Exception as exc:
        QMessageBox.critical(None, "起動エラー", str(exc))
        return 1
    presenter.window.show()
    result = application.exec()
    presenter.session.shutdown()
    presenter.session.join()
    return result
