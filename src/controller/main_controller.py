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
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt

from src.model.midi import MidiWorker


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


class MainController(QObject):
    """Coordinates the unchanged live-input worker and file scheduler."""

    timeline_loaded = Signal(object)  # MidiTimeline
    playback_position_changed = Signal(float)
    playback_state_changed = Signal(bool)
    playback_note_on = Signal(int)
    playback_note_off = Signal(int)
    playback_notes_reset = Signal()
    playback_error = Signal(str)

    SYNTH_STARTUP_GRACE_SECONDS = 1.0
    SYNTH_STARTUP_TIMEOUT_SECONDS = 15.0

    def __init__(self):
        super().__init__()
        self.view = None
        self.midi_thread = None
        self.worker = None
        self.timeline: MidiTimeline | None = None
        self._pending_file_play = False
        self._engine_started_at = 0.0
        self._engine_failed = False
        self._file_voice_lock = threading.Lock()
        self._file_active_notes: dict[tuple[int, int], int] = {}
        self._file_sustain_channels: set[int] = set()

        self.playback_worker = MidiPlaybackWorker(self)
        # Direct delivery runs FluidSynth calls in the timing thread instead of
        # waiting for the GUI event loop.
        self.playback_worker.midi_event_due.connect(
            self._dispatch_file_event,
            Qt.ConnectionType.DirectConnection,
        )
        self.playback_worker.chase_requested.connect(self._chase_file_state)
        self.playback_worker.panic_requested.connect(self._file_all_notes_off)
        self.playback_worker.position_changed.connect(
            self.playback_position_changed
        )
        self.playback_worker.playback_changed.connect(
            self.playback_state_changed
        )
        self.playback_worker.end_reached.connect(self._on_file_end)
        self.playback_worker.start(QThread.Priority.TimeCriticalPriority)

    def set_view(self, view):
        self.view = view

    # ------------------------------------------------------------------
    # Existing live MIDI input setup. Its signals and MidiWorker logic are
    # preserved; only the running-state guard and error bookkeeping are added.
    # ------------------------------------------------------------------

    def start_midi_engine(self):
        if self.midi_thread and self.midi_thread.isRunning():
            print("Midi engine already running")
            return

        self.midi_thread = QThread()
        self.worker = MidiWorker()
        self.worker.moveToThread(self.midi_thread)

        # Original physical-input connections.
        self.midi_thread.started.connect(self.worker.start_logic)
        self.worker.note_detected.connect(self.view.update_note_display)
        self.worker.error_occurred.connect(self.view.show_error)
        self.worker.note_on.connect(self.view.piano_widget.handle_note_on)
        self.worker.note_off.connect(self.view.piano_widget.handle_note_off)

        # Additional bookkeeping does not alter the input event path.
        self.worker.error_occurred.connect(self._on_engine_error)
        self._engine_failed = False
        self._engine_started_at = time.perf_counter()
        self.midi_thread.start(QThread.Priority.TimeCriticalPriority)
        self.view.set_loading_state(True)

    # ------------------------------------------------------------------
    # MIDI file transport API used by MainWindow.
    # ------------------------------------------------------------------

    def load_midi_file(self, path: str | Path) -> None:
        try:
            timeline = MidiTimeline.from_file(path)
        except (OSError, EOFError, ValueError) as error:
            self.playback_error.emit(str(error))
            return

        self.timeline = timeline
        self.playback_worker.set_timeline(timeline)
        self.timeline_loaded.emit(timeline)

    def toggle_file_playback(self) -> None:
        if self.timeline is None:
            self.playback_error.emit("Import a MIDI file before pressing Play.")
        elif self.playback_worker.is_playing():
            self.playback_worker.pause()
        else:
            self._request_file_play()

    def _request_file_play(self) -> None:
        if self._synth_is_ready():
            self.playback_worker.play()
            return

        self._pending_file_play = True
        if not self.midi_thread or not self.midi_thread.isRunning():
            self.start_midi_engine()
        if self.view:
            self.view.update_note_display(
                "Starting FluidSynth before MIDI-file playbackâŚ"
            )
        QTimer.singleShot(100, self._finish_pending_file_play)

    def _synth_is_ready(self) -> bool:
        # MidiWorker has no explicit ready signal and must remain unchanged. A
        # short grace period prevents playback from racing its soundfont load.
        return bool(
            self.worker
            and self.worker.fs is not None
            and not self._engine_failed
            and time.perf_counter() - self._engine_started_at
            >= self.SYNTH_STARTUP_GRACE_SECONDS
        )

    def _finish_pending_file_play(self) -> None:
        if not self._pending_file_play:
            return
        if self._synth_is_ready():
            self._pending_file_play = False
            self.playback_worker.play()
            return
        if (
            self._engine_failed
            or time.perf_counter() - self._engine_started_at
            > self.SYNTH_STARTUP_TIMEOUT_SECONDS
        ):
            self._pending_file_play = False
            self.playback_error.emit(
                "FluidSynth did not become ready for file playback."
            )
            return
        QTimer.singleShot(100, self._finish_pending_file_play)

    def pause_file_playback(self) -> None:
        self._pending_file_play = False
        self.playback_worker.pause()

    def stop_file_playback(self) -> None:
        self._pending_file_play = False
        self.playback_worker.stop_playback()

    def seek_file(self, seconds: float) -> None:
        self.playback_worker.seek(seconds)

    def set_file_speed(self, speed: float) -> None:
        self.playback_worker.set_speed(speed)

    def current_file_position(self) -> float:
        return self.playback_worker.current_position()

    def file_is_playing(self) -> bool:
        return self.playback_worker.is_playing()

    # ------------------------------------------------------------------
    # FluidSynth output. These calls reuse MidiWorker.fs; midi.py is untouched.
    # ------------------------------------------------------------------

    @Slot(object)
    def _dispatch_file_event(self, dispatch: MidiDispatch) -> None:
        if not self.playback_worker.is_current_generation(dispatch.generation):
            return
        if not self._synth_is_ready():
            return

        try:
            self._send_message_to_synth(dispatch.event.message)
        except Exception as error:  # FluidSynth bindings raise platform-specific errors.
            self.playback_error.emit(f"FluidSynth playback error: {error}")

    def _send_message_to_synth(self, message: mido.Message) -> None:
        fs = self.worker.fs
        if message.type == "note_on":
            fs.noteon(message.channel, message.note, message.velocity)
            with self._file_voice_lock:
                key = (message.channel, message.note)
                self._file_active_notes[key] = (
                    self._file_active_notes.get(key, 0) + 1
                )
            self.playback_note_on.emit(message.note)
        elif message.type == "note_off":
            fs.noteoff(message.channel, message.note)
            with self._file_voice_lock:
                key = (message.channel, message.note)
                remaining = self._file_active_notes.get(key, 0) - 1
                if remaining > 0:
                    self._file_active_notes[key] = remaining
                else:
                    self._file_active_notes.pop(key, None)
            self.playback_note_off.emit(message.note)
        elif message.type == "control_change":
            fs.cc(message.channel, message.control, message.value)
            if message.control == 64:
                with self._file_voice_lock:
                    if message.value >= 64:
                        self._file_sustain_channels.add(message.channel)
                    else:
                        self._file_sustain_channels.discard(message.channel)
        elif message.type == "program_change":
            fs.program_change(message.channel, message.program)
        elif message.type == "pitchwheel":
            fs.pitch_bend(message.channel, message.pitch + 8192)
        elif message.type == "aftertouch" and hasattr(fs, "channel_pressure"):
            fs.channel_pressure(message.channel, message.value)

    @Slot(object, object)
    def _chase_file_state(
        self,
        state_messages: tuple[mido.Message, ...],
        held_notes: tuple[NoteSpan, ...],
    ) -> None:
        if not self._synth_is_ready():
            return
        try:
            for message in state_messages:
                self._send_message_to_synth(message)
            for note in held_notes:
                self.worker.fs.noteon(note.channel, note.note, note.velocity)
                with self._file_voice_lock:
                    key = (note.channel, note.note)
                    self._file_active_notes[key] = (
                        self._file_active_notes.get(key, 0) + 1
                    )
                self.playback_note_on.emit(note.note)
        except Exception as error:
            self.playback_error.emit(f"FluidSynth seek error: {error}")

    @Slot()
    def _file_all_notes_off(self) -> None:
        # Release only voices/controllers known to come from file playback. A
        # global CC 123 would also silence unrelated physical-input notes.
        with self._file_voice_lock:
            active_notes = tuple(self._file_active_notes.items())
            sustain_channels = tuple(self._file_sustain_channels)
            self._file_active_notes.clear()
            self._file_sustain_channels.clear()

        if self.worker and self.worker.fs is not None:
            try:
                for channel in sustain_channels:
                    self.worker.fs.cc(channel, 64, 0)
                for (channel, note), voice_count in active_notes:
                    for _ in range(voice_count):
                        self.worker.fs.noteoff(channel, note)
            except Exception as error:
                self.playback_error.emit(f"FluidSynth reset error: {error}")
        self.playback_notes_reset.emit()

    @Slot()
    def _on_file_end(self) -> None:
        if self.view:
            self.view.update_note_display("Reached end of MIDI file.")

    @Slot(str)
    def _on_engine_error(self, _message: str) -> None:
        self._engine_failed = True
        self._pending_file_play = False
        if self.view:
            self.view.set_loading_state(False)

    def dispose(self):
        """Clean shutdown of both playback and physical-input threads."""

        self._pending_file_play = False
        self._file_all_notes_off()
        self.playback_worker.request_shutdown()
        self.playback_worker.wait(2000)

        if self.worker:
            self.worker.stop()
        if self.midi_thread:
            self.midi_thread.quit()
            self.midi_thread.wait()