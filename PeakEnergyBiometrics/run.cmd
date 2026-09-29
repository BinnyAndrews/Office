@echo off
REM Hidden collector runner — prefer run-collector.vbs from Task Scheduler.
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"%~dp0venv\Scripts\pythonw.exe" "%~dp0collector.py"
