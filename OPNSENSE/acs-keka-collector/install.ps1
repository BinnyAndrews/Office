# Peak Attendance installer
# - Ensures venv + dependencies
# - Registers minute collector task
# - Registers Start Menu + Desktop + Windows Startup shortcuts
# - Starts the app (in tray)
#
# Run:  powershell -ExecutionPolicy Bypass -File .\install.ps1

param(
    [string]$InstallDir = $PSScriptRoot,
    [string]$CollectorTaskName = "Peak-Attendance-Collector",
    [string]$StartupTaskName = "Peak-Attendance-UI",
    [switch]$NoStartApp
)

$ErrorActionPreference = "Stop"
$InstallDir = (Resolve-Path $InstallDir).Path
Set-Location $InstallDir

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-Venv {
    $py = Get-Command py -ErrorAction SilentlyContinue
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($py) {
        $pyExe = $py.Source
        $pyArgs = @("-3")
    } elseif ($python) {
        $pyExe = $python.Source
        $pyArgs = @()
    } else {
        throw "Python 3 is not installed. Install from python.org (tick Add to PATH), then re-run install.ps1."
    }

    Write-Host "Using $pyExe $($pyArgs -join ' ')"
    if (-not (Test-Path (Join-Path $InstallDir "venv\Scripts\python.exe"))) {
        & $pyExe @pyArgs -m venv (Join-Path $InstallDir "venv")
    }
    & (Join-Path $InstallDir "venv\Scripts\python.exe") -m pip install --upgrade pip
    & (Join-Path $InstallDir "venv\Scripts\python.exe") -m pip install -r (Join-Path $InstallDir "requirements.txt")
}

function Ensure-Appsettings {
    $app = Join-Path $InstallDir "appsettings.json"
    $example = Join-Path $InstallDir "appsettings.example.json"
    if (-not (Test-Path $app)) {
        Copy-Item $example $app
        Write-Host "Created appsettings.json - set SQL/device settings in the app."
    }
}

function Write-RunCmd {
    # Kept for compatibility; scheduled task should use run-collector.vbs (no console).
    $lines = @(
        "@echo off",
        ("cd /d `"{0}`"" -f $InstallDir),
        "set PYTHONUTF8=1",
        "set PYTHONIOENCODING=utf-8",
        ("`"{0}`" `"collector.py`"" -f (Join-Path $InstallDir "venv\Scripts\pythonw.exe"))
    )
    Set-Content -Path (Join-Path $InstallDir "run.cmd") -Value ($lines -join "`r`n") -Encoding ASCII
}

function Register-CollectorTask {
    Write-RunCmd
    $vbs = Join-Path $InstallDir "run-collector.vbs"
    $tr = "wscript.exe //B //Nologo `"$vbs`""
    # Remove old noisy task names if present
    schtasks /Delete /TN "Peak-ACS-Keka-Collector" /F 2>$null | Out-Null
    if (Test-IsAdmin) {
        schtasks /Create /TN $CollectorTaskName /SC MINUTE /MO 1 /RU SYSTEM /RL HIGHEST /F /TR $tr | Out-Null
        Write-Host "Registered collector task '$CollectorTaskName' (every 1 minute, SYSTEM, hidden)."
    } else {
        schtasks /Create /TN $CollectorTaskName /SC MINUTE /MO 1 /F /TR $tr | Out-Null
        Write-Host "Registered collector task '$CollectorTaskName' (every 1 minute, current user, hidden)."
        Write-Host "Tip: re-run install.ps1 as Administrator for SYSTEM-level collector."
    }
}

function New-Shortcut {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [string]$TargetPath,
        [string]$Arguments = "",
        [string]$WorkingDirectory = $InstallDir,
        [string]$Description = "Peak Attendance"
    )
    $dir = Split-Path $Path -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $w = New-Object -ComObject WScript.Shell
    $s = $w.CreateShortcut($Path)
    $s.TargetPath = $TargetPath
    $s.Arguments = $Arguments
    $s.WorkingDirectory = $WorkingDirectory
    $s.Description = $Description
    $s.WindowStyle = 7
    $s.Save()
}

function Register-UiStartup {
    $vbs = Join-Path $InstallDir "start-ui.vbs"
    if (-not (Test-Path $vbs)) {
        throw "Missing start-ui.vbs"
    }

    $startup = [Environment]::GetFolderPath("Startup")
    New-Shortcut -Path (Join-Path $startup "Peak Attendance.lnk") -TargetPath "wscript.exe" -Arguments ("`"{0}`"" -f $vbs)

    $tr = "wscript.exe `"$vbs`""
    schtasks /Create /TN $StartupTaskName /SC ONLOGON /RL LIMITED /F /TR $tr | Out-Null
    Write-Host "Registered Windows startup: $StartupTaskName + Startup folder shortcut."
}

function Register-Shortcuts {
    $vbs = Join-Path $InstallDir "start-ui.vbs"
    $startMenu = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\Peak Attendance"
    New-Shortcut -Path (Join-Path $startMenu "Peak Attendance.lnk") -TargetPath "wscript.exe" -Arguments ("`"{0}`"" -f $vbs)
    $desktop = [Environment]::GetFolderPath("Desktop")
    New-Shortcut -Path (Join-Path $desktop "Peak Attendance.lnk") -TargetPath "wscript.exe" -Arguments ("`"{0}`"" -f $vbs)
    Write-Host "Created Start Menu and Desktop shortcuts."
}

function Start-App {
    $vbs = Join-Path $InstallDir "start-ui.vbs"
    Start-Process -FilePath "wscript.exe" -ArgumentList ("`"{0}`"" -f $vbs)
    Write-Host "Started Peak Attendance (tray)."
}

Write-Host "=== Peak Attendance install ==="
Write-Host "InstallDir: $InstallDir"
Ensure-Venv
Ensure-Appsettings
Register-CollectorTask
Register-UiStartup
Register-Shortcuts

try {
    schtasks /Run /TN $CollectorTaskName | Out-Null
} catch {
}

if (-not $NoStartApp) {
    Start-App
}

Write-Host ""
Write-Host "Install complete."
Write-Host "  - App starts with Windows (logon, in tray)"
Write-Host "  - Collector runs every 1 minute"
Write-Host "  - Shortcuts: Desktop + Start Menu"
