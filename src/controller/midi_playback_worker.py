"""Application controller for live MIDI input and MIDI-file playback.

The existing ``MidiWorker`` remains responsible for portable FluidSynth setup
and physical MIDI input.  This module adds an independent, monotonic-clock file
scheduler that reuses the *same* FluidSynth instance after it is ready.
"""

from __future__ import annotations

import bisect
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido
from PySide6.QtCore import QObject, QThread, Signal




@dataclass(frozen=True, slots=True)
class ScheduledMidiEvent:
    """A MIDI channel message at an absolute position in song seconds."""

    at_seconds: float
    message: mido.Message


@dataclass(frozen=True, slots=True)
class MidiDispatch:
    """Generation-tagged event used to invalidate events after a seek."""

    generation: int
    event: ScheduledMidiEvent


@dataclass(frozen=True, slots=True)
class NoteSpan:
    """A paired note-on/note-off used for rendering and note chasing."""

    start_seconds: float
    end_seconds: float
    note: int
    channel: int
    velocity: int


@dataclass(frozen=True, slots=True)
class MidiTimeline:
    """Immutable, tempo-aware representation of one Standard MIDI File."""

    path: Path
    ticks_per_beat: int
    duration_seconds: float
    events: tuple[ScheduledMidiEvent, ...]
    note_spans: tuple[NoteSpan, ...]

    @classmethod
    def from_file(cls, path: str | Path) -> "MidiTimeline":
        """Merge all tracks and convert delta ticks through the MIDI tempo map."""

        midi_path = Path(path).expanduser().resolve()
        midi = mido.MidiFile(midi_path)
        merged_track = mido.merge_tracks(midi.tracks)

        tempo = 500_000  # MIDI default: 120 BPM in microseconds per beat.
        song_seconds = 0.0
        events: list[ScheduledMidiEvent] = []
        spans: list[NoteSpan] = []
        open_notes: dict[
            tuple[int, int], deque[tuple[float, int]]
        ] = defaultdict(deque)

        for message in merged_track:
            # The tempo active during the preceding delta determines its length.
            song_seconds += mido.tick2second(
                message.time, midi.ticks_per_beat, tempo
            )
            if message.type == "set_tempo":
                tempo = message.tempo

            # Meta messages control parsing/timing but are not sent to FluidSynth.
            if message.is_meta:
                continue

            clean_message = message.copy(time=0)
            if clean_message.type == "note_on" and clean_message.velocity == 0:
                clean_message = mido.Message(
                    "note_off",
                    channel=clean_message.channel,
                    note=clean_message.note,
                    velocity=0,
                    time=0,
                )

            events.append(ScheduledMidiEvent(song_seconds, clean_message))

            if clean_message.type == "note_on":
                open_notes[(clean_message.channel, clean_message.note)].append(
                    (song_seconds, clean_message.velocity)
                )
            elif clean_message.type == "note_off":
                key = (clean_message.channel, clean_message.note)
                if open_notes[key]:
                    start, velocity = open_notes[key].popleft()
                    spans.append(
                        NoteSpan(
                            start_seconds=start,
                            end_seconds=max(start, song_seconds),
                            note=clean_message.note,
                            channel=clean_message.channel,
                            velocity=velocity,
                        )
                    )

        # Malformed files occasionally omit a final note-off. Close those notes
        # defensively so playback and visualization can still finish cleanly.
        for (channel, note), starts in open_notes.items():
            for start, velocity in starts:
                end = max(song_seconds, start + 0.1)
                song_seconds = max(song_seconds, end)
                spans.append(NoteSpan(start, end, note, channel, velocity))

        spans.sort(key=lambda span: (span.start_seconds, span.end_seconds))
        return cls(
            path=midi_path,
            ticks_per_beat=midi.ticks_per_beat,
            duration_seconds=max(0.0, song_seconds),
            events=tuple(events),
            note_spans=tuple(spans),
        )

    def held_notes_at(self, seconds: float) -> tuple[NoteSpan, ...]:
        """Notes that began before a seek target and end after it."""

        return tuple(
            note
            for note in self.note_spans
            if note.start_seconds < seconds < note.end_seconds
        )

    def channel_state_at(self, seconds: float) -> tuple[mido.Message, ...]:
        """Chase the latest program/controller/pitch state before a seek target.

        Without state chasing, jumping past a program or sustain change can use
        the wrong sound or pedal state even if note timing itself is correct.
        """

        latest: dict[tuple, ScheduledMidiEvent] = {}
        for event in self.events:
            if event.at_seconds >= seconds:
                break
            message = event.message
            if message.type == "program_change":
                latest[(message.channel, "program")] = event
            elif message.type == "control_change":
                latest[(message.channel, "cc", message.control)] = event
            elif message.type == "pitchwheel":
                latest[(message.channel, "pitch")] = event
            elif message.type == "aftertouch":
                latest[(message.channel, "pressure")] = event

        # Original timestamp ordering retains bank-select-before-program behavior.
        return tuple(
            event.message
            for event in sorted(latest.values(), key=lambda item: item.at_seconds)
        )


