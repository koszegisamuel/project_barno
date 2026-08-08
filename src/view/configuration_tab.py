"""Modern modal view for editing application configuration."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Signal, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ToggleButton(QAbstractButton):
    """Painted switch control that renders consistently across platforms."""

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(48, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Show playback notes")

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        track_color = QColor("#35C980") if self.isChecked() else QColor("#3A4353")
        painter.setBrush(track_color)
        painter.drawRoundedRect(QRectF(0, 1, 48, 24), 12, 12)

        knob_x = 25 if self.isChecked() else 3
        painter.setBrush(QColor("#F7F9FC"))
        painter.drawEllipse(QRectF(knob_x, 3, 20, 20))


class ToggleSwitch(QWidget):
    """Accessible switch paired with an explicit On/Off state label."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.switch = ToggleButton(checked)
        self.state_label = QLabel()
        self.state_label.setObjectName("toggleState")
        layout.addWidget(self.switch)
        layout.addWidget(self.state_label)
        layout.addStretch(1)

        self.switch.toggled.connect(self._on_toggled)
        self._on_toggled(checked)

    def _on_toggled(self, checked: bool) -> None:
        self.state_label.setText("On" if checked else "Off")
        self.state_label.setProperty("enabled", checked)
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
        self.toggled.emit(checked)

    def is_checked(self) -> bool:
        return self.switch.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.switch.setChecked(checked)


class ConfigurationDialog(QDialog):
    """Pure view: gathers values and delegates saving to its controller."""

    save_requested = Signal()

    MIDI_INPUT_OPTIONS = (
        "Default MIDI Input",
        "USB MIDI Keyboard",
        "Digital Piano",
        "Virtual MIDI Port",
    )
    AUDIO_DRIVER_OPTIONS = (
        "System Default",
        "WASAPI",
        "DirectSound",
        "ALSA",
        "CoreAudio",
    )
    INSTRUMENT_OPTIONS = (
        "Acoustic Grand Piano",
        "Bright Acoustic Piano",
        "Electric Piano",
        "Honky-tonk Piano",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("configurationDialog")
        self.setWindowTitle("Configuration")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setSizeGripEnabled(False)
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(18)

        title = QLabel("Application configuration")
        title.setObjectName("dialogTitle")
        description = QLabel(
            "Choose the MIDI and audio defaults used when Barno starts."
        )
        description.setObjectName("dialogDescription")
        description.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(description)

        form_card = QFrame()
        form_card.setObjectName("formCard")
        form = QGridLayout(form_card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(16)
        form.setColumnStretch(1, 1)

        self.midi_input_combo = self._make_combo(self.MIDI_INPUT_OPTIONS)
        self.audio_driver_combo = self._make_combo(
            self.AUDIO_DRIVER_OPTIONS
        )
        self.instrument_combo = self._make_combo(self.INSTRUMENT_OPTIONS)
        self.show_playback_notes_toggle = ToggleSwitch(True)

        self._add_field(
            form,
            0,
            "MIDI input",
            "Physical or virtual source for live notes",
            self.midi_input_combo,
        )
        self._add_field(
            form,
            1,
            "Audio driver",
            "Backend used by the FluidSynth output",
            self.audio_driver_combo,
        )
        self._add_field(
            form,
            2,
            "Instrument",
            "Default sound selected during startup",
            self.instrument_combo,
        )
        self._add_field(
            form,
            3,
            "Show playback notes",
            "Display falling notes imported from MIDI files",
            self.show_playback_notes_toggle,
        )
        root.addWidget(form_card)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancelButton")
        self.save_button = QPushButton("Save configuration")
        self.save_button.setObjectName("saveButton")
        self.save_button.setDefault(True)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)

        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.save_requested.emit)

    @staticmethod
    def _make_combo(values) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        combo.setMinimumHeight(38)
        return combo

    @staticmethod
    def _add_field(
        layout: QGridLayout,
        row: int,
        title: str,
        description: str,
        editor: QWidget,
    ) -> None:
        label_container = QWidget()
        labels = QVBoxLayout(label_container)
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("fieldTitle")
        description_label = QLabel(description)
        description_label.setObjectName("fieldDescription")
        labels.addWidget(title_label)
        labels.addWidget(description_label)
        layout.addWidget(label_container, row, 0)
        layout.addWidget(editor, row, 1)

    def form_values(self) -> dict[str, object]:
        """Return controller-friendly values using persistent JSON key names."""

        return {
            "midi_input": self.midi_input_combo.currentText(),
            "audio_driver": self.audio_driver_combo.currentText(),
            "instrument": self.instrument_combo.currentText(),
            "show_playback_notes": (
                self.show_playback_notes_toggle.is_checked()
            ),
        }

    def set_configuration(self, configuration) -> None:
        self._select_or_add(
            self.midi_input_combo, configuration.midi_input
        )
        self._select_or_add(
            self.audio_driver_combo, configuration.audio_driver
        )
        self._select_or_add(
            self.instrument_combo, configuration.instrument
        )
        self.show_playback_notes_toggle.set_checked(
            configuration.show_playback_notes
        )

    @staticmethod
    def _select_or_add(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index < 0:
            combo.addItem(value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def show_save_error(self, message: str) -> None:
        QMessageBox.critical(self, "Could not save configuration", message)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QDialog#configurationDialog {
                background-color: #11151D;
                color: #E8EDF7;
            }
            QLabel#dialogTitle {
                color: #F5F7FB;
                font-size: 21px;
                font-weight: 700;
            }
            QLabel#dialogDescription,
            QLabel#fieldDescription {
                color: #8E98AB;
                font-size: 12px;
            }
            QLabel#fieldTitle {
                color: #E8EDF7;
                font-size: 13px;
                font-weight: 600;
            }
            QFrame#formCard {
                background-color: #181E28;
                border: 1px solid #2C3545;
                border-radius: 10px;
            }
            QComboBox {
                color: #F2F5FA;
                background-color: #222A37;
                border: 1px solid #3A465A;
                border-radius: 6px;
                padding: 7px 10px;
            }
            QComboBox:hover, QComboBox:focus {
                border-color: #57C7FF;
            }
            QComboBox::drop-down {
                border: none;
                width: 28px;
            }
            QComboBox QAbstractItemView {
                color: #F2F5FA;
                background-color: #222A37;
                border: 1px solid #3A465A;
                selection-background-color: #31516B;
                outline: none;
            }
            QLabel#toggleState {
                color: #9AA4B7;
                font-weight: 600;
            }
            QLabel#toggleState[enabled="true"] {
                color: #55D99B;
            }
            QPushButton {
                min-height: 34px;
                border-radius: 6px;
                padding: 2px 15px;
                font-weight: 600;
            }
            QPushButton#cancelButton {
                color: #D5DBE6;
                background-color: #252C38;
                border: 1px solid #3A4557;
            }
            QPushButton#cancelButton:hover {
                background-color: #303947;
            }
            QPushButton#saveButton {
                color: #0C1820;
                background-color: #57C7FF;
                border: 1px solid #57C7FF;
            }
            QPushButton#saveButton:hover {
                background-color: #78D2FF;
            }
            """
        )