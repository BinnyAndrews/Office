#Requires -RunAsAdministrator
param(
    [string]$InstallDir = $PSScriptRoot,
    [string]$TaskName = "Peak-ACS-Keka-Collector"
)

$ErrorActionPreference = "Stop"
$InstallDir = (Resolve-Path $InstallDir).Path
Set-Location $InstallDir

$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $pyExe = $py.Source
    $pyArgs = "-3"
} elseif ($python) {
    $pyExe = $python.Source
    $pyArgs = ""
} else {
    throw "Python 3 is not installed. Install python.org 3.11+ (check 'Add python.exe to PATH')."
}

Write-Host "Using $pyExe $pyArgs"
if (-not (Test-Path "$InstallDir\venv\Scripts\python.exe")) {
    if ($pyArgs) {
        & $pyExe $pyArgs -m venv "$InstallDir\venv"
    } else {
        & $pyExe -m venv "$InstallDir\venv"
    }
}

& "$InstallDir\venv\Scripts\python.exe" -m pip install --upgrade pip
& "$InstallDir\venv\Scripts\python.exe" -m pip install -r "$InstallDir\requirements.txt"

if (-not (Test-Path "$InstallDir\config.json")) {
    Copy-Item "$InstallDir\config.example.json" "$InstallDir\config.json"
    Write-Host "Created config.json — edit device and SQL passwords before the first real run."
}

$runCmd = @"
@echo off
cd /d "$InstallDir"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
".\venv\Scripts\python.exe" collector.py
"@
Set-Content -Path "$InstallDir\run.cmd" -Value $runCmd -Encoding ASCII

schtasks /Create /TN $TaskName /SC MINUTE /MO 1 /RU SYSTEM /RL HIGHEST /F /TR "`"$InstallDir\run.cmd`"" | Out-Null

Write-Host ""
Write-Host "Task '$TaskName' registered (every 1 minute, as SYSTEM)."
Write-Host "Next:"
Write-Host "  1. Edit $InstallDir\config.json"
Write-Host "  2. Run:  $InstallDir\venv\Scripts\python.exe collector.py --probe"
Write-Host "  3. Run:  $InstallDir\venv\Scripts\python.exe collector.py --dry-run"
Write-Host "  4. Run:  $InstallDir\venv\Scripts\python.exe collector.py"
