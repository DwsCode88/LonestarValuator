# PyInstaller spec – build with:  pyinstaller LonestarValuator.spec
from pathlib import Path

datas = [("assets/icon.ico", "assets"), ("assets/icon.png", "assets")]
if Path("assets/logo.png").exists():
    datas.append(("assets/logo.png", "assets"))

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["reportlab.graphics.barcode.common", "reportlab.graphics.barcode.code128"],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="LonestarValuator",
    icon="assets/icon.ico",
    console=False,
    upx=False,
)
