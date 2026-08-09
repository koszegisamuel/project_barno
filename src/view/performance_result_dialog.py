"""Polished end-of-song performance summary dialog.

The dialog deliberately depends only on the public attributes of a
``PerformanceReport``.  This keeps the view independent from the tracker and
controller modules and makes it straightforward to reuse or preview.
"""

from __future__ import annotations

import math
from typing import Callable, Protocol

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class PerformanceReportLike(Protocol):
    """Structural type expected by :class:`PerformanceResultDialog`."""

    total_notes: int
    hit_notes: int
    missed_notes: int
    extra_notes: int
    hit_ratio: float
    onset_precision: float
    hold_accuracy: float
    overall_accuracy: float
    perfect_notes: int
    great_notes: int
    good_notes: int
    close_notes: int


def _clamp_percent(value: float) -> float:
    """Return a display-safe percentage without mutating the source report."""

    return min(100.0, max(0.0, float(value)))


class StarRatingWidget(QWidget):
    """Five-star display with smooth partial-star filling.

    Painting all stars in one lightweight widget avoids creating animated
    child widgets or image assets.  A score of 86 therefore renders as 4.3
    stars rather than losing useful detail through integer rounding.
    """

    STAR_COUNT = 5

    def __init__(self, score: float, parent: QWidget | None = None):
        super().__init__(parent)
        self._score = _clamp_percent(score)
        self.setMinimumSize(270, 54)
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.setAccessibleName(
            f"Performance rating {self.rating:.1f} out of 5 stars"
        )

    @property
    def rating(self) -> float:
        return self._score / 20.0

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API naming convention
        return QSize(290, 58)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API convention
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        star_size = min(46.0, float(self.height() - 8))
        gap = 8.0
        total_width = self.STAR_COUNT * star_size + (self.STAR_COUNT - 1) * gap
        left = (self.width() - total_width) / 2.0
        top = (self.height() - star_size) / 2.0

        empty_fill = QColor("#30394B")
        outline = QPen(QColor("#657087"), 1.4)
        gold = QColor("#FFD166")

        for index in range(self.STAR_COUNT):
            x = left + index * (star_size + gap)
            path = self._star_path(x, top, star_size)

            painter.setPen(outline)
            painter.setBrush(empty_fill)
            painter.drawPath(path)

            fill_fraction = min(1.0, max(0.0, self.rating - index))
            if fill_fraction > 0.0:
                painter.save()
                painter.setClipRect(
                    QRectF(x, top, star_size * fill_fraction, star_size)
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(gold)
                painter.drawPath(path)
                painter.restore()

            # Redraw the border over the clipped fill for a crisp edge.
            painter.setPen(outline)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    @staticmethod
    def _star_path(left: float, top: float, size: float) -> QPainterPath:
        center_x = left + size / 2.0
        center_y = top + size / 2.0
        outer_radius = size * 0.48
        inner_radius = outer_radius * 0.46
        points = []
        for index in range(10):
            angle = math.radians(-90.0 + index * 36.0)
            radius = outer_radius if index % 2 == 0 else inner_radius
            points.append(
                (
                    center_x + math.cos(angle) * radius,
                    center_y + math.sin(angle) * radius,
                )
            )

        polygon = QPolygonF()
        for x, y in points:
            polygon.append(QRectF(x, y, 0.0, 0.0).topLeft())
        path = QPainterPath()
        path.addPolygon(polygon)
        path.closeSubpath()
        return path


class MetricCard(QFrame):
    """One labelled percentage with a compact explanation and progress bar."""

    def __init__(
        self,
        title: str,
        value: float,
        detail: str,
        accent: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("metricCard")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        value = _clamp_percent(value)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        heading_row = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        value_label = QLabel(f"{value:.1f}%")
        value_label.setObjectName("metricValue")
        value_label.setStyleSheet(f"color: {accent};")
        heading_row.addWidget(title_label)
        heading_row.addStretch(1)
        heading_row.addWidget(value_label)
        layout.addLayout(heading_row)

        detail_label = QLabel(detail)
        detail_label.setObjectName("metricDetail")
        detail_label.setWordWrap(True)
        layout.addWidget(detail_label)

        progress = QProgressBar()
        progress.setObjectName("metricProgress")
        progress.setRange(0, 1000)
        progress.setValue(round(value * 10))
        progress.setTextVisible(False)
        progress.setFixedHeight(7)
        progress.setStyleSheet(
            "QProgressBar::chunk {"
            f" background-color: {accent};"
            " border-radius: 3px;"
            "}"
        )
        layout.addWidget(progress)


class GradeRow(QWidget):
    """A readable distribution row for one timing grade."""

    def __init__(
        self,
        title: str,
        count: int,
        maximum: int,
        color: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)

        marker = QFrame()
        marker.setFixedSize(9, 9)
        marker.setStyleSheet(
            f"background-color: {color}; border-radius: 4px;"
        )
        title_label = QLabel(title)
        title_label.setObjectName("gradeName")
        title_label.setMinimumWidth(58)

        progress = QProgressBar()
        progress.setObjectName("gradeProgress")
        progress.setRange(0, max(1, maximum))
        progress.setValue(max(0, count))
        progress.setTextVisible(False)
        progress.setFixedHeight(7)
        progress.setStyleSheet(
            "QProgressBar::chunk {"
            f" background-color: {color};"
            " border-radius: 3px;"
            "}"
        )

        count_label = QLabel(str(count))
        count_label.setObjectName("gradeCount")
        count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        count_label.setMinimumWidth(34)

        layout.addWidget(marker)
        layout.addWidget(title_label)
        layout.addWidget(progress, 1)
        layout.addWidget(count_label)


class PerformanceResultDialog(QDialog):
    """Modal, end-of-song result screen for a ``PerformanceReport``.

    Connect :attr:`practice_again_requested` if the caller wants the secondary
    action to restart playback.  The dialog itself intentionally knows nothing
    about the MIDI controller or playback worker.
    """

    practice_again_requested = Signal()

    def __init__(
        self,
        report: PerformanceReportLike,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.report = report
        self.setObjectName("performanceResultDialog")
        self.setWindowTitle("Performance summary")
        self.setModal(True)
        self.setMinimumSize(650, 600)
        self.resize(760, 720)
        self._build_ui()

    @classmethod
    def show_report(
        cls,
        report: PerformanceReportLike,
        parent: QWidget | None = None,
        practice_again_callback: Callable[[], None] | None = None,
    ) -> int:
        """Construct, optionally wire, and execute the dialog modally."""

        dialog = cls(report, parent)
        if practice_again_callback is not None:
            dialog.practice_again_requested.connect(practice_again_callback)
        return dialog.exec()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("resultScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget()
        content.setObjectName("resultContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)

        layout.addWidget(self._build_hero())
        layout.addLayout(self._build_metrics())
        layout.addWidget(self._build_note_summary())
        layout.addWidget(self._build_grade_distribution())
        layout.addWidget(self._build_coaching_tip())
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._build_actions())

        self.setStyleSheet(self._style_sheet())

    def _build_hero(self) -> QFrame:
        score = _clamp_percent(self.report.overall_accuracy)
        hero = QFrame()
        hero.setObjectName("heroCard")
        layout = QVBoxLayout(hero)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        eyebrow = QLabel("SESSION COMPLETE")
        eyebrow.setObjectName("eyebrow")
        eyebrow.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(self._headline(score))
        title.setObjectName("resultTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        score_label = QLabel(f"{score:.1f}%")
        score_label.setObjectName("overallScore")
        score_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stars = StarRatingWidget(score)
        rating_label = QLabel(f"{stars.rating:.1f} / 5 stars")
        rating_label.setObjectName("ratingText")
        rating_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(score_label)
        layout.addWidget(stars, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(rating_label)
        return hero

    def _build_metrics(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        cards = (
            MetricCard(
                "Overall accuracy",
                self.report.overall_accuracy,
                "Combined timing, recognition and hold quality",
                "#57C7FF",
            ),
            MetricCard(
                "Hit rate",
                self.report.hit_ratio,
                f"{self.report.hit_notes} of {self.report.total_notes} song notes",
                "#67E8A5",
            ),
            MetricCard(
                "Onset precision",
                self.report.onset_precision,
                "How closely your attacks matched the song",
                "#A78BFA",
            ),
            MetricCard(
                "Hold accuracy",
                self.report.hold_accuracy,
                "How accurately long notes were sustained",
                "#FFD166",
            ),
        )
        for index, card in enumerate(cards):
            grid.addWidget(card, index // 2, index % 2)
        return grid

    def _build_note_summary(self) -> QFrame:
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 16)
        layout.setSpacing(11)

        heading = QLabel("Note summary")
        heading.setObjectName("sectionHeading")
        layout.addWidget(heading)

        counts = QHBoxLayout()
        counts.setSpacing(8)
        entries = (
            ("HIT", self.report.hit_notes, "#67E8A5"),
            ("MISSED", self.report.missed_notes, "#FF7A90"),
            ("EXTRA", self.report.extra_notes, "#FFB86C"),
            ("TOTAL", self.report.total_notes, "#57C7FF"),
        )
        for label, value, color in entries:
            item = QFrame()
            item.setObjectName("countItem")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(8, 10, 8, 10)
            item_layout.setSpacing(2)
            number = QLabel(str(value))
            number.setObjectName("countValue")
            number.setStyleSheet(f"color: {color};")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption = QLabel(label)
            caption.setObjectName("countCaption")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item_layout.addWidget(number)
            item_layout.addWidget(caption)
            counts.addWidget(item, 1)
        layout.addLayout(counts)
        return card

    def _build_grade_distribution(self) -> QFrame:
        card = QFrame()
        card.setObjectName("sectionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(4)

        heading = QLabel("Timing grades")
        heading.setObjectName("sectionHeading")
        layout.addWidget(heading)

        subtitle = QLabel("Matched notes grouped by attack precision")
        subtitle.setObjectName("sectionSubtitle")
        layout.addWidget(subtitle)

        maximum = max(1, self.report.hit_notes)
        grades = (
            ("Perfect", self.report.perfect_notes, "#67E8A5"),
            ("Great", self.report.great_notes, "#57C7FF"),
            ("Good", self.report.good_notes, "#FFD166"),
            ("Close", self.report.close_notes, "#FFB86C"),
        )
        for title, count, color in grades:
            layout.addWidget(GradeRow(title, count, maximum, color))
        return card

    def _build_coaching_tip(self) -> QFrame:
        tip = QFrame()
        tip.setObjectName("tipCard")
        layout = QHBoxLayout(tip)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(12)

        icon = QLabel("TIP")
        icon.setObjectName("tipBadge")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(42, 28)

        text = QLabel(self._coaching_message())
        text.setObjectName("tipText")
        text.setWordWrap(True)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(text, 1)
        return tip

    def _build_actions(self) -> QFrame:
        actions = QFrame()
        actions.setObjectName("actionBar")
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(28, 14, 28, 14)
        layout.setSpacing(10)
        layout.addStretch(1)

        close_button = QPushButton("Close")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)

        retry_button = QPushButton("Practice again")
        retry_button.setObjectName("primaryButton")
        retry_button.setDefault(True)
        retry_button.clicked.connect(self._request_practice_again)

        layout.addWidget(close_button)
        layout.addWidget(retry_button)
        return actions

    def _request_practice_again(self) -> None:
        self.accept()
        self.practice_again_requested.emit()

    @staticmethod
    def _headline(score: float) -> str:
        if score >= 95.0:
            return "Outstanding performance"
        if score >= 85.0:
            return "Excellent work"
        if score >= 70.0:
            return "Strong performance"
        if score >= 55.0:
            return "Good progress"
        return "Keep practicing"

    def _coaching_message(self) -> str:
        if self.report.total_notes == 0:
            return "There were no scoreable notes in this playback range."
        if self.report.hit_ratio < 70.0 or self.report.missed_notes > self.report.hit_notes:
            return (
                "Focus first on note recognition and play a little slower. "
                "Once the notes feel secure, bring the tempo back up gradually."
            )
        if self.report.onset_precision + 8.0 < self.report.hold_accuracy:
            return (
                "Your note lengths are controlled well. Next, focus on landing "
                "each attack closer to the visual hit line."
            )
        if self.report.hold_accuracy + 8.0 < self.report.onset_precision:
            return (
                "Your attacks are precise. Give long notes their full value and "
                "release them together with the playback guide."
            )
        if self.report.extra_notes > max(2, self.report.total_notes // 10):
            return (
                "Your timing is developing nicely. A slightly calmer touch will "
                "help remove extra notes and improve the final score."
            )
        if self.report.overall_accuracy >= 85.0:
            return (
                "Excellent consistency across timing and note duration. Try a "
                "small tempo increase when you are ready for the next challenge."
            )
        return (
            "You have a solid foundation. Repeat the passage and aim to turn "
            "the Close and Good notes into Great or Perfect attacks."
        )

    @staticmethod
    def _style_sheet() -> str:
        return """
            QDialog#performanceResultDialog,
            QWidget#resultContent,
            QScrollArea#resultScroll {
                color: #E7EAF0;
                background-color: #11151D;
            }
            QScrollBar:vertical {
                width: 9px;
                margin: 2px;
                background: #11151D;
            }
            QScrollBar::handle:vertical {
                min-height: 28px;
                background: #3A4559;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            QFrame#heroCard {
                background-color: #192230;
                border: 1px solid #34435A;
                border-radius: 12px;
            }
            QLabel#eyebrow {
                color: #57C7FF;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 2px;
            }
            QLabel#resultTitle {
                color: #F5F8FC;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#overallScore {
                color: #FFFFFF;
                font-size: 42px;
                font-weight: 800;
            }
            QLabel#ratingText {
                color: #AEB9C9;
                font-size: 12px;
            }
            QFrame#metricCard,
            QFrame#sectionCard {
                background-color: #181E28;
                border: 1px solid #2A3343;
                border-radius: 9px;
            }
            QLabel#metricTitle {
                color: #CFD7E4;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#metricValue {
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#metricDetail,
            QLabel#sectionSubtitle {
                color: #8995A8;
                font-size: 10px;
            }
            QProgressBar#metricProgress,
            QProgressBar#gradeProgress {
                background-color: #303849;
                border: none;
                border-radius: 3px;
            }
            QLabel#sectionHeading {
                color: #F1F4F9;
                font-size: 13px;
                font-weight: 700;
            }
            QFrame#countItem {
                background-color: #202735;
                border: 1px solid #303A4C;
                border-radius: 7px;
            }
            QLabel#countValue {
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#countCaption {
                color: #8490A4;
                font-size: 9px;
                font-weight: 700;
            }
            QLabel#gradeName,
            QLabel#gradeCount {
                color: #B9C3D1;
                font-size: 11px;
            }
            QLabel#gradeCount {
                font-weight: 700;
            }
            QFrame#tipCard {
                background-color: #17242A;
                border: 1px solid #29505B;
                border-radius: 9px;
            }
            QLabel#tipBadge {
                color: #08191F;
                background-color: #67E8A5;
                border-radius: 6px;
                font-size: 9px;
                font-weight: 800;
            }
            QLabel#tipText {
                color: #C6D4D7;
                font-size: 11px;
            }
            QFrame#actionBar {
                background-color: #151A23;
                border-top: 1px solid #2A3343;
            }
            QPushButton {
                min-width: 110px;
                padding: 9px 17px;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton#secondaryButton {
                color: #E1E6EE;
                background-color: #252D3B;
                border: 1px solid #455066;
            }
            QPushButton#secondaryButton:hover {
                background-color: #333D50;
                border-color: #65718A;
            }
            QPushButton#primaryButton {
                color: #08151C;
                background-color: #57C7FF;
                border: 1px solid #57C7FF;
            }
            QPushButton#primaryButton:hover {
                background-color: #78D2FF;
                border-color: #78D2FF;
            }
        """
