"""Real-time note matching and performance statistics for MIDI playback."""

from __future__ import annotations

import bisect
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class OnsetFeedback:
    """Immediate result produced when a physical key is pressed."""

    note: int
    grade: str
    label: str
    matched: bool
    timing_error_ms: float | None = None


@dataclass(frozen=True, slots=True)
class HoldFeedback:
    """Duration result produced when a physical key is released."""

    note: int
    grade: str
    label: str
    matched: bool
    hold_ratio: float | None = None


@dataclass(frozen=True, slots=True)
class PerformanceReport:
    """Final immutable statistics for one uninterrupted playback attempt."""

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

    def log_summary(self) -> str:
        return (
            "Performance result: "
            f"hits {self.hit_notes}/{self.total_notes} "
            f"({self.hit_ratio:.1f}%), missed {self.missed_notes}, "
            f"extra {self.extra_notes}, onset {self.onset_precision:.1f}%, "
            f"hold {self.hold_accuracy:.1f}%, overall "
            f"{self.overall_accuracy:.1f}% "
            f"[perfect {self.perfect_notes}, great {self.great_notes}, "
            f"good {self.good_notes}, close {self.close_notes}]"
        )


@dataclass(slots=True)
class _ExpectedNote:
    index: int
    note: int
    start_seconds: float
    end_seconds: float
    matched: bool = False
    onset_score: float = 0.0
    hold_score: float | None = None
    grade: str = "close"

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass(frozen=True, slots=True)
class _ActiveHit:
    expected_index: int
    pressed_at_seconds: float


