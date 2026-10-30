"""Lonestar Valuator – entry point.

`LonestarValuator.exe --selftest` (used by the GitHub build) checks that the packaged app can
drive a browser, then exits 0/1 without opening a window.
"""
import sys


def selftest() -> int:
    import tempfile
    from valuator.browser import BrowserService
    channel = sys.argv[sys.argv.index("--selftest") + 1] if len(sys.argv) > sys.argv.index("--selftest") + 1 \
        else "chrome"
    svc = BrowserService(tempfile.mkdtemp(prefix="lsv-selftest-"), channel=channel, headless=True)
    try:
        svc.ensure_started(timeout=120)
        html = svc.get_html("data:text/html,<p id=x>ok</p><script>document.getElementById('x').textContent='js-ok'"
                            "</script>", wait_selector="#x")
        ok = "js-ok" in html
        print(f"selftest: browser={svc.used_channel} js={'ok' if ok else 'FAILED'}")
        return 0 if ok else 1
    except Exception as e:
        print(f"selftest FAILED: {e}")
        return 1
    finally:
        svc.close()


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from valuator import __app_name__
    from valuator.settings import resource_path
    from valuator.ui.main_window import MainWindow
    from valuator.ui.theme import QSS

    if sys.platform == "win32":
        try:  # own taskbar icon instead of python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Lonestar.Valuator")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    icon = resource_path("assets/icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    w = MainWindow()
    w.show()
    code = app.exec()
    # Skip interpreter teardown: background lookups may still be waiting on the network, and
    # destroying their threads during normal shutdown can trigger a Qt abort dialog on Windows.
    import os
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
