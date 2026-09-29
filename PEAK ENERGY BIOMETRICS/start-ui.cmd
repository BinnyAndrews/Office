@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM Starts in tray only (no console). Use --window to open UI immediately.
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0ui_app.py"
