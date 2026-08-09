"""Reusable application log panel with an append-only text console."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)


class LogView(QFrame):
    """Large read-only text area ready for application-wide log messages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logView")
        self.setMinimumHeight(130)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel("APPLICATION LOG")
        title.setObjectName("logTitle")
        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("clearLogButton")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.clear_button)
        root.addLayout(header)

        self.text_box = QPlainTextEdit()
        self.text_box.setObjectName("logTextBox")
        self.text_box.setReadOnly(True)
        self.text_box.setUndoRedoEnabled(False)
        self.text_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text_box.document().setMaximumBlockCount(5000)
        self.text_box.setPlaceholderText(
            "Application and MIDI messages will appear here"
        )
        root.addWidget(self.text_box, 1)

        self.clear_button.clicked.connect(self.clear)
        self.setStyleSheet(
            """
            QFrame#logView {
                color: #E7EAF0;
                background-color: #141922;
                border: 1px solid #2A3343;
                border-radius: 9px;
            }
            QLabel#logTitle {
                color: #C8D1E0;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QPushButton#clearLogButton {
                color: #9DA8BA;
                background-color: transparent;
                border: 1px solid #384356;
                border-radius: 5px;
                padding: 4px 10px;
            }
            QPushButton#clearLogButton:hover {
                color: #F0F4FA;
                background-color: #293142;
            }
            QPlainTextEdit#logTextBox {
                color: #B9C4D5;
                background-color: #0D1118;
                border: 1px solid #273143;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #31516B;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
            """
        )

    @Slot(str, str)
    def append_log(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        normalized_level = (level or "INFO").upper()
        self.text_box.appendPlainText(
            f"[{timestamp}] [{normalized_level:<5}] {message}"
        )
        self.text_box.moveCursor(QTextCursor.MoveOperation.End)

    @Slot()
    def clear(self) -> None:
        self.text_box.clear()