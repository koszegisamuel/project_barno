"""Application controller for live MIDI input and MIDI-file playback.

The existing ``MidiWorker`` remains responsible for portable FluidSynth setup
and physical MIDI input.  This module adds an independent, monotonic-clock file
scheduler that reuses the *same* FluidSynth instance after it is ready.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import mido
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt

from src.controller.midi_playback_worker import MidiTimeline, MidiPlaybackWorker, MidiDispatch, NoteSpan
from src.model.midi import MidiWorker


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