"""Responsive application shell composed from focused child views."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.view.horizontal_settings import HorizontalSettingsWidget
from src.view.log_view import LogView
from src.view.midi_player_view import MidiPlayerView
from src.view.side_panel_view import SidePanelView


class MainWindow(QMainWindow):
    """Top-level window responsible only for responsive view composition."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller

        self.setWindowTitle("Barno")
        self.resize(1280, 850)
        self.setMinimumSize(900, 650)
        self._build_ui()
        self._connect_child_views()

    def _build_ui(self) -> None:
        central_widget = QWidget()
        central_widget.setObjectName("mainWindowRoot")
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        # Global settings always occupy the full width at the top.
        self.horizontal_settings = HorizontalSettingsWidget(self)
        root_layout.addWidget(self.horizontal_settings)

        # Left navigation and right workspace resize independently. The 1:4
        # stretch ratio keeps the side view close to one quarter of the player.
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.setChildrenCollapsible(False)

        self.side_panel_view = SidePanelView()
        self.side_panel_view.setMinimumWidth(180)

        # The right side is vertically adjustable: MIDI player above, logs below.
        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setObjectName("rightSplitter")
        self.right_splitter.setChildrenCollapsible(False)
        self.midi_player_view = MidiPlayerView(self.controller)
        self.log_view = LogView()
        self.right_splitter.addWidget(self.midi_player_view)
        self.right_splitter.addWidget(self.log_view)
        self.right_splitter.setStretchFactor(0, 4)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([600, 170])

        self.content_splitter.addWidget(self.side_panel_view)
        self.content_splitter.addWidget(self.right_splitter)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 4)
        self.content_splitter.setSizes([240, 960])
        root_layout.addWidget(self.content_splitter, 1)

        self.setCentralWidget(central_widget)
        self.setStyleSheet(
            """
            QMainWindow, QWidget#mainWindowRoot {
                background-color: #0E1118;
                color: #E7EAF0;
            }
            QSplitter::handle {
                background-color: #0E1118;
            }
            QSplitter#contentSplitter::handle:horizontal {
                width: 8px;
            }
            QSplitter#rightSplitter::handle:vertical {
                height: 8px;
            }
            QSplitter::handle:hover {
                background-color: #283247;
            }
            """
        )

    def _connect_child_views(self) -> None:
        # Cross-view communication belongs at the composition level. The player
        # remains reusable and has no dependency on MainWindow or LogView.
        self.midi_player_view.log_message.connect(self.log_view.append_log)
        self.midi_player_view.title_changed.connect(self.setWindowTitle)
        self.log_view.append_log("Application interface initialized", "INFO")