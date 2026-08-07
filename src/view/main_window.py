from PySide6.QtWidgets import QMainWindow, QPushButton, QVBoxLayout, QWidget, QLineEdit, QLabel, QMessageBox

class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Piano Practicing App")
        self.resize(400, 200)

        self._build_ui()

    def _build_ui(self):
        self.central_widget = QWidget()
        self.layout = QVBoxLayout(self.central_widget)

        self.note_display = QLineEdit()
        self.note_display.setReadOnly(True)
        self.note_display.setPlaceholderText("Notes will appear here...")

        self.load_button = QPushButton("Load MIDI Engine")
        self.load_button.clicked.connect(self.controller.start_midi_engine)

        self.layout.addWidget(QLabel("Current Input:"))
        self.layout.addWidget(self.note_display)
        self.layout.addWidget(self.load_button)

        self.setCentralWidget(self.central_widget)

    def update_note_display(self, text):
        self.note_display.setText(text)

    def set_loading_state(self, is_loading):
        self.load_button.setEnabled(not is_loading)
        self.load_button.setText("Engine Running..." if is_loading else "Load MIDI Engine")

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)