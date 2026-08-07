"""Main application window with live input and MIDI-file transport controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.view.piano_layout import PianoLayoutWidget


class MainWindow(QMainWindow):
    SEEK_SLIDER_STEPS = 10_000

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.timeline = None
        self._resume_after_seek = False

        self.setWindowTitle("Barno")
        self.resize(1120, 610)
        self._build_ui()
        self._connect_controller()
        self._install_shortcuts()
        self._load_default_midi_if_present()

    def _build_ui(self):
        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)

        # Existing live MIDI engine control plus MIDI-file importing.
        top_controls = QHBoxLayout()
        self.load_button = QPushButton("Load MIDI Engine")
        self.load_button.clicked.connect(self.controller.start_midi_engine)
        self.import_button = QPushButton("Import MIDI")
        self.import_button.clicked.connect(self.choose_midi_file)
        self.file_label = QLabel("No MIDI file loaded")
        top_controls.addWidget(self.load_button)
        top_controls.addWidget(self.import_button)
        top_controls.addWidget(self.file_label, 1)
        self.main_layout.addLayout(top_controls)

        # Retain the existing horizontally scrollable 88-key piano.
        self.scroll = QScrollArea()
        self.piano_widget = PianoLayoutWidget()
        self.scroll.setWidget(self.piano_widget)
        self.scroll.setWidgetResizable(False)
        self.scroll.setFixedHeight(420)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.main_layout.addWidget(self.scroll)

        # Accurate song-time seeking. Slider drag pauses and resumes atomically.
        seek_row = QHBoxLayout()
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, self.SEEK_SLIDER_STEPS)
        self.seek_slider.setEnabled(False)
        self.position_label = QLabel("00:00.000 / 00:00.000")
        self.position_label.setMinimumWidth(165)
        seek_row.addWidget(self.seek_slider, 1)
        seek_row.addWidget(self.position_label)
        self.main_layout.addLayout(seek_row)

        transport = QHBoxLayout()
        self.back_button = QPushButton("-5 s")
        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.forward_button = QPushButton("+5 s")
        for button in (
            self.back_button,
            self.play_button,
            self.stop_button,
            self.forward_button,
        ):
            button.setEnabled(False)

        self.speed_label = QLabel("Tempo: 100%")
        self.speed_label.setMinimumWidth(95)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(25, 200)
        self.speed_slider.setValue(100)
        self.speed_slider.setTickInterval(25)
        self.speed_slider.setMaximumWidth(240)

        transport.addStretch(1)
        transport.addWidget(self.back_button)
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addWidget(self.forward_button)
        transport.addStretch(1)
        transport.addWidget(self.speed_label)
        transport.addWidget(self.speed_slider)
        self.main_layout.addLayout(transport)

        self.play_button.clicked.connect(
            self.controller.toggle_file_playback
        )
        self.stop_button.clicked.connect(
            self.controller.stop_file_playback
        )
        self.back_button.clicked.connect(lambda: self.jump_by(-5.0))
        self.forward_button.clicked.connect(lambda: self.jump_by(5.0))
        self.speed_slider.valueChanged.connect(self.change_speed)
        self.seek_slider.sliderPressed.connect(self.begin_slider_seek)
        self.seek_slider.sliderMoved.connect(self.preview_slider_seek)
        self.seek_slider.sliderReleased.connect(self.finish_slider_seek)

        self.setCentralWidget(self.central_widget)
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #11131A; color: #E7EAF0; }
            QPushButton {
                background: #2A3040; border: 1px solid #47506A;
                border-radius: 5px; padding: 7px 13px;
            }
            QPushButton:hover { background: #394158; }
            QPushButton:disabled { color: #72798A; background: #1C1F29; }
            QSlider::groove:horizontal {
                height: 5px; background: #343A4C;
            }
            QSlider::handle:horizontal {
                width: 15px; margin: -5px 0;
                border-radius: 7px; background: #57C7FF;
            }
            QScrollArea { border: 1px solid #343A4C; }
            """
        )

    def _connect_controller(self):
        self.controller.timeline_loaded.connect(self.on_timeline_loaded)
        self.controller.playback_position_changed.connect(
            self.on_position_changed
        )
        self.controller.playback_state_changed.connect(
            self.on_playback_changed
        )
        self.controller.playback_note_on.connect(self.on_playback_note_on)
        self.controller.playback_note_off.connect(self.on_playback_note_off)
        self.controller.playback_notes_reset.connect(
            self.reset_playback_highlights
        )
        self.controller.playback_error.connect(self.show_error)

    def _install_shortcuts(self):
        open_action = QAction("Import MIDI", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.choose_midi_file)
        self.addAction(open_action)

        play_action = QAction("Play / Pause", self)
        play_action.setShortcut(Qt.Key.Key_Space)
        play_action.triggered.connect(
            self.controller.toggle_file_playback
        )
        self.addAction(play_action)

    def _load_default_midi_if_present(self):
        # main_window.py normally lives at src/view/main_window.py.
        project_root = Path(__file__).resolve().parents[2]
        for filename in ("sample.midi", "sample.mid"):
            candidate = project_root / "resource" / filename
            if candidate.exists():
                self.controller.load_midi_file(candidate)
                return

    @Slot()
    def choose_midi_file(self):
        project_root = Path(__file__).resolve().parents[2]
        start_directory = project_root / "resource"
        if not start_directory.exists():
            start_directory = Path.home()
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import MIDI file",
            str(start_directory),
            "MIDI files (*.mid *.midi);;All files (*)",
        )
        if filename:
            self.controller.load_midi_file(filename)

    @Slot(object)
    def on_timeline_loaded(self, timeline):
        self.timeline = timeline
        self.file_label.setText(
            f"{timeline.path.name} & {len(timeline.note_spans)} notes"
        )
        self.setWindowTitle(f"Barno & {timeline.path.name}")
        self.piano_widget.set_playback_timeline(timeline.note_spans)
        self.seek_slider.setEnabled(timeline.duration_seconds > 0)
        for button in (
            self.back_button,
            self.play_button,
            self.stop_button,
            self.forward_button,
        ):
            button.setEnabled(True)
        self.on_position_changed(0.0)
        self.update_note_display(f"Loaded {timeline.path.name}")

    @Slot(bool)
    def on_playback_changed(self, playing):
        self.play_button.setText("Pause" if playing else "Play")

    @Slot(float)
    def on_position_changed(self, seconds):
        duration = self.timeline.duration_seconds if self.timeline else 0.0
        self.position_label.setText(
            f"{self.format_time(seconds)} / {self.format_time(duration)}"
        )
        self.piano_widget.set_playback_position(seconds)

        if duration > 0 and not self.seek_slider.isSliderDown():
            slider_value = round(
                seconds / duration * self.SEEK_SLIDER_STEPS
            )
            self.seek_slider.setValue(slider_value)

    @Slot(int)
    def on_playback_note_on(self, note):
        self.piano_widget.handle_note_on(note, source="playback")

    @Slot(int)
    def on_playback_note_off(self, note):
        self.piano_widget.handle_note_off(note, source="playback")

    @Slot()
    def reset_playback_highlights(self):
        self.piano_widget.release_source("playback")

    @Slot(int)
    def change_speed(self, percentage):
        speed = percentage / 100.0
        self.speed_label.setText(f"Tempo: {percentage}%")
        self.controller.set_file_speed(speed)
        self.piano_widget.set_playback_speed(speed)

    @staticmethod
    def format_time(seconds):
        milliseconds = max(0, round(seconds * 1000))
        minutes, remainder = divmod(milliseconds, 60_000)
        whole_seconds, millis = divmod(remainder, 1000)
        return f"{minutes:02d}:{whole_seconds:02d}.{millis:03d}"

    def slider_seconds(self, value):
        if not self.timeline:
            return 0.0
        return (
            value
            / self.SEEK_SLIDER_STEPS
            * self.timeline.duration_seconds
        )

    @Slot()
    def begin_slider_seek(self):
        self._resume_after_seek = self.controller.file_is_playing()
        if self._resume_after_seek:
            self.controller.pause_file_playback()

    @Slot(int)
    def preview_slider_seek(self, value):
        seconds = self.slider_seconds(value)
        duration = self.timeline.duration_seconds if self.timeline else 0.0
        self.position_label.setText(
            f"{self.format_time(seconds)} / {self.format_time(duration)}"
        )
        self.piano_widget.set_playback_position(seconds)

    @Slot()
    def finish_slider_seek(self):
        self.controller.seek_file(
            self.slider_seconds(self.seek_slider.value())
        )
        if self._resume_after_seek:
            self.controller.toggle_file_playback()
        self._resume_after_seek = False

    def jump_by(self, delta_seconds):
        if self.timeline:
            self.controller.seek_file(
                self.controller.current_file_position() + delta_seconds
            )

    # Existing view API used by the physical MIDI input controller.
    def update_note_display(self, text):
        self.statusBar().showMessage(text)

    def set_loading_state(self, is_loading):
        self.load_button.setEnabled(not is_loading)
        self.load_button.setText(
            "MIDI Engine Running" if is_loading else "Load MIDI Engine"
        )

    @Slot(str)
    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)