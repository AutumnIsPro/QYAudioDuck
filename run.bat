@echo off
title Audio Duck - Audio Auto-Ducking Assistant
cd /d "%~dp0"

rem --- Locate Python ---
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY goto :nopython

rem --- Use existing venv if healthy ---
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul && goto :havevenv
    echo [INFO] Broken virtual environment detected, rebuilding...
    rmdir /s /q .venv
)

rem --- Create venv, or fall back to user install ---
echo [FIRST RUN] Creating virtual environment...
%PY% -m venv .venv >nul 2>nul
if exist ".venv\Scripts\python.exe" goto :havevenv

echo [INFO] venv creation failed, falling back to user install (network required)...
%PY% -m pip install --user -q -r requirements.txt
if errorlevel 1 goto :pipfail
echo [START] Launching application...
%PY% main.py
if errorlevel 1 pause
exit /b 0

:havevenv
echo [CHECK] Installing / updating dependencies...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check --no-cache-dir -r requirements.txt
if errorlevel 1 goto :pipfail
echo [START] Launching application (no console, this window will close)...
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:nopython
echo [ERROR] Python not found. Please install Python 3.9+ and check "Add python.exe to PATH".
pause
exit /b 1

:pipfail
echo [ERROR] Dependency install failed. Check your network and retry.
pause
exit /b 1
