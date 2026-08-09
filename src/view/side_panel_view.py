"""Extensible full-height side panel for future application features."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class SidePanelView(QFrame):
    """Left workspace region intentionally independent of player and logs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidePanelView")
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )

        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(16, 16, 16, 16)
        self.content_layout.setSpacing(10)

        title = QLabel("WORKSPACE")
        title.setObjectName("sidePanelTitle")
        self.empty_state = QLabel(
            "Future tools, navigation, playlists, or project controls can be "
            "added here."
        )
        self.empty_state.setObjectName("sidePanelEmptyState")
        self.empty_state.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.empty_state.setWordWrap(True)

        self.content_layout.addWidget(title)
        self.content_layout.addWidget(self.empty_state)
        self.content_layout.addStretch(1)

        self.setStyleSheet(
            """
            QFrame#sidePanelView {
                color: #E7EAF0;
                background-color: #141922;
                border: 1px solid #2A3343;
                border-radius: 9px;
            }
            QLabel#sidePanelTitle {
                color: #C8D1E0;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#sidePanelEmptyState {
                color: #7F8A9D;
                font-size: 12px;
                line-height: 1.4;
                padding-top: 8px;
            }
            """
        )

    def add_widget(self, widget: QWidget, stretch: int = 0) -> None:
        """Insert a future side-panel feature above the flexible spacer."""

        spacer_index = self.content_layout.count() - 1
        self.content_layout.insertWidget(spacer_index, widget, stretch)