class MidiPlaybackWorker(QThread):
    """Drift-free MIDI scheduler using one monotonic song-time clock."""

    position_changed = Signal(float)
    midi_event_due = Signal(object)  # MidiDispatch
    chase_requested = Signal(object, object)  # state messages, held notes
    panic_requested = Signal()
    playback_changed = Signal(bool)
    end_reached = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._condition = threading.Condition()
        self._timeline: MidiTimeline | None = None
        self._event_times: tuple[float, ...] = ()
        self._next_event_index = 0
        self._position = 0.0
        self._anchor_position = 0.0
        self._anchor_clock = time.perf_counter()
        self._speed = 1.0
        self._playing = False
        self._shutdown = False
        self._generation = 0

    def _position_locked(self, now: float | None = None) -> float:
        if not self._playing:
            return self._position
        clock = time.perf_counter() if now is None else now
        return self._anchor_position + (
            clock - self._anchor_clock
        ) * self._speed

    def current_position(self) -> float:
        with self._condition:
            return self._position_locked()

    def is_playing(self) -> bool:
        with self._condition:
            return self._playing

    def is_current_generation(self, generation: int) -> bool:
        with self._condition:
            return generation == self._generation

    def set_timeline(self, timeline: MidiTimeline) -> None:
        with self._condition:
            self._generation += 1
            self._timeline = timeline
            self._event_times = tuple(
                event.at_seconds for event in timeline.events
            )
            self._next_event_index = 0
            self._position = 0.0
            self._anchor_position = 0.0
            self._anchor_clock = time.perf_counter()
            self._playing = False
            self._condition.notify_all()
        self.panic_requested.emit()
        self.position_changed.emit(0.0)
        self.playback_changed.emit(False)

    def play(self) -> None:
        with self._condition:
            if self._timeline is None or self._playing:
                return
            if self._position >= self._timeline.duration_seconds:
                self._position = 0.0
                self._next_event_index = 0
            self._anchor_position = self._position
            self._anchor_clock = time.perf_counter()
            self._playing = True
            state = self._timeline.channel_state_at(self._position)
            held_notes = self._timeline.held_notes_at(self._position)
            self._condition.notify_all()

        # Recreate synth state cleared by pause/seek panic before scheduling more.
        self.chase_requested.emit(state, held_notes)
        self.playback_changed.emit(True)

    def pause(self) -> None:
        with self._condition:
            if not self._playing:
                return
            self._position = self._position_locked()
            self._playing = False
            self._generation += 1
            self._condition.notify_all()
        self.panic_requested.emit()
        self.position_changed.emit(self._position)
        self.playback_changed.emit(False)

    def stop_playback(self) -> None:
        with self._condition:
            self._generation += 1
            self._playing = False
            self._position = 0.0
            self._anchor_position = 0.0
            self._next_event_index = 0
            self._condition.notify_all()
        self.panic_requested.emit()
        self.position_changed.emit(0.0)
        self.playback_changed.emit(False)

    def seek(self, requested_seconds: float) -> None:
        with self._condition:
            if self._timeline is None:
                return
            self._generation += 1
            position = min(
                max(0.0, requested_seconds),
                self._timeline.duration_seconds,
            )
            self._position = position
            self._anchor_position = position
            self._anchor_clock = time.perf_counter()
            self._next_event_index = bisect.bisect_left(
                self._event_times, position
            )
            playing = self._playing
            state = self._timeline.channel_state_at(position) if playing else ()
            held_notes = self._timeline.held_notes_at(position) if playing else ()
            self._condition.notify_all()

        self.panic_requested.emit()
        if playing:
            self.chase_requested.emit(state, held_notes)
        self.position_changed.emit(position)

    def set_speed(self, speed: float) -> None:
        speed = min(max(speed, 0.25), 2.0)
        with self._condition:
            now = time.perf_counter()
            # Re-anchor first so elapsed time is never retroactively rescaled.
            self._position = self._position_locked(now)
            self._anchor_position = self._position
            self._anchor_clock = now
            self._speed = speed
            self._condition.notify_all()

    def request_shutdown(self) -> None:
        with self._condition:
            self._shutdown = True
            self._condition.notify_all()

    def run(self) -> None:
        last_position_emit = 0.0
        while True:
            due_events: list[ScheduledMidiEvent] = []
            reached_end = False

            with self._condition:
                if self._shutdown:
                    return
                if not self._playing or self._timeline is None:
                    self._condition.wait(timeout=0.1)
                    continue

                now = time.perf_counter()
                dispatch_generation = self._generation
                position = self._position_locked(now)
                duration = self._timeline.duration_seconds
                if position >= duration:
                    position = duration
                    self._position = duration
                    self._playing = False
                    reached_end = True

                # Small look-ahead offsets signal/call overhead without drift.
                dispatch_limit = min(duration, position + 0.002 * self._speed)
                while (
                    self._next_event_index < len(self._timeline.events)
                    and self._timeline.events[
                        self._next_event_index
                    ].at_seconds <= dispatch_limit
                ):
                    due_events.append(
                        self._timeline.events[self._next_event_index]
                    )
                    self._next_event_index += 1

            for event in due_events:
                self.midi_event_due.emit(
                    MidiDispatch(dispatch_generation, event)
                )

            if now - last_position_emit >= 1.0 / 60.0 or reached_end:
                self.position_changed.emit(position)
                last_position_emit = now

            if reached_end:
                self.panic_requested.emit()
                self.playback_changed.emit(False)
                self.end_reached.emit()
            else:
                with self._condition:
                    self._condition.wait(timeout=0.003)