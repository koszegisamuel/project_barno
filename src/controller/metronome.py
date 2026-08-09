"""Tempo-map-aware metronome scheduling and FluidSynth click output.

The schedule is expressed in the same absolute *song seconds* as MIDI file
playback.  The playback worker can therefore schedule clicks with its existing
monotonic clock, automatically following pause, seek and playback-speed changes.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Protocol

import mido


@dataclass(frozen=True, slots=True)
class MetronomeTick:
    """One notated beat in a MIDI file."""

    at_seconds: float
    beat_in_bar: int
    beats_per_bar: int

    @property
    def accented(self) -> bool:
        """The first beat of every bar receives the stronger click."""

        return self.beat_in_bar == 0


@dataclass(frozen=True, slots=True)
class MetronomeDispatch:
    """Generation-tagged tick, invalidated when playback seeks or pauses."""

    generation: int
    tick: MetronomeTick


@dataclass(frozen=True, slots=True)
class _TempoPoint:
    at_tick: float
    at_seconds: float
    microseconds_per_quarter: int


@dataclass(frozen=True, slots=True)
class _TimeSignaturePoint:
    at_tick: float
    numerator: int
    denominator: int


@dataclass(frozen=True, slots=True)
class MetronomeSchedule:
    """Immutable clicks generated from MIDI tempo and time-signature maps."""

    ticks: tuple[MetronomeTick, ...]

    @classmethod
    def from_midi(cls, midi: mido.MidiFile) -> "MetronomeSchedule":
        """Build a beat schedule without approximating tempo changes.

        MIDI tempo is always measured per quarter note. Time-signature
        denominators are applied separately so, for example, 6/8 receives
        eighth-note clicks with an accent every six clicks.
        """

        ticks_per_quarter = midi.ticks_per_beat
        merged_track = mido.merge_tracks(midi.tracks)
        absolute_tick = 0.0
        song_seconds = 0.0
        tempo = 500_000  # Standard MIDI default: 120 quarter notes per minute.

        tempo_points = [_TempoPoint(0.0, 0.0, tempo)]
        signature_points = [_TimeSignaturePoint(0.0, 4, 4)]

        for message in merged_track:
            delta_ticks = float(message.time)
            song_seconds += mido.tick2second(
                delta_ticks,
                ticks_per_quarter,
                tempo,
            )
            absolute_tick += delta_ticks

            if message.type == "set_tempo":
                tempo = int(message.tempo)
                point = _TempoPoint(absolute_tick, song_seconds, tempo)
                cls._replace_or_append_tempo(tempo_points, point)
            elif message.type == "time_signature":
                point = _TimeSignaturePoint(
                    absolute_tick,
                    max(1, int(message.numerator)),
                    max(1, int(message.denominator)),
                )
                cls._replace_or_append_signature(signature_points, point)

        if absolute_tick <= 0.0:
            return cls(())

        tempo_ticks = [point.at_tick for point in tempo_points]
        generated: list[MetronomeTick] = []
        epsilon = 1e-7

        for region_index, signature in enumerate(signature_points):
            region_end = (
                signature_points[region_index + 1].at_tick
                if region_index + 1 < len(signature_points)
                else absolute_tick
            )
            if signature.at_tick >= absolute_tick:
                break

            ticks_per_notated_beat = (
                ticks_per_quarter * 4.0 / signature.denominator
            )
            if ticks_per_notated_beat <= 0.0:
                continue

            beat_tick = signature.at_tick
            beat_in_bar = 0
            # A signature change starts a fresh bar. The region endpoint is
            # exclusive so two signature regions never create a duplicate tick.
            while (
                beat_tick < region_end - epsilon
                and beat_tick < absolute_tick - epsilon
            ):
                at_seconds = cls._tick_to_seconds(
                    beat_tick,
                    tempo_points,
                    tempo_ticks,
                    ticks_per_quarter,
                )
                generated.append(
                    MetronomeTick(
                        at_seconds=at_seconds,
                        beat_in_bar=beat_in_bar,
                        beats_per_bar=signature.numerator,
                    )
                )
                beat_in_bar = (beat_in_bar + 1) % signature.numerator
                beat_tick += ticks_per_notated_beat

        return cls(tuple(generated))

    @staticmethod
    def _replace_or_append_tempo(
        points: list[_TempoPoint],
        point: _TempoPoint,
    ) -> None:
        if points and points[-1].at_tick == point.at_tick:
            points[-1] = point
        else:
            points.append(point)

    @staticmethod
    def _replace_or_append_signature(
        points: list[_TimeSignaturePoint],
        point: _TimeSignaturePoint,
    ) -> None:
        if points and points[-1].at_tick == point.at_tick:
            points[-1] = point
        else:
            points.append(point)

    @staticmethod
    def _tick_to_seconds(
        tick: float,
        tempo_points: list[_TempoPoint],
        tempo_ticks: list[float],
        ticks_per_quarter: int,
    ) -> float:
        point_index = max(0, bisect.bisect_right(tempo_ticks, tick) - 1)
        point = tempo_points[point_index]
        return point.at_seconds + mido.tick2second(
            tick - point.at_tick,
            ticks_per_quarter,
            point.microseconds_per_quarter,
        )


class FluidSynthLike(Protocol):
    """Small part of the pyFluidSynth interface used by the click player."""

    def program_select(
        self,
        channel: int,
        soundfont_id: int,
        bank: int,
        preset: int,
    ) -> object: ...

    def noteon(self, channel: int, note: int, velocity: int) -> object: ...

    def noteoff(self, channel: int, note: int) -> object: ...


class FluidSynthMetronome:
    """Render clicks from a dedicated soundfont preset and MIDI channel.

    The application's live keyboard remains on FluidSynth channel 0. Selecting
    the metronome preset on a separate channel is essential: program selection
    is channel-local, so selecting bank 128/preset 1 on channel 0 would replace
    the instrument chosen by ``midi.py`` for live playing.

    ``soundfont_id`` must be the integer returned by ``fs.sfload(...)``. It can
    be supplied at construction, later through :meth:`set_soundfont_id`, or to
    :meth:`play_tick` when the MIDI worker initializes asynchronously.
    """

    DEFAULT_CHANNEL = 15
    DEFAULT_BANK = 128
    DEFAULT_PRESET = 1
    ACCENT_NOTE = 75
    REGULAR_NOTE = 76
    ACCENT_VELOCITY = 118
    REGULAR_VELOCITY = 88

    def __init__(
        self,
        soundfont_id: int | None = None,
        *,
        channel: int = DEFAULT_CHANNEL,
        bank: int = DEFAULT_BANK,
        preset: int = DEFAULT_PRESET,
    ) -> None:
        if not 0 <= channel <= 15:
            raise ValueError("FluidSynth channel must be between 0 and 15.")
        if bank < 0 or preset < 0:
            raise ValueError("Soundfont bank and preset must be non-negative.")

        self._soundfont_id = soundfont_id
        self._channel = channel
        self._bank = bank
        self._preset = preset
        self._active_note: int | None = None
        self._configured_synth: tuple[int, int] | None = None

    @property
    def channel(self) -> int:
        return self._channel

    def set_soundfont_id(self, soundfont_id: int) -> None:
        """Set the ``sfload`` result and reconfigure on the next click."""

        soundfont_id = int(soundfont_id)
        if soundfont_id != self._soundfont_id:
            self._soundfont_id = soundfont_id
            self._configured_synth = None

    def configure(
        self,
        synth: FluidSynthLike,
        soundfont_id: int | None = None,
    ) -> None:
        """Select bank 128/preset 1 once on the metronome-only channel."""

        if soundfont_id is not None:
            self.set_soundfont_id(soundfont_id)
        if self._soundfont_id is None:
            raise RuntimeError(
                "Metronome soundfont_id is not configured. Pass the integer "
                "returned by fs.sfload(...) to FluidSynthMetronome or "
                "play_tick()."
            )

        configuration = (id(synth), self._soundfont_id)
        if self._configured_synth == configuration:
            return

        synth.program_select(
            self._channel,
            self._soundfont_id,
            self._bank,
            self._preset,
        )
        self._configured_synth = configuration

    def play_tick(
        self,
        synth: FluidSynthLike,
        tick: MetronomeTick,
        soundfont_id: int | None = None,
    ) -> None:
        """Ensure the preset, release the previous click and play this beat."""

        self.configure(synth, soundfont_id)
        self.silence(synth)
        note = self.ACCENT_NOTE if tick.accented else self.REGULAR_NOTE
        velocity = (
            self.ACCENT_VELOCITY
            if tick.accented
            else self.REGULAR_VELOCITY
        )
        synth.noteon(self._channel, note, velocity)
        self._active_note = note

    def silence(self, synth: FluidSynthLike) -> None:
        """Release a pending click during pause, seek, stop or disable."""

        if self._active_note is None:
            return
        synth.noteoff(self._channel, self._active_note)
        self._active_note = None