class PerformanceTracker:
    """Match live notes against an immutable song timeline efficiently.

    Candidate lookup is grouped by pitch and uses binary search, so each key
    press is O(log n) rather than scanning every song note. All time positions
    are musical song seconds; onset errors are divided by playback speed to
    preserve the same human timing window at every tempo multiplier.
    """

    ONSET_WINDOW_SECONDS = 0.180
    PERFECT_WINDOW_SECONDS = 0.045
    GREAT_WINDOW_SECONDS = 0.090
    GOOD_WINDOW_SECONDS = 0.140
    MIN_HOLD_SCORING_SECONDS = 0.250
    MIN_ACCEPTABLE_HOLD_RATIO = 0.82
    MAX_ACCEPTABLE_HOLD_RATIO = 1.22
    LOWEST_PIANO_NOTE = 21
    HIGHEST_PIANO_NOTE = 108
    LAYERED_NOTE_MERGE_SECONDS = 0.012

    def __init__(self) -> None:
        self._active = False
        self._expected: list[_ExpectedNote] = []
        self._indices_by_pitch: dict[int, list[int]] = {}
        self._starts_by_pitch: dict[int, list[float]] = {}
        self._active_hits: dict[int, deque[_ActiveHit]] = defaultdict(deque)
        self._unmatched_active: dict[int, int] = defaultdict(int)
        self._extra_notes = 0
        self._session_start = 0.0

    @property
    def is_active(self) -> bool:
        return self._active

    def start_session(
        self,
        note_spans: Iterable,
        start_position_seconds: float = 0.0,
    ) -> None:
        """Start or restart scoring from a playback position."""

        self.cancel_session()
        self._session_start = max(0.0, start_position_seconds)

        # Notes already underway when playback begins are excluded because their
        # onset cannot fairly be judged. Notes at the exact start are included.
        eligible_spans = tuple(
            span
            for span in note_spans
            if (
                span.start_seconds >= self._session_start
                and self.LOWEST_PIANO_NOTE <= span.note <= self.HIGHEST_PIANO_NOTE
                and getattr(span, "channel", 0) != 9
            )
        )
        # Layered MIDI arrangements often duplicate one musical note across
        # several channels. Collapse near-simultaneous duplicates so a pianist
        # is never expected to strike the same physical key twice at once.
        collapsed: list[list[float | int]] = []
        latest_by_pitch: dict[int, int] = {}
        for span in eligible_spans:
            previous_index = latest_by_pitch.get(span.note)
            if previous_index is not None:
                previous = collapsed[previous_index]
                if abs(span.start_seconds - float(previous[1])) <= self.LAYERED_NOTE_MERGE_SECONDS:
                    previous[2] = max(float(previous[2]), span.end_seconds)
                    continue
            latest_by_pitch[span.note] = len(collapsed)
            collapsed.append([span.note, span.start_seconds, span.end_seconds])

        self._expected = []
        for index, (note, start, end) in enumerate(collapsed):
            self._expected.append(
                _ExpectedNote(
                    index=index,
                    note=int(note),
                    start_seconds=float(start),
                    end_seconds=float(end),
                )
            )

        grouped: dict[int, list[int]] = defaultdict(list)
        for expected in self._expected:
            grouped[expected.note].append(expected.index)
        self._indices_by_pitch = dict(grouped)
        self._starts_by_pitch = {
            note: [self._expected[index].start_seconds for index in indices]
            for note, indices in self._indices_by_pitch.items()
        }
        self._active = True

    def cancel_session(self) -> None:
        self._active = False
        self._expected = []
        self._indices_by_pitch = {}
        self._starts_by_pitch = {}
        self._active_hits.clear()
        self._unmatched_active.clear()
        self._extra_notes = 0

    def note_on(
        self,
        note: int,
        song_position_seconds: float,
        playback_speed: float = 1.0,
    ) -> OnsetFeedback:
        if not self._active:
            return OnsetFeedback(note, "live", "", False)

        speed = min(max(playback_speed, 0.25), 2.0)
        expected_index = self._nearest_unmatched_note(
            note,
            song_position_seconds,
            self.ONSET_WINDOW_SECONDS * speed,
        )
        if expected_index is None:
            self._extra_notes += 1
            self._unmatched_active[note] += 1
            return OnsetFeedback(note, "wrong", "Wrong note", False)

        expected = self._expected[expected_index]
        expected.matched = True
        error_wall_seconds = (
            song_position_seconds - expected.start_seconds
        ) / speed
        absolute_error = abs(error_wall_seconds)
        score = max(
            0.0,
            100.0 * (1.0 - absolute_error / self.ONSET_WINDOW_SECONDS),
        )
        grade, label = self._onset_grade(error_wall_seconds)
        expected.onset_score = score
        expected.grade = grade
        self._active_hits[note].append(
            _ActiveHit(expected_index, song_position_seconds)
        )
        return OnsetFeedback(
            note=note,
            grade=grade,
            label=label,
            matched=True,
            timing_error_ms=error_wall_seconds * 1000.0,
        )

    def note_off(
        self,
        note: int,
        song_position_seconds: float,
    ) -> HoldFeedback:
        if not self._active:
            return HoldFeedback(note, "live", "", False)
        if not self._active_hits[note]:
            if self._unmatched_active[note] > 0:
                self._unmatched_active[note] -= 1
                if self._unmatched_active[note] <= 0:
                    self._unmatched_active.pop(note, None)
                return HoldFeedback(note, "wrong", "Wrong note", False)
            return HoldFeedback(note, "live", "", False)

        active_hit = self._active_hits[note].popleft()
        if not self._active_hits[note]:
            self._active_hits.pop(note, None)
        expected = self._expected[active_hit.expected_index]

        expected_duration = expected.duration_seconds
        actual_duration = max(
            0.0, song_position_seconds - active_hit.pressed_at_seconds
        )
        if expected_duration < self.MIN_HOLD_SCORING_SECONDS:
            expected.hold_score = 100.0
            return HoldFeedback(note, "held", "Nice", True, 1.0)

        hold_ratio = actual_duration / expected_duration
        expected.hold_score = self._hold_score(hold_ratio)
        if hold_ratio < self.MIN_ACCEPTABLE_HOLD_RATIO:
            grade, label = "early_release", "Released early"
        elif hold_ratio > self.MAX_ACCEPTABLE_HOLD_RATIO:
            grade, label = "late_release", "Held too long"
        else:
            grade, label = "held", "Good hold"
        return HoldFeedback(note, grade, label, True, hold_ratio)

    def finalize(self, song_position_seconds: float) -> PerformanceReport:
        """Complete active holds and calculate final aggregate statistics."""

        if not self._active:
            return PerformanceReport(0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0)

        # Keys still down at end-of-song receive duration credit up to the end.
        for note, active_hits in tuple(self._active_hits.items()):
            while active_hits:
                active_hit = active_hits.popleft()
                expected = self._expected[active_hit.expected_index]
                duration = expected.duration_seconds
                if duration < self.MIN_HOLD_SCORING_SECONDS:
                    expected.hold_score = 100.0
                else:
                    actual = max(
                        0.0,
                        song_position_seconds - active_hit.pressed_at_seconds,
                    )
                    expected.hold_score = self._hold_score(actual / duration)

        matched = [note for note in self._expected if note.matched]
        total = len(self._expected)
        hit_count = len(matched)
        missed = total - hit_count
        hit_ratio = 100.0 * hit_count / total if total else 0.0
        onset_precision = self._average(
            note.onset_score for note in matched
        )
        hold_accuracy = self._average(
            note.hold_score if note.hold_score is not None else 0.0
            for note in matched
        )
        # Timing is weighted slightly higher while duration still materially
        # affects long-note performance.
        overall = (
            onset_precision * 0.65 + hold_accuracy * 0.35
            if matched
            else 0.0
        )
        grade_counts = {
            grade: sum(note.grade == grade for note in matched)
            for grade in ("perfect", "great", "good", "close")
        }
        report = PerformanceReport(
            total_notes=total,
            hit_notes=hit_count,
            missed_notes=missed,
            extra_notes=self._extra_notes,
            hit_ratio=hit_ratio,
            onset_precision=onset_precision,
            hold_accuracy=hold_accuracy,
            overall_accuracy=overall,
            perfect_notes=grade_counts["perfect"],
            great_notes=grade_counts["great"],
            good_notes=grade_counts["good"],
            close_notes=grade_counts["close"],
        )
        self.cancel_session()
        return report

    def _nearest_unmatched_note(
        self,
        note: int,
        position: float,
        tolerance: float,
    ) -> int | None:
        indices = self._indices_by_pitch.get(note)
        starts = self._starts_by_pitch.get(note)
        if not indices or not starts:
            return None

        best_index = None
        best_error = tolerance + 1.0
        # Only candidates inside the tolerance window are visited. This handles
        # dense trills/overlapping tracks without an arbitrary scan limit.
        left = bisect.bisect_left(starts, position - tolerance)
        right = bisect.bisect_right(starts, position + tolerance)
        for local_index in range(left, right):
            expected = self._expected[indices[local_index]]
            error = abs(position - expected.start_seconds)
            if not expected.matched and error <= tolerance and error < best_error:
                best_index = expected.index
                best_error = error
        return best_index

    @classmethod
    def _onset_grade(cls, error_seconds: float) -> tuple[str, str]:
        absolute_error = abs(error_seconds)
        if absolute_error <= cls.PERFECT_WINDOW_SECONDS:
            return "perfect", "Perfect"
        if absolute_error <= cls.GREAT_WINDOW_SECONDS:
            return "great", "Great"
        if absolute_error <= cls.GOOD_WINDOW_SECONDS:
            return "good", "Good"
        direction = "Late" if error_seconds > 0 else "Early"
        return "close", direction

    @classmethod
    def _hold_score(cls, hold_ratio: float) -> float:
        # Full credit inside the friendly range, then a smooth falloff.
        if cls.MIN_ACCEPTABLE_HOLD_RATIO <= hold_ratio <= cls.MAX_ACCEPTABLE_HOLD_RATIO:
            return 100.0
        if hold_ratio < cls.MIN_ACCEPTABLE_HOLD_RATIO:
            return max(0.0, 100.0 * hold_ratio / cls.MIN_ACCEPTABLE_HOLD_RATIO)
        overshoot = hold_ratio - cls.MAX_ACCEPTABLE_HOLD_RATIO
        return max(0.0, 100.0 * (1.0 - overshoot))

    @staticmethod
    def _average(values: Iterable[float]) -> float:
        collected = tuple(values)
        return sum(collected) / len(collected) if collected else 0.0