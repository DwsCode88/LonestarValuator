"""Lonestar Valuator – entry point."""
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from valuator import __app_name__
from valuator.settings import resource_path
from valuator.ui.main_window import MainWindow


def main():
    if sys.platform == "win32":
        try:  # own taskbar icon instead of python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Lonestar.Valuator")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setStyle("Fusion")
    icon = resource_path("assets/icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
