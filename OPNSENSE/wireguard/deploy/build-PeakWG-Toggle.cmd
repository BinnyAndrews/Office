@echo off
setlocal
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo csc.exe not found. Install .NET Framework 4.x Developer Pack.
  exit /b 1
)

cd /d "%~dp0"
if not exist "PeakEnergyLogo.ico" (
  echo Missing PeakEnergyLogo.ico — copy from PEAK ENERGY BIOMETRICS.
  exit /b 1
)

"%CSC%" /nologo /target:winexe /optimize+ /r:System.ServiceProcess.dll ^
  /win32manifest:app.manifest ^
  /win32icon:PeakEnergyLogo.ico ^
  /out:"PeakEnergyVPN.exe" PeakWG-Toggle.cs
if errorlevel 1 exit /b 1

REM Keep logo beside EXE for the in-window image
copy /Y PeakEnergyLogo.png >nul 2>&1
copy /Y PeakEnergyLogo.ico >nul 2>&1

REM Compat alias
copy /Y PeakEnergyVPN.exe PeakWG-Toggle.exe >nul

echo Built: %~dp0PeakEnergyVPN.exe
echo Branding: Peak Energy VPN + Peak Energy logo (from Biometrics)
endlocal
