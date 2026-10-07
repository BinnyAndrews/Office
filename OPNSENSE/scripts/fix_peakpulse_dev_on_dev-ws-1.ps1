# Run on dev-ws-1 (10.80.100.54) in elevated PowerShell after RDP.
# Fixes local browser access to peakpulse-dev.peakenergy.asia when corp DNS/NAT already work.

$ErrorActionPreference = 'Stop'
$hostname = 'peakpulse-dev.peakenergy.asia'
$fwDns = '10.80.100.1'
$lanIp = '10.80.100.54'

Write-Host "=== DNS lookup (default resolver) ===" -ForegroundColor Cyan
Resolve-DnsName $hostname -Type A -ErrorAction SilentlyContinue | Format-Table Name, IPAddress

Write-Host "`n=== DNS lookup (firewall $fwDns) ===" -ForegroundColor Cyan
Resolve-DnsName $hostname -Server $fwDns -Type A | Format-Table Name, IPAddress

Write-Host "`n=== Set IPv4 DNS to $fwDns on active corp adapters ===" -ForegroundColor Cyan
Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -notmatch 'Virtual|Hyper-V|WSL|Loopback|Tailscale|WireGuard' } | ForEach-Object {
    Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses $fwDns
    Write-Host "  $($_.Name) -> $fwDns"
}

Write-Host "`n=== Flush DNS cache ===" -ForegroundColor Cyan
Clear-DnsClientCache

Write-Host "`n=== Hosts entry (LAN IP, not 127.0.0.1 — nginx listens on $lanIp) ===" -ForegroundColor Cyan
$hostsPath = "$env:Windir\System32\drivers\etc\hosts"
$line = "$lanIp`t$hostname"
$hosts = Get-Content $hostsPath -Raw
if ($hosts -notmatch [regex]::Escape($hostname)) {
    Add-Content -Path $hostsPath -Value "`n# PeakPulse local access on dev-ws-1`n$line"
    Write-Host "  Added: $line"
} else {
    Write-Host "  Hosts already contains $hostname"
}

Write-Host "`n=== Allow inbound HTTPS from this subnet (self-access to own LAN IP) ===" -ForegroundColor Cyan
$ruleName = 'PeakPulse HTTPS LAN self'
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 -RemoteAddress LocalSubnet | Out-Null
    Write-Host "  Created firewall rule: $ruleName"
} else {
    Write-Host "  Rule already exists: $ruleName"
}

Write-Host "`n=== Test HTTPS (ignore cert warnings) ===" -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri "https://$hostname/" -MaximumRedirection 0 -SkipCertificateCheck -TimeoutSec 15 -ErrorAction Stop
    Write-Host "  Status: $($r.StatusCode)"
} catch {
    if ($_.Exception.Response.StatusCode.value__) {
        Write-Host "  Status: $($_.Exception.Response.StatusCode.value__) (redirect/login is OK)"
    } else {
        Write-Host "  FAIL: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  If nginx runs in WSL2: use https://localhost:PORT or fix WSL port forwarding."
    }
}

Write-Host "`nDone. Retry in browser (disable Chrome 'Secure DNS' if it still uses Google)." -ForegroundColor Green
