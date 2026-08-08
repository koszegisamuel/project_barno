"""Existing 88-key piano enhanced with synchronized falling MIDI notes."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QWidget

from src.util.constants import PIANO_SOURCE_LIVE, PIANO_SOURCE_PLAYBACK


class PianoKey(QFrame):
    def __init__(self, midi_note, is_black, parent=None):
        super().__init__(parent)
        self.midi_note = midi_note
        self.is_black = is_black
        self.default_color = "#333" if is_black else "white"
        self.highlight_color_live = "#2ecc71"
        self.highlight_color_playback = "#4da8da"

        self.set_style(self.default_color)

        # Add a border to see white keys clearly.
        if not is_black:
            self.setFrameStyle(QFrame.Panel | QFrame.Plain)
            self.setLineWidth(1)

    def set_style(self, color):
        border = "1px solid #888" if not self.is_black else "none"
        self.setStyleSheet(
            f"background-color: {color}; border: {border}; "
            "border-radius: 2px;"
        )

    def press(self, source: str):

        if source == PIANO_SOURCE_LIVE:
            self.set_style(self.highlight_color_live)
        elif source == PIANO_SOURCE_PLAYBACK:
            self.set_style(self.highlight_color_playback)
        else:
            self.set_style(self.highlight_color_live)
    def release(self):
        self.set_style(self.default_color)


class FallingNotesOverlay(QWidget):
    """Transparent piano-roll renderer aligned to the existing key geometry."""

    CHANNEL_COLORS = (
        QColor("#57C7FF"), QColor("#FF6B9D"), QColor("#FFD166"),
        QColor("#70E1A1"), QColor("#B892FF"), QColor("#FF8C5A"),
        QColor("#5DE2E7"), QColor("#F38BA8"), QColor("#A6E3A1"),
        QColor("#FAB387"), QColor("#89B4FA"), QColor("#CBA6F7"),
        QColor("#F9E2AF"), QColor("#94E2D5"), QColor("#74C7EC"),
        QColor("#F5C2E7"),
    )

    def __init__(self, key_geometry: dict[int, tuple[float, float]], parent=None):
        super().__init__(parent)
        self._key_geometry = key_geometry
        self._note_spans: tuple = ()
        self._position = 0.0
        self._speed = 1.0
        self._look_ahead_wall_seconds = 4.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")

    def set_note_spans(self, note_spans: Iterable) -> None:
        self._note_spans = tuple(note_spans)
        self._position = 0.0
        self.update()

    @Slot(float)
    def set_position(self, seconds: float) -> None:
        self._position = max(0.0, seconds)
        self.update()

    def set_speed(self, speed: float) -> None:
        self._speed = min(max(speed, 0.25), 2.0)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Keep the existing white-key lane guides visible behind falling notes.
        painter.setPen(QPen(QColor("#252A35"), 1.0))
        seen_lines = set()
        for center, width in self._key_geometry.values():
            left = round(center - width / 2.0)
            if left not in seen_lines:
                painter.drawLine(
                    QPointF(left, 0), QPointF(left, self.height())
                )
                seen_lines.add(left)

        look_ahead = self._look_ahead_wall_seconds * self._speed
        visible_end = self._position + look_ahead
        strike_y = float(self.height() - 2)

        for span in self._note_spans:
            if span.end_seconds < self._position:
                continue
            # MidiTimeline keeps spans ordered by start time, so this is safe.
            if span.start_seconds > visible_end:
                break
            if span.note not in self._key_geometry:
                continue

            center, key_width = self._key_geometry[span.note]
            bar_width = max(7.0, min(key_width - 3.0, 14.0))
            bottom_y = strike_y - (
                (span.start_seconds - self._position) / look_ahead
            ) * self.height()
            top_y = strike_y - (
                (span.end_seconds - self._position) / look_ahead
            ) * self.height()
            rectangle = QRectF(
                center - bar_width / 2.0,
                top_y,
                bar_width,
                max(3.0, bottom_y - top_y),
            )
            color = self.CHANNEL_COLORS[
                span.channel % len(self.CHANNEL_COLORS)
            ]
            painter.setPen(QPen(color.lighter(145), 1.0))
            painter.setBrush(color)
            painter.drawRoundedRect(rectangle, 2.0, 2.0)

        # Every note-on is scheduled exactly when its leading edge reaches here.
        painter.setPen(QPen(QColor("#F5F7FA"), 2.0))
        painter.drawLine(
            QPointF(0, strike_y), QPointF(self.width(), strike_y)
        )


class PianoLayoutWidget(QWidget):
    """The original piano layout with live/file-safe key highlighting."""

    def __init__(self):
        super().__init__()
        self.keys = {}
        self.white_keys = []

        # Track live-input and file-playback presses independently. This avoids
        # a file note-off unlighting a key still held on the physical keyboard.
        self._active_sources: dict[int, dict[str, int]] = defaultdict(dict)

        # Standard 88-key piano: A0 (21) to C8 (108).
        self.start_note = 21
        self.end_note = 108

        self.init_ui()

    def init_ui(self):
        w_width, w_height = 20, 120
        b_width, b_height = 12, 75

        # Falling-note lanes remain the upper part of the original layout.
        self.lane_container = QWidget(self)
        self.lane_container.setStyleSheet(
            "background-color: #1a1a1a; border-bottom: 2px solid #555;"
        )
        self.keyboard_container = QWidget(self)

        current_x = 0
        black_keys_to_add = []

        for note in range(self.start_note, self.end_note + 1):
            note_in_octave = note % 12
            is_black = note_in_octave in [1, 3, 6, 8, 10]

            if not is_black:
                key = PianoKey(note, False, self.keyboard_container)
                key.setGeometry(current_x, 0, w_width, w_height)
                self.keys[note] = key
                self.white_keys.append(key)
                current_x += w_width
            else:
                black_keys_to_add.append((note, current_x - b_width // 2))

        # Add black keys last so they stay visually above white keys.
        for note, x_pos in black_keys_to_add:
            key = PianoKey(note, True, self.keyboard_container)
            key.setGeometry(x_pos, 0, b_width, b_height)
            key.raise_()
            self.keys[note] = key

        self.setFixedSize(current_x, 400)
        self.lane_container.setGeometry(0, 0, current_x, 280)
        self.keyboard_container.setGeometry(0, 280, current_x, w_height)

        # Map each MIDI note to its actual on-screen key center and width. Bars
        # therefore align with the existing physically proportioned keyboard.
        key_geometry = {
            note: (key.geometry().center().x(), key.width())
            for note, key in self.keys.items()
        }
        self.note_overlay = FallingNotesOverlay(
            key_geometry, self.lane_container
        )
        self.note_overlay.setGeometry(0, 0, current_x, 280)
        self.note_overlay.raise_()

    @Slot(int)
    def handle_note_on(self, note, source=PIANO_SOURCE_LIVE):
        """Highlight a key while retaining independent source reference counts."""

        if note not in self.keys:
            return
        counts = self._active_sources[note]
        counts[source] = counts.get(source, 0) + 1
        self.keys[note].press(source)

    @Slot(int)
    def handle_note_off(self, note, source=PIANO_SOURCE_LIVE):
        if note not in self.keys:
            return
        counts = self._active_sources[note]
        if source in counts:
            if counts[source] <= 1:
                counts.pop(source)
            else:
                counts[source] -= 1
        if counts:
            self.keys[note].press(source)
        else:
            self._active_sources.pop(note, None)
            self.keys[note].release()

    def release_source(self, source: str) -> None:
        """Release only one origin, leaving other held-note sources intact."""

        for note in tuple(self._active_sources):
            counts = self._active_sources[note]
            counts.pop(source, None)
            if counts:
                self.keys[note].press(source)
            else:
                self._active_sources.pop(note, None)
                self.keys[note].release()

    def set_playback_timeline(self, note_spans: Iterable) -> None:
        self.note_overlay.set_note_spans(note_spans)

    @Slot(float)
    def set_playback_position(self, seconds: float) -> None:
        self.note_overlay.set_position(seconds)

    def set_playback_speed(self, speed: float) -> None:
        self.note_overlay.set_speed(speed)