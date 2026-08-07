from PySide6.QtWidgets import QWidget, QFrame

class PianoKey(QFrame):
    def __init__(self, midi_note, is_black, parent=None):
        super().__init__(parent)
        self.midi_note = midi_note
        self.is_black = is_black
        self.default_color = "#333" if is_black else "white"
        self.highlight_color = "#2ecc71"  # Green highlight

        self.set_style(self.default_color)

        # Add a border to see white keys clearly
        if not is_black:
            self.setFrameStyle(QFrame.Panel | QFrame.Plain)
            self.setLineWidth(1)

    def set_style(self, color):
        border = "1px solid #888" if not self.is_black else "none"
        self.setStyleSheet(f"background-color: {color}; border: {border}; border-radius: 2px;")

    def press(self):
        self.set_style(self.highlight_color)

    def release(self):
        self.set_style(self.default_color)


class PianoLayoutWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.keys = {}  # Dictionary to store MIDI_ID: PianoKey Object
        self.white_keys = []

        # Standard 88-key piano: A0 (21) to C8 (108)
        self.start_note = 21
        self.end_note = 108

        self.init_ui()

    def init_ui(self):
        # Configuration
        w_width, w_height = 20, 120  # White key dimensions
        b_width, b_height = 12, 75  # Black key dimensions

        # 1. Create the Lanes Area
        self.lane_container = QWidget(self)
        self.lane_container.setStyleSheet("background-color: #1a1a1a; border-bottom: 2px solid #555;")

        # 2. Create the Piano Keys
        self.keyboard_container = QWidget(self)

        current_x = 0
        black_keys_to_add = []

        for note in range(self.start_note, self.end_note + 1):
            note_in_octave = note % 12
            is_black = note_in_octave in [1, 3, 6, 8, 10]

            if not is_black:
                key = PianoKey(note, False, self.keyboard_container)
                key.setGeometry(current_x, 0, w_width, w_height)
                self.keys[note] = key
                self.white_keys.append(key)
                current_x += w_width
            else:
                # Store black keys to add them LATER (so they are drawn on top)
                # Position is current_x minus half the black key width
                black_keys_to_add.append((note, current_x - (b_width // 2)))

        # Add black keys on top
        for note, x_pos in black_keys_to_add:
            key = PianoKey(note, True, self.keyboard_container)
            key.setGeometry(x_pos, 0, b_width, b_height)
            key.raise_()  # Ensure it's on top
            self.keys[note] = key

        # Set widget size based on total white keys
        self.setFixedSize(current_x, 400)  # 400 height = Lanes + Keyboard

        # Position containers
        self.lane_container.setGeometry(0, 0, current_x, 280)  # Top area
        self.keyboard_container.setGeometry(0, 280, current_x, w_height)  # Bottom area

        # Draw visual separators (lanes) for each white key
        for i in range(0, current_x, w_width):
            line = QFrame(self.lane_container)
            line.setGeometry(i, 0, 1, 280)
            line.setStyleSheet("background-color: #222;")

    def handle_note_on(self, note):
        if note in self.keys:
            self.keys[note].press()

    def handle_note_off(self, note):
        if note in self.keys:
            self.keys[note].release()