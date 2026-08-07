import PySide6
from PySide6.QtWidgets import QMainWindow, QScrollArea, QVBoxLayout, QWidget, QPushButton, QMessageBox

from src.view.piano_layout import PianoLayoutWidget


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Barno")
        self.resize(1060, 400)

        self._build_ui()

    def _build_ui(self):
        # Main Layout
        self.central_widget = QWidget()
        self.main_layout = QVBoxLayout(self.central_widget)

        # 1. Top Controls Area
        self.load_button = QPushButton("Load MIDI Engine")
        self.load_button.clicked.connect(self.controller.start_midi_engine)
        self.main_layout.addWidget(self.load_button)

        # 2. Piano Area with Scroll
        self.scroll = QScrollArea()
        self.piano_widget = PianoLayoutWidget()
        self.scroll.setWidget(self.piano_widget)
        self.scroll.setFixedHeight(420)  # Match piano + lanes height
        self.scroll.setHorizontalScrollBarPolicy(PySide6.QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        self.main_layout.addWidget(self.scroll)
        self.setCentralWidget(self.central_widget)

    def update_note_display(self, text):
        self.statusBar().showMessage(text)

    def set_loading_state(self, is_loading):
        self.load_button.setEnabled(not is_loading)
        self.load_button.setText("Engine Running..." if is_loading else "Load MIDI Engine")

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)