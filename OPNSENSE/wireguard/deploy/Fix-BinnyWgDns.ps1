#Requires -RunAsAdministrator
# Re-points PEAK-WG DNS to Unbound (10.80.100.1) so peakpulse-dev resolves over WireGuard.
# Public PeakPulse WAN access stays disabled — VPN-only.

$ErrorActionPreference = 'Stop'
$confSrc = Join-Path (Split-Path $PSScriptRoot -Parent) 'binny.andrews.conf'
$wgExe = "${env:ProgramFiles}\WireGuard\wireguard.exe"
$tunnel = 'binny.andrews'

if (-not (Test-Path $confSrc)) { throw "Missing $confSrc" }
if (-not (Test-Path $wgExe)) { throw "WireGuard not installed at $wgExe" }

# Ensure source conf uses corp Unbound
$content = Get-Content $confSrc -Raw
if ($content -notmatch '(?m)^DNS\s*=\s*10\.80\.100\.1\s*$') {
    $content = $content -replace '(?m)^DNS\s*=\s*.*$', 'DNS = 10.80.100.1'
    Set-Content -Path $confSrc -Value $content.TrimEnd() -Encoding ascii
    Add-Content -Path $confSrc -Value ''
}

Write-Host "Using conf: $confSrc"
Write-Host (Select-String -Path $confSrc -Pattern '^(Address|DNS|AllowedIPs|Endpoint)')

& $wgExe /uninstalltunnelservice $tunnel 2>$null
Start-Sleep -Seconds 2
& $wgExe /installtunnelservice $confSrc
if ($LASTEXITCODE -ne 0) { throw "installtunnelservice failed: $LASTEXITCODE" }

$svc = "WireGuardTunnel`$$tunnel"
sc.exe config $svc start= delayed-auto | Out-Null
Start-Service $svc
Start-Sleep -Seconds 2

Clear-DnsClientCache
Write-Host "`nDNS on tunnel:"
Get-DnsClientServerAddress -InterfaceAlias $tunnel -AddressFamily IPv4 | Format-Table InterfaceAlias, ServerAddresses

Write-Host "Resolve peakpulse-dev:"
Resolve-DnsName peakpulse-dev.peakenergy.asia -DnsOnly | Format-Table Name, IPAddress

Write-Host "Done. Open https://peakpulse-dev.peakenergy.asia/ (WireGuard only)." -ForegroundColor Green
