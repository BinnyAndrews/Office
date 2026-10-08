#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Enterprise install for PEAK-WG WireGuard (non-admin end users).

.DESCRIPTION
  1) Silent-installs WireGuard MSI (if present beside this script)
  2) Registers the tunnel as a Windows service (runs as SYSTEM)
  3) Optionally enables LimitedOperatorUI so Network Configuration Operators
     can start/stop the tunnel without full Administrators membership

.PARAMETER ConfPath
  Path to the user-specific .conf (e.g. jagadeshwar.conf)

.PARAMETER MsiPath
  Optional path to wireguard-amd64.msi. Defaults to same folder as this script.

.PARAMETER LimitedUi
  If set, enables LimitedOperatorUI registry key.

.EXAMPLE
  .\Install-PeakWG.ps1 -ConfPath .\jagadeshwar.conf -LimitedUi
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ConfPath,

    [string]$MsiPath = "",

    [switch]$LimitedUi
)

$ErrorActionPreference = "Stop"
$wgExe = "${env:ProgramFiles}\WireGuard\wireguard.exe"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $MsiPath) {
    $MsiPath = Join-Path $here "wireguard-amd64.msi"
}

$ConfPath = (Resolve-Path $ConfPath).Path
$tunnelName = [System.IO.Path]::GetFileNameWithoutExtension($ConfPath)

Write-Host "Tunnel name: $tunnelName"
Write-Host "Config:      $ConfPath"

# --- 1) MSI ---
if (-not (Test-Path $wgExe)) {
    if (-not (Test-Path $MsiPath)) {
        throw "WireGuard not installed and MSI not found at $MsiPath"
    }
    Write-Host "Installing MSI silently..."
    $p = Start-Process msiexec.exe -ArgumentList "/i `"$MsiPath`" /qn DO_NOT_LAUNCH=1" -Wait -PassThru
    if ($p.ExitCode -ne 0) {
        throw "msiexec failed exit $($p.ExitCode)"
    }
}

if (-not (Test-Path $wgExe)) {
    throw "wireguard.exe missing after install"
}

# --- 2) Tunnel as Windows service ---
# Remove existing service with same name (idempotent re-push)
& $wgExe /uninstalltunnelservice $tunnelName 2>$null | Out-Null

Write-Host "Installing tunnel service..."
& $wgExe /installtunnelservice $ConfPath
if ($LASTEXITCODE -ne 0) {
    throw "installtunnelservice failed exit $LASTEXITCODE"
}

$svc = "WireGuardTunnel`$$tunnelName"
sc.exe config $svc start= delayed-auto | Out-Null
Start-Service -Name $svc -ErrorAction SilentlyContinue

# --- 3) Optional limited UI for non-admins ---
if ($LimitedUi) {
    reg add "HKLM\Software\WireGuard" /v LimitedOperatorUI /t REG_DWORD /d 1 /f | Out-Null
    Write-Host "LimitedOperatorUI enabled."
    Write-Host "IT must also add the user to local group: Network Configuration Operators"
}

Write-Host "Done. Service: $svc"
Get-Service -Name $svc | Format-List Name, Status, StartType
