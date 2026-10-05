@echo off
cd /d "%~dp0"
echo Installing PyInstaller...
".\venv\Scripts\python.exe" -m pip install -q pyinstaller
echo Building PeakEnergyDashboard.exe (one-file)...
".\venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean PeakEnergyDashboard.spec
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)
echo.
echo Output: %~dp0dist\PeakEnergyDashboard.exe
dir "%~dp0dist\PeakEnergyDashboard.exe"
