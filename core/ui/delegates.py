from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit, QStyledItemDelegate


class HiraganaDelegate(QStyledItemDelegate):
    """読み列（0列目）をひらがなのみ入力に制限するデリゲート。"""

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        # ひらがな・長音符・句読点などを許可する正規表現
        pattern = QRegularExpression("[\u3040-\u309F\u30FC]*")
        validator = QRegularExpressionValidator(pattern, editor)
        editor.setValidator(validator)
        return editor
