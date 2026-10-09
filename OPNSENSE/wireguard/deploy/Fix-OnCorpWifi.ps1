#Requires -RunAsAdministrator
# Use when back on PETCPL / corp Wi-Fi (10.80.101.x or 10.80.100.x).
# WireGuard split tunnel (10.80.0.0/16) hijacks local corp traffic into a tunnel
# that often fails after hotspot — turn WG off on-site; use WG only when remote.

$ErrorActionPreference = 'Stop'
$tunnel = 'binny.andrews'
$svc = "WireGuardTunnel`$$tunnel"
$wgExe = "${env:ProgramFiles}\WireGuard\wireguard.exe"

$wifi = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.InterfaceAlias -eq 'Wi-Fi' -and $_.IPAddress -match '^10\.80\.(100|101)\.' } |
  Select-Object -First 1

if (-not $wifi) {
  Write-Host 'Wi-Fi is not on corp VLAN (10.80.100.x / 10.80.101.x). This script is for in-office PETCPL.' -ForegroundColor Yellow
  Write-Host 'If you are remote, activate WireGuard instead.' -ForegroundColor Yellow
  exit 1
}

Write-Host "Corp Wi-Fi detected: $($wifi.IPAddress)" -ForegroundColor Cyan

# Stale Ethernet DNS/routes confuse Windows after unplugging cable
if (Get-NetAdapter -Name 'Ethernet' -ErrorAction SilentlyContinue) {
  Disable-NetAdapter -Name 'Ethernet' -Confirm:$false
  Write-Host 'Disabled disconnected Ethernet adapter.' -ForegroundColor Green
}

if (Get-Service $svc -ErrorAction SilentlyContinue) {
  Stop-Service $svc -Force
  Write-Host "Stopped $svc (WireGuard off for local corp access)." -ForegroundColor Green
}

Clear-DnsClientCache

Write-Host "`nQuick tests (direct via Wi-Fi):" -ForegroundColor Cyan
foreach ($target in @('10.80.101.1', '10.80.99.1', '10.80.100.54')) {
  $r = Test-Connection -TargetName $target -Count 1 -Quiet -ErrorAction SilentlyContinue
  Write-Host "  ping $target : $(if ($r) { 'OK' } else { 'FAIL' })"
}

Write-Host @"

Done.
- In office: keep WireGuard **deactivated**; use firewall https://10.80.99.1:4444/ and RDP directly.
- Remote (hotspot/home): activate WireGuard again.

To re-enable tunnel later (remote):
  & `"$wgExe`" /installtunnelservice `"$(Join-Path (Split-Path $PSScriptRoot -Parent) "$tunnel.conf")`"
  Start-Service $svc

"@ -ForegroundColor Green
