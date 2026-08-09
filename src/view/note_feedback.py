"""Performant particle and hold animations for real-time piano feedback."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


@dataclass(slots=True)
class _Particle:
    x: float
    y: float
    vx: float
    vy: float
    age: float
    lifetime: float
    size: float
    color: QColor


@dataclass(slots=True)
class _Pulse:
    x: float
    y: float
    age: float
    lifetime: float
    color: QColor
    label: str


@dataclass(slots=True)
class _HeldNote:
    x: float
    y: float
    width: float
    grade: str
    count: int = 1
    phase: float = 0.0
    spawn_elapsed: float = 0.0


class NoteFeedbackOverlay(QWidget):
    """One shared animation surface for all 88 notes.

    A single 30 FPS timer is active only while a key is held or particles remain.
    Particle count is capped, making render cost predictable even for dense
    chords and fast passages.
    """

    MAX_PARTICLES = 180
    MAX_PULSES = 48
    FRAME_INTERVAL_MS = 33
    HOLD_PARTICLE_INTERVAL = 0.14
    COLORS = {
        "live": QColor("#2ECC71"),
        "perfect": QColor("#57E6FF"),
        "great": QColor("#55D99B"),
        "good": QColor("#FFD166"),
        "close": QColor("#FF9F5A"),
        "wrong": QColor("#FF647C"),
        "held": QColor("#57E6FF"),
        "early_release": QColor("#FFB454"),
        "late_release": QColor("#D18CFF"),
    }

    def __init__(
        self,
        key_geometry: dict[int, tuple[float, float]],
        strike_y: float,
        parent=None,
    ):
        super().__init__(parent)
        self._key_geometry = key_geometry
        self._strike_y = strike_y
        self._particles: list[_Particle] = []
        self._pulses: list[_Pulse] = []
        self._held_notes: dict[int, _HeldNote] = {}
        self._random = random.Random()
        self._last_tick = time.perf_counter()
        self._label_font = QFont("Sans Serif", 9, QFont.Weight.DemiBold)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self.FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._advance)

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")

    def begin_note(
        self,
        note: int,
        grade: str = "live",
        label: str = "",
    ) -> None:
        geometry = self._key_geometry.get(note)
        if geometry is None:
            return
        center_x, key_width = geometry
        color = self._color(grade)
        held = self._held_notes.get(note)
        if held is None:
            self._held_notes[note] = _HeldNote(
                x=center_x,
                y=self._strike_y,
                width=max(8.0, min(key_width, 18.0)),
                grade=grade,
            )
        else:
            held.count += 1
            held.grade = grade

        self._spawn_burst(center_x, self._strike_y, color, 9)
        self._add_pulse(
            _Pulse(center_x, self._strike_y, 0.0, 0.72, color, label)
        )
        self._start_timer()

    def update_note_grade(
        self,
        note: int,
        grade: str,
        label: str = "",
    ) -> None:
        """Replace generic live feedback with the timing judgment."""

        held = self._held_notes.get(note)
        geometry = self._key_geometry.get(note)
        if geometry is None:
            return
        if held is not None:
            held.grade = grade
        center_x, _ = geometry
        color = self._color(grade)
        self._add_pulse(
            _Pulse(center_x, self._strike_y, 0.0, 0.82, color, label)
        )
        self._spawn_burst(center_x, self._strike_y, color, 5)
        self._start_timer()

    def end_note(
        self,
        note: int,
        grade: str = "held",
        label: str = "",
    ) -> None:
        geometry = self._key_geometry.get(note)
        if geometry is None:
            return
        held = self._held_notes.get(note)
        if held is not None and held.count > 1:
            held.count -= 1
        else:
            self._held_notes.pop(note, None)

        center_x, _ = geometry
        color = self._color(grade)
        self._spawn_burst(center_x, self._strike_y, color, 7)
        if label:
            self._add_pulse(
                _Pulse(center_x, self._strike_y, 0.0, 0.9, color, label)
            )
        self._start_timer()

    def clear(self) -> None:
        self._held_notes.clear()
        self._particles.clear()
        self._pulses.clear()
        self._timer.stop()
        self.update()

    def _start_timer(self) -> None:
        if not self._timer.isActive():
            self._last_tick = time.perf_counter()
            self._timer.start()
        self.update()

    def _advance(self) -> None:
        now = time.perf_counter()
        delta = min(max(now - self._last_tick, 0.0), 0.06)
        self._last_tick = now

        live_particles: list[_Particle] = []
        for particle in self._particles:
            particle.age += delta
            if particle.age >= particle.lifetime:
                continue
            particle.x += particle.vx * delta
            particle.y += particle.vy * delta
            particle.vy += 28.0 * delta
            live_particles.append(particle)
        self._particles = live_particles

        for pulse in self._pulses:
            pulse.age += delta
        self._pulses = [
            pulse for pulse in self._pulses if pulse.age < pulse.lifetime
        ]

        for held in self._held_notes.values():
            held.phase += delta * 4.0
            held.spawn_elapsed += delta
            if held.spawn_elapsed >= self.HOLD_PARTICLE_INTERVAL:
                held.spawn_elapsed = 0.0
                self._spawn_hold_particle(held)

        if not self._particles and not self._pulses and not self._held_notes:
            self._timer.stop()
        self.update()

    def _spawn_burst(
        self,
        x: float,
        y: float,
        color: QColor,
        count: int,
    ) -> None:
        available = max(0, self.MAX_PARTICLES - len(self._particles))
        for _ in range(min(count, available)):
            angle = self._random.uniform(math.pi * 1.05, math.pi * 1.95)
            speed = self._random.uniform(34.0, 88.0)
            self._particles.append(
                _Particle(
                    x=x + self._random.uniform(-4.0, 4.0),
                    y=y + self._random.uniform(-2.0, 3.0),
                    vx=math.cos(angle) * speed,
                    vy=math.sin(angle) * speed,
                    age=0.0,
                    lifetime=self._random.uniform(0.55, 1.0),
                    size=self._random.uniform(2.2, 5.2),
                    color=QColor(color),
                )
            )

    def _add_pulse(self, pulse: _Pulse) -> None:
        if len(self._pulses) >= self.MAX_PULSES:
            self._pulses.pop(0)
        self._pulses.append(pulse)

    def _spawn_hold_particle(self, held: _HeldNote) -> None:
        if len(self._particles) >= self.MAX_PARTICLES:
            return
        self._particles.append(
            _Particle(
                x=held.x + self._random.uniform(-held.width / 3, held.width / 3),
                y=held.y - self._random.uniform(2.0, 12.0),
                vx=self._random.uniform(-8.0, 8.0),
                vy=self._random.uniform(-36.0, -20.0),
                age=0.0,
                lifetime=self._random.uniform(0.55, 0.85),
                size=self._random.uniform(2.0, 3.8),
                color=QColor(self._color(held.grade)),
            )
        )

    def paintEvent(self, event):  # noqa: N802 - Qt API name
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        for held in self._held_notes.values():
            color = QColor(self._color(held.grade))
            glow = 0.72 + math.sin(held.phase) * 0.12
            color.setAlphaF(max(0.0, min(glow, 1.0)))
            beam_height = 24.0 + math.sin(held.phase * 0.7) * 5.0
            painter.setBrush(color)
            painter.drawRoundedRect(
                QRectF(
                    held.x - held.width / 2,
                    held.y - beam_height,
                    held.width,
                    beam_height + 5,
                ),
                held.width / 2,
                held.width / 2,
            )

        for particle in self._particles:
            progress = particle.age / particle.lifetime
            color = QColor(particle.color)
            color.setAlphaF(max(0.0, (1.0 - progress) * 0.9))
            painter.setBrush(color)
            size = particle.size * (1.0 - progress * 0.35)
            painter.drawEllipse(
                QPointF(particle.x, particle.y), size, size
            )

        for pulse in self._pulses:
            progress = pulse.age / pulse.lifetime
            color = QColor(pulse.color)
            color.setAlphaF(max(0.0, 1.0 - progress))
            radius = 7.0 + progress * 22.0
            painter.setPen(QPen(color, max(1.0, 2.6 * (1.0 - progress))))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(pulse.x, pulse.y), radius, radius * 0.52)

            if pulse.label and progress < 0.82:
                label_color = QColor(pulse.color)
                label_color.setAlphaF(max(0.0, 1.0 - progress / 0.82))
                painter.setPen(label_color)
                painter.setFont(self._label_font)
                painter.drawText(
                    QRectF(
                        pulse.x - 45,
                        pulse.y - 34 - progress * 18,
                        90,
                        20,
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    pulse.label,
                )

    @classmethod
    def _color(cls, grade: str) -> QColor:
        return cls.COLORS.get(grade, cls.COLORS["live"])