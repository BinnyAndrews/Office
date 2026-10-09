#Requires -RunAsAdministrator
<#
.SYNOPSIS
  One installer for all PCs — Peak Energy VPN app + WireGuard peer + no-UAC toggle.

.PARAMETER ConfPath
  Path to this user's WireGuard .conf (e.g. venu.gopal.reddy.conf). Required unless
  a WireGuardTunnel$* service already exists.

.PARAMETER PeerName
  Optional peer slug. Default: filename of ConfPath, or auto from Windows user.

.EXAMPLE
  .\Install-PeakEnergyVPN.ps1 -ConfPath .\venu.gopal.reddy.conf
#>
param(
    [string]$ConfPath,
    [string]$PeerName
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$installDir = Join-Path $env:ProgramFiles 'Peak Energy VPN'
$dataDir = Join-Path $env:ProgramData 'PeakEnergyVPN'
$wgExe = Join-Path $env:ProgramFiles 'WireGuard\wireguard.exe'

Write-Host "=== Peak Energy VPN — machine install ===" -ForegroundColor Cyan

# Resolve conf / peer
if ($ConfPath) {
    $ConfPath = (Resolve-Path $ConfPath).Path
    if (-not $PeerName) { $PeerName = [IO.Path]::GetFileNameWithoutExtension($ConfPath) }
} else {
    # Prefer conf already in ProgramData or deploy folder matching a known peer
    $candidates = @()
    foreach ($d in @($dataDir, $here, (Join-Path $here '..'))) {
        if (Test-Path $d) {
            $candidates += Get-ChildItem $d -Filter '*.conf' -ErrorAction SilentlyContinue
        }
    }
    if ($candidates.Count -eq 1) {
        $ConfPath = $candidates[0].FullName
        $PeerName = $candidates[0].BaseName
    }
}

if (-not $PeerName) {
    # Map Windows user → peer (same aliases as EXE)
    # Normalize AzureAD / UPN logins (Venugopal.reddy@peakenergy.asia → venugopalreddy)
    $raw = $env:USERNAME
    try { $raw = (whoami) } catch { }
    $u = ($raw -replace '.*\\', '' -replace '@.*', '' -replace '[^a-zA-Z0-9]', '').ToLowerInvariant()
    $map = @{
        'binnyandrews' = 'binny.andrews'; 'binny' = 'binny.andrews'
        'jagadeshwar' = 'jagadeshwar'; 'jagadeeshwar' = 'jagadeshwar'
        'venugopalreddy' = 'venu.gopal.reddy'; 'venugopal' = 'venu.gopal.reddy'
        'venu' = 'venu.gopal.reddy'; 'gopal' = 'venu.gopal.reddy'
        'poovarasumanickam' = 'poovarasu'; 'poovarasu' = 'poovarasu'; 'manickam' = 'poovarasu'
        'sj' = 'sanoj.james'; 'sanojjames' = 'sanoj.james'; 'sanoj' = 'sanoj.james'
        'admin' = 'admin'; 'lusrpeakadmin' = 'admin'
    }
    if ($map.ContainsKey($u)) { $PeerName = $map[$u] }
}

if (-not $PeerName) {
    throw "Could not detect peer. Pass -ConfPath path\to\user.conf"
}

$svc = "WireGuardTunnel`$$PeerName"
Write-Host "Peer: $PeerName"
Write-Host "Service: $svc"

# 1) WireGuard MSI note
if (-not (Test-Path $wgExe)) {
    Write-Host "WireGuard not installed. Looking for MSI beside installer..." -ForegroundColor Yellow
    $msi = Get-ChildItem $here, (Join-Path $here '..') -Filter 'wireguard-amd64.msi' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($msi) {
        Start-Process msiexec.exe -ArgumentList "/i `"$($msi.FullName)`" /qn DO_NOT_LAUNCH=1" -Wait -Verb RunAs
    } else {
        throw "Install WireGuard first: https://www.wireguard.com/install/"
    }
}

# 2) App files
New-Item -ItemType Directory -Force -Path $installDir, $dataDir | Out-Null
Copy-Item -Force (Join-Path $here 'PeakEnergyVPN.exe') (Join-Path $installDir 'PeakEnergyVPN.exe')
foreach ($f in @('PeakEnergyLogo.png', 'PeakEnergyLogo.ico')) {
    $src = Join-Path $here $f
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $installDir $f)
        Copy-Item -Force $src (Join-Path $dataDir $f)
    }
}

# 3) Peer conf into ProgramData (all machines use same layout)
if ($ConfPath -and (Test-Path $ConfPath)) {
    Copy-Item -Force $ConfPath (Join-Path $dataDir "$PeerName.conf")
    Write-Host "Conf → $dataDir\$PeerName.conf" -ForegroundColor Green
}

# 4) Tunnel service
if (-not (Get-Service -Name $svc -ErrorAction SilentlyContinue)) {
    $confInstall = Join-Path $dataDir "$PeerName.conf"
    if (-not (Test-Path $confInstall)) { throw "Missing $confInstall" }
    & $wgExe /installtunnelservice $confInstall
    Start-Sleep -Seconds 2
}
sc.exe config $svc start= delayed-auto | Out-Null
Write-Host "Tunnel service ready." -ForegroundColor Green

# 5) LimitedOperatorUI + NCO for logged-on user
New-Item -Path 'HKLM:\Software\WireGuard' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\Software\WireGuard' -Name 'LimitedOperatorUI' -PropertyType DWord -Value 1 -Force | Out-Null
foreach ($m in @((whoami), $env:USERNAME, "AzureAD\$env:USERNAME")) {
    try {
        Add-LocalGroupMember -Group 'Network Configuration Operators' -Member $m -ErrorAction Stop
        Write-Host "NCO: $m" -ForegroundColor Green
        break
    } catch {
        if ("$($_.Exception.Message)" -match 'already') { Write-Host "NCO already: $m"; break }
    }
}

# 6) Grant Interactive Users start/stop on THIS tunnel (and any other WG tunnels)
$iuAce = '(A;;CCLCSWRPWPDTLOCRRC;;;IU)'
Get-Service 'WireGuardTunnel$*' -ErrorAction SilentlyContinue | ForEach-Object {
    $name = $_.Name
    $sd = ((sc.exe sdshow $name) | Out-String).Trim()
    $sd2 = [regex]::Replace($sd, '\(A;;[^)]*;;;IU\)', '')
    if ($sd2 -match '^D:') { $sd2 = $sd2 -replace '^D:', "D:$iuAce" } else { $sd2 = "D:$iuAce$sd2" }
    sc.exe sdset $name $sd2 | Out-Null
    Write-Host "ACL OK: $name" -ForegroundColor Green
}

# 7) Shortcuts
$exe = Join-Path $installDir 'PeakEnergyVPN.exe'
$wsh = New-Object -ComObject WScript.Shell
foreach ($loc in @(
    (Join-Path ([Environment]::GetFolderPath('CommonDesktopDirectory')) 'Peak Energy VPN.lnk'),
    (Join-Path ([Environment]::GetFolderPath('CommonStartMenu')) 'Programs\Peak Energy VPN.lnk')
)) {
    try {
        $dir = Split-Path $loc
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $sc = $wsh.CreateShortcut($loc)
        $sc.TargetPath = $exe
        $sc.WorkingDirectory = $installDir
        $sc.IconLocation = (Join-Path $installDir 'PeakEnergyLogo.ico')
        $sc.Description = 'Peak Energy VPN — ON at home/hotspot, OFF on PETCPL'
        $sc.Save()
        Write-Host "Shortcut: $loc" -ForegroundColor Green
    } catch {
        Write-Host "Shortcut skip: $loc — $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host @"

Done.
- App: $installDir\PeakEnergyVPN.exe
- Peer auto-detect: Windows user → $PeerName (or sole WireGuardTunnel`$ service)
- Conf store: $dataDir
- User: OFF on PETCPL / ON when remote

Sign out/in only if Network Configuration Operators was just added and toggle still access-denied.

"@ -ForegroundColor Green
