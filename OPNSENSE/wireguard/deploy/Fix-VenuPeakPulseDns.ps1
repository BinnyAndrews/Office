#Requires -RunAsAdministrator
# PeakPulse over VPN when Unbound DNS from WG fails: hosts + NRPT + WG DNS=10.80.200.1

$ErrorActionPreference = 'Stop'
$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$entry = '10.80.100.54 peakpulse-dev.peakenergy.asia'
$confCandidates = [System.Collections.Generic.List[string]]@(
    'C:\ProgramData\PeakEnergyVPN\venu.gopal.reddy.conf'
    'C:\ProgramData\PeakEnergyVPN\tunnel.conf'
    'C:\venu.gopal.reddy.conf'
)
if ($PSScriptRoot) {
    $confCandidates.Add((Join-Path $PSScriptRoot 'venu.gopal.reddy.conf'))
    $parent = Split-Path $PSScriptRoot -Parent
    if ($parent) {
        $confCandidates.Add((Join-Path $parent 'venu.gopal.reddy.conf'))
    }
}
$wgExe = Join-Path ${env:ProgramFiles} 'WireGuard\wireguard.exe'
$tunnel = 'venu.gopal.reddy'

# 1) Hosts (works even if DNS is broken; ping to .54 already works)
$raw = Get-Content $hostsPath -Raw -ErrorAction SilentlyContinue
if ($raw -notmatch '(?m)^\s*10\.80\.100\.54\s+peakpulse-dev\.peakenergy\.asia\s*$') {
    Add-Content -Path $hostsPath -Value "`r`n$entry" -Encoding ascii
    Write-Host "Added hosts: $entry"
} else {
    Write-Host "Hosts already has peakpulse-dev"
}

# 2) NRPT for corp domain via Unbound
Get-DnsClientNrptRule -ErrorAction SilentlyContinue |
    Where-Object { $_.Namespace -eq '.peakenergy.asia' -or $_.Namespace -eq 'peakenergy.asia' } |
    ForEach-Object { Remove-DnsClientNrptRule -Name $_.Name -Force -ErrorAction SilentlyContinue }
Add-DnsClientNrptRule -Namespace '.peakenergy.asia' -NameServers @('10.80.200.1', '10.80.100.1') -DisplayName 'PeakEnergy-WG'
Write-Host 'NRPT: .peakenergy.asia -> 10.80.200.1, 10.80.100.1'

# 3) Prefer Unbound on WG interface IP in tunnel conf
$conf = $confCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($conf -and (Test-Path $wgExe)) {
    $content = Get-Content $conf -Raw
    if ($content -notmatch '(?m)^DNS\s*=\s*10\.80\.200\.1\s*$') {
        if ($content -match '(?m)^DNS\s*=') {
            $content = $content -replace '(?m)^DNS\s*=\s*.*$', 'DNS = 10.80.200.1'
        } else {
            $content = $content -replace '(?m)^(Address\s*=\s*.*)$', "`$1`r`nDNS = 10.80.200.1"
        }
        Set-Content -Path $conf -Value $content.TrimEnd() -Encoding ascii
        Add-Content -Path $conf -Value ''
        Write-Host "Updated DNS in $conf"
    }
    & $wgExe /uninstalltunnelservice $tunnel 2>$null
    Start-Sleep -Seconds 2
    & $wgExe /installtunnelservice $conf
    sc.exe config "WireGuardTunnel`$$tunnel" start= delayed-auto | Out-Null
    Start-Service "WireGuardTunnel`$$tunnel" -ErrorAction SilentlyContinue
    Write-Host "Reinstalled tunnel service from $conf"
} else {
    Write-Host "Skip tunnel reinstall (conf or wireguard.exe missing). Hosts+NRPT still applied."
}

Clear-DnsClientCache
Write-Host ''
Write-Host 'Test with VPN ON:'
Write-Host '  ping 10.80.100.54'
Write-Host '  nslookup peakpulse-dev.peakenergy.asia 10.80.200.1'
Write-Host '  https://peakpulse-dev.peakenergy.asia/'
