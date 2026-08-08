import sys

from PySide6.QtWidgets import QApplication
from view.main_window import MainWindow
from controller.main_controller import MainController


def main():
    app = QApplication(sys.argv)

    # Initialize Controller
    controller = MainController()

    # Initialize View
    view = MainWindow(controller)

    #Currently configuration is loaded with horizontal settings

    # Connect Controller to View
    controller.set_view(view)

    # Add clean exit
    app.aboutToQuit.connect(controller.dispose)

    view.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()