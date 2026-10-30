@echo off
REM Build LonestarValuator.exe on a Windows PC with Python 3.11+ installed.
cd /d %~dp0
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller LonestarValuator.spec --noconfirm --clean
echo.
echo Done: dist\LonestarValuator.exe
pause
