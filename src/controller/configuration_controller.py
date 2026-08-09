"""Typed configuration model and JSON persistence controller."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import ClassVar, Mapping

from PySide6.QtCore import QObject, Signal
import rtmidi


@dataclass(frozen=True, slots=True)
class Configuration:
    """Application configuration available globally after startup.

    Consumers can use ``Configuration.current().audio_driver`` without knowing
    anything about the JSON file or configuration dialog.
    """

    midi_input: str = "Default MIDI Input"
    audio_driver: str = "System Default"
    instrument: str = "Acoustic Grand Piano"
    show_playback_notes: bool = True

    _current: ClassVar["Configuration | None"] = None

    @classmethod
    def current(cls) -> "Configuration":
        """Return the process-wide configuration, or defaults before loading."""

        if cls._current is None:
            cls._current = cls()
        return cls._current

    @classmethod
    def install(cls, configuration: "Configuration") -> "Configuration":
        """Replace the process-wide immutable configuration snapshot."""

        cls._current = configuration
        return configuration

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "Configuration":
        defaults = cls()
        midi_input = values.get("midi_input", defaults.midi_input)
        audio_driver = values.get("audio_driver", defaults.audio_driver)
        instrument = values.get("instrument", defaults.instrument)
        show_notes = values.get(
            "show_playback_notes", defaults.show_playback_notes
        )

        for key, value in (
            ("midi_input", midi_input),
            ("audio_driver", audio_driver),
            ("instrument", instrument),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a non-empty string")
        if not isinstance(show_notes, bool):
            raise ValueError("show_playback_notes must be true or false")

        return cls(
            midi_input=midi_input.strip(),
            audio_driver=audio_driver.strip(),
            instrument=instrument.strip(),
            show_playback_notes=show_notes,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ConfigurationController(QObject):
    """Owns dialog coordination plus atomic ``conf.json`` persistence."""

    configuration_saved = Signal(object)  # Configuration

    def __init__(
        self,
        parent: QObject | None = None,
        configuration_path: str | Path | None = None,
    ):
        super().__init__(parent)
        self.configuration_path = (
            Path(configuration_path).expanduser().resolve()
            if configuration_path is not None
            else self.default_configuration_path()
        )
        self.last_load_error: str | None = None
        self._dialog = None

    @staticmethod
    def default_configuration_path() -> Path:
        """Return ``<project root>/conf.json`` for src/controller placement."""

        return Path(__file__).resolve().parents[2] / "conf.json"

    @staticmethod
    def get_connected_midi_devices() -> list[str]:
        """Return list of connected MIDI devices."""
        devices = []
        midiin = rtmidi.RtMidiIn()
        ports = range(midiin.getPortCount())
        if ports:
            for i in ports:
                devices.append(midiin.getPortName(i))
        return devices

    def load_configuration(self) -> Configuration:
        """Load, validate, install, and return the typed configuration.

        Missing files are normal on first launch and return defaults. Invalid
        JSON also falls back safely while retaining ``last_load_error`` for
        optional diagnostics instead of preventing the application from opening.
        """

        self.last_load_error = None
        if not self.configuration_path.exists():
            return Configuration.install(Configuration())

        try:
            with self.configuration_path.open("r", encoding="utf-8") as file:
                values = json.load(file)
            if not isinstance(values, dict):
                raise ValueError("The configuration root must be a JSON object")
            configuration = Configuration.from_mapping(values)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            self.last_load_error = str(error)
            configuration = Configuration()

        return Configuration.install(configuration)

    def save_configuration(self, configuration: Configuration) -> None:
        """Atomically create or overwrite the same ``conf.json`` file."""

        self.configuration_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.configuration_path.with_suffix(
            self.configuration_path.suffix + ".tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(
                    configuration.to_dict(),
                    file,
                    indent=2,
                    ensure_ascii=False,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.configuration_path)
        except OSError:
            # Never leave a misleading partial configuration beside conf.json.
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        Configuration.install(configuration)
        self.configuration_saved.emit(configuration)

    def open_configuration(self, parent=None) -> None:
        """Open a fresh modal view populated from the latest disk state."""

        # Local import avoids coupling the reusable model to the view module and
        # prevents a circular import through HorizontalSettingsWidget.
        from src.view.configuration_tab import ConfigurationDialog

        configuration = self.load_configuration()
        dialog = ConfigurationDialog(parent)
        dialog.set_configuration(configuration)
        dialog.save_requested.connect(
            lambda: self._save_dialog_configuration(dialog)
        )
        self._dialog = dialog
        try:
            dialog.exec()
        finally:
            self._dialog = None

    def _save_dialog_configuration(self, dialog) -> None:
        try:
            configuration = Configuration.from_mapping(dialog.form_values())
            self.save_configuration(configuration)
        except (OSError, ValueError) as error:
            dialog.show_save_error(str(error))
            return
        dialog.accept()