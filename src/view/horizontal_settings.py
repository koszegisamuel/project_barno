"""Extensible horizontal application toolbar for global actions."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from src.controller.configuration_controller import ConfigurationController


class HorizontalSettingsWidget(QFrame):
    """Top action bar kept separate from the main playback window.

    Add future buttons with :meth:`add_action` rather than expanding
    ``MainWindow._build_ui`` with unrelated application-level controls.
    """

    configuration_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("horizontalSettings")
        self.setFixedHeight(52)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 7, 8, 7)
        self._layout.setSpacing(8)

        self.title_label = QLabel("BARNO")
        self.title_label.setObjectName("toolbarTitle")
        self.subtitle_label = QLabel("MIDI visualizer")
        self.subtitle_label.setObjectName("toolbarSubtitle")

        self._layout.addWidget(self.title_label)
        self._layout.addWidget(self.subtitle_label)
        self._layout.addStretch(1)

        self.configuration_button = QPushButton("Configuration")
        self.configuration_button.setObjectName("configurationButton")
        self.configuration_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.configuration_button.setToolTip("Open application configuration")
        self.configuration_button.setAccessibleName("Configuration")
        self._layout.addWidget(self.configuration_button)

        self.configuration_controller = ConfigurationController(self)
        self.configuration_controller.configuration_saved.connect(
            self.configuration_changed.emit
        )
        # Loading here installs Configuration.current() during window startup.
        self.configuration_controller.load_configuration()
        self.configuration_button.clicked.connect(self.open_configuration)

        self.setStyleSheet(
            """
            QFrame#horizontalSettings {
                background-color: #171B24;
                border: 1px solid #2C3342;
                border-radius: 8px;
            }
            QLabel#toolbarTitle {
                color: #F4F7FB;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#toolbarSubtitle {
                color: #7F899D;
                font-size: 12px;
                padding-left: 4px;
            }
            QPushButton#configurationButton {
                color: #E9EEF8;
                background-color: #252C3A;
                border: 1px solid #3A4559;
                border-radius: 6px;
                padding: 7px 13px;
                font-weight: 600;
            }
            QPushButton#configurationButton:hover {
                background-color: #30394B;
                border-color: #57C7FF;
            }
            QPushButton#configurationButton:pressed {
                background-color: #1E2430;
            }
            """
        )

    def add_action(self, button: QPushButton) -> None:
        """Insert another application action before Configuration."""

        configuration_index = self._layout.indexOf(self.configuration_button)
        self._layout.insertWidget(configuration_index, button)

    def open_configuration(self) -> None:
        self.configuration_controller.open_configuration(self.window())