@echo off
cd /d "%~dp0"
echo Installing PyInstaller...
".\venv\Scripts\python.exe" -m pip install -q pyinstaller
echo Building PeakAttendance.exe (one-file)...
".\venv\Scripts\pyinstaller.exe" --noconfirm --clean PeakAttendance.spec
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)
echo.
echo Output: %~dp0dist\PeakAttendance.exe
dir "%~dp0dist\PeakAttendance.exe"
