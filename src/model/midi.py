import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
import rtmidi
import os
import sys
import ctypes

from src.controller.configuration_controller import Configuration
from src.util.instrument_registry import InstrumentRegistry


class MidiWorker(QObject):
    # Signals must be defined as class attributes
    note_detected = Signal(str)
    error_occurred = Signal(str)
    note_on = Signal(int)
    note_off = Signal(int)

    def __init__(self):
        super().__init__()
        self._running = True
        self.midiin = None
        self.fs = None
        self._current_dir = Path(__file__).resolve().parents[2]
        self._config = Configuration.current()

    @Slot()
    def start_logic(self):
        """The main loop - this runs in the background thread."""
        try:
            # Init RtMidi
            self._init_midi_input()

            # Init fluidsynth
            self._init_fluid_synth()

            while self._running:
                midi = self.midiin.getMessage()
                if midi:
                    note_num = midi.getNoteNumber()
                    velocity = midi.getVelocity()

                    if midi.isNoteOn():
                        self.fs.noteon(0, note_num, velocity)
                        self.note_detected.emit(f'Note: {midi.getMidiNoteName(note_num)}, Velocity: {velocity}')
                        self.note_on.emit(note_num)
                        print(f'Note: {midi.getMidiNoteName(note_num)}, Velocity: {velocity}')

                    elif midi.isNoteOff():
                        self.fs.noteoff(0, note_num)
                        self.note_off.emit(note_num)

                    elif midi.isController() and midi.getControllerNumber() == 64:
                        self.fs.cc(0, 64, midi.getControllerValue())

                time.sleep(0.001)

        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.cleanup()

    def _init_fluid_synth(self):
        fluidsynth = self._load_fluid_synth()

        self.fs = fluidsynth.Synth()
        self.fs.setting('midi.driver', 'none')
        self.fs.setting('audio.period-size', 128)
        self.fs.setting('audio.periods', 2)
        self.fs.setting('synth.sample-rate', 44100.0)
        self.fs.start(driver=self._config.audio_driver)

        # Update this path to your portable soundfont location
        sf_path = os.path.join(self._current_dir, 'soundfonts', 'FluidR3_GM.sf2')
        sf_id = self.fs.sfload(sf_path)
        configured_instrument = self._config.instrument
        self.fs.program_select(0, sf_id, 0, InstrumentRegistry.get_instrument_id(configured_instrument))
        self.soundfont_id = sf_id

    def _init_midi_input(self):
        self.midiin = rtmidi.RtMidiIn()
        ports = range(self.midiin.getPortCount())
        if ports:
            for i in ports:
                print(f"\nAvailable port: {self.midiin.getPortName(i)}")
        else:
            print('NO MIDI INPUT PORTS!')

        port_index = 0
        self.midiin.openPort(port_index)
        print(f"\nListening for MIDI input on: {port_index}")
        print("Press Ctrl+C to stop.\n")

    def stop(self):
        self._running = False

    def cleanup(self):
        if self.midiin:
            self.midiin.closePort()
        if self.fs:
            self.fs.delete()
        print("MIDI Engine Cleaned Up.")

    def _load_fluid_synth(self):
        fluidsynth_bin_path = os.path.join(self._current_dir, 'bin', 'fluidsynth')

        if sys.platform == 'win32':
            if os.path.exists(fluidsynth_bin_path):

                os.add_dll_directory(fluidsynth_bin_path)
                # Add  bin folder to the front of the PATH just for this session. This is required for fluidsynth import resolution
                os.environ['PATH'] = fluidsynth_bin_path + os.path.pathsep + os.environ['PATH']

                try:
                    ctypes.CDLL(os.path.join(fluidsynth_bin_path, 'libfluidsynth-3.dll'))
                    print("Verified: libfluidsynth-3.dll is loadable.")
                except Exception as e:
                    print(f"Manual check failed: {e}")
            else:
                print(f"Error: Folder not found at {fluidsynth_bin_path}")

        try:
            import fluidsynth

            print("Success: fluidsynth imported!")
        except ImportError as e:
            print("\n--- IMPORT ERROR ---")
            print(e)
            sys.exit(1)
        return fluidsynth