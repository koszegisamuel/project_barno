from PySide6.QtCore import QThread, QObject

from model.midi import MidiWorker


class MainController(QObject):
    def __init__(self):
        super().__init__()
        self.view = None
        self.midi_thread = None
        self.worker = None

    def set_view(self, view):
        self.view = view

    def start_midi_engine(self):
        if self.worker and self.worker.is_alive():
            print("Midi engine already running")
            return

        # Create a thread
        self.midi_thread = QThread()
        # Create worker
        self.worker = MidiWorker()
        # Move worker to thread
        self.worker.moveToThread(self.midi_thread)

        # Connect signals
        self.midi_thread.started.connect(self.worker.start_logic)
        self.worker.note_detected.connect(self.view.update_note_display)
        self.worker.error_occurred.connect(self.view.show_error)

        # Set high priority for MIDI timing
        self.midi_thread.start(QThread.Priority.TimeCriticalPriority)

        self.view.set_loading_state(True)

    def dispose(self):
        """Clean shutdown of threads."""
        if self.worker:
            self.worker.stop()
        if self.midi_thread:
            self.midi_thread.quit()
            self.midi_thread.wait()  # Wait for thread to actually finish