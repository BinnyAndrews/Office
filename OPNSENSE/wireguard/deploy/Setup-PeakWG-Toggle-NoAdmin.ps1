#Requires -RunAsAdministrator
# One-time setup so PeakWG-Toggle.exe works WITHOUT UAC prompts.
# Enables WireGuard LimitedOperatorUI, adds user to Network Configuration Operators,
# grants service start/stop, and creates SYSTEM scheduled tasks the user can run.

param(
    [string]$TunnelName = 'binny.andrews',
    [string]$UserSam = $env:USERNAME
)

$ErrorActionPreference = 'Stop'
$svcName = "WireGuardTunnel`$$TunnelName"
$taskOn = 'PEAK-WG-On'
$taskOff = 'PEAK-WG-Off'

Write-Host "=== PeakWG no-admin toggle setup ===" -ForegroundColor Cyan
Write-Host "Tunnel: $TunnelName"
Write-Host "User:   $UserSam"
Write-Host ""

# 1) WireGuard Limited Operator UI (official non-admin toggle support)
Write-Host "[1] LimitedOperatorUI registry..."
New-Item -Path 'HKLM:\Software\WireGuard' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\Software\WireGuard' -Name 'LimitedOperatorUI' -PropertyType DWord -Value 1 -Force | Out-Null
Write-Host "    OK" -ForegroundColor Green

# 2) Network Configuration Operators
Write-Host "[2] Add $UserSam to 'Network Configuration Operators'..."
$nco = 'Network Configuration Operators'
try {
    Add-LocalGroupMember -Group $nco -Member $UserSam -ErrorAction Stop
    Write-Host "    Added." -ForegroundColor Green
} catch {
    if ($_.Exception.Message -match 'already a member') {
        Write-Host "    Already a member." -ForegroundColor Green
    } else {
        # AzureAD users: try AzureAD\user or full whoami form
        $candidates = @(
            $UserSam,
            "AzureAD\$UserSam",
            "$env:USERDOMAIN\$UserSam"
        )
        $ok = $false
        foreach ($m in $candidates) {
            try {
                Add-LocalGroupMember -Group $nco -Member $m -ErrorAction Stop
                Write-Host "    Added as $m" -ForegroundColor Green
                $ok = $true
                break
            } catch {
                if ($_.Exception.Message -match 'already a member') {
                    Write-Host "    Already a member ($m)." -ForegroundColor Green
                    $ok = $true
                    break
                }
            }
        }
        if (-not $ok) {
            Write-Host "    WARN: could not add to NCO automatically: $($_.Exception.Message)" -ForegroundColor Yellow
            Write-Host "    Add manually: lusrmgr.msc → Groups → Network Configuration Operators" -ForegroundColor Yellow
        }
    }
}

# 3) Ensure tunnel service exists
$wg = Join-Path $env:ProgramFiles 'WireGuard\wireguard.exe'
$confCandidates = @(
    (Join-Path $PSScriptRoot "..\$TunnelName.conf"),
    (Join-Path $PSScriptRoot "$TunnelName.conf"),
    "C:\DEV\OFFICE\OPNSENSE\wireguard\$TunnelName.conf"
)
if (-not (Get-Service -Name $svcName -ErrorAction SilentlyContinue)) {
    Write-Host "[3] Installing tunnel service..."
    $conf = $confCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $conf) { throw "Conf not found for $TunnelName" }
    & $wg /installtunnelservice (Resolve-Path $conf)
    Start-Sleep -Seconds 2
} else {
    Write-Host "[3] Tunnel service already exists." -ForegroundColor Green
}

# 4) Grant Network Configuration Operators start/stop on the service
# Well-known SID S-1-5-32-556 = Network Configuration Operators
Write-Host "[4] Grant NCO start/stop on $svcName..."
$sd = (sc.exe sdshow $svcName) | Out-String
$sd = $sd.Trim()
$ncoAce = '(A;;LCRPRC;;;S-1-5-32-556)'  # QUERY_STATUS + START + STOP-ish; expand below
# Full useful rights: CC RC RP WP LC SW LO CR DT + start/stop
# SERVICE_QUERY_CONFIG|QUERY_STATUS|ENUMERATE|START|STOP|USER_DEFINED|INTERROGATE
$ace = '(A;;CCLCSWRPWPDTLOCRRC;;;S-1-5-32-556)'
if ($sd -notmatch 'S-1-5-32-556') {
    # Insert ACE after D: or at start of DACL
    if ($sd -match '^D:') {
        $newSd = $sd -replace '^D:', "D:$ace"
    } else {
        $newSd = "D:$ace$sd"
    }
    sc.exe sdset $svcName $newSd | Out-Null
    Write-Host "    ACL updated." -ForegroundColor Green
} else {
    Write-Host "    NCO already in ACL." -ForegroundColor Green
}

# 5) Scheduled tasks (SYSTEM) — reliable fallback, no UAC for schtasks /Run
Write-Host "[5] Creating scheduled tasks $taskOn / $taskOff..."
foreach ($pair in @(
    @{ Name = $taskOn;  Cmd = "net.exe"; Args = "start `"$svcName`"" },
    @{ Name = $taskOff; Cmd = "net.exe"; Args = "stop `"$svcName`"" }
)) {
    Unregister-ScheduledTask -TaskName $pair.Name -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute $pair.Cmd -Argument $pair.Args
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $pair.Name -Action $action -Principal $principal -Settings $settings -Force | Out-Null

    # Allow Users to execute/read the task definition
    $taskPath = Join-Path $env:WINDIR "System32\Tasks\$($pair.Name)"
    if (Test-Path $taskPath) {
        icacls $taskPath /grant '*S-1-5-32-545:(RX)' /grant '*S-1-5-11:(RX)' | Out-Null
    }
    Write-Host "    $($pair.Name) OK" -ForegroundColor Green
}

Write-Host @"

Done.
1. SIGN OUT and sign back in (needed for Network Configuration Operators).
2. Use PeakWG-Toggle.exe — it should NO longer ask for admin password.
3. Rebuild toggle if needed: build-PeakWG-Toggle.cmd

"@ -ForegroundColor Green
