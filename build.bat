@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Please run run.bat first to initialize the environment.
    pause
    exit /b 1
)

echo [BUILD] Packaging single-file exe (dist\AudioDuck.exe)...
".venv\Scripts\python.exe" -m pip install -q pyinstaller
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name AudioDuck --icon icon.ico --collect-all customtkinter --add-data "114514;114514" main.py

echo [DONE] Output: dist\AudioDuck.exe
pause
