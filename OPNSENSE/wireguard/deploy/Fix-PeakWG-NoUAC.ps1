#Requires -RunAsAdministrator
# Fix: allow any signed-in user to start/stop PEAK WireGuard WITHOUT admin password.
# Grants Interactive Users start+stop on the tunnel service (takes effect immediately).

param([string]$TunnelName = 'binny.andrews')

$ErrorActionPreference = 'Stop'
$svc = "WireGuardTunnel`$$TunnelName"
$user = whoami

Write-Host "Fixing $svc for no-UAC toggle..." -ForegroundColor Cyan
Write-Host "Current user: $user"

# LimitedOperatorUI
New-Item -Path 'HKLM:\Software\WireGuard' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\Software\WireGuard' -Name 'LimitedOperatorUI' -PropertyType DWord -Value 1 -Force | Out-Null

# Add to Network Configuration Operators (best-effort)
foreach ($m in @($user, $env:USERNAME, "AzureAD\$env:USERNAME")) {
    try {
        Add-LocalGroupMember -Group 'Network Configuration Operators' -Member $m -ErrorAction Stop
        Write-Host "Added to NCO: $m" -ForegroundColor Green
        break
    } catch {
        if ("$($_.Exception.Message)" -match 'already') {
            Write-Host "Already in NCO: $m" -ForegroundColor Green
            break
        }
    }
}

if (-not (Get-Service -Name $svc -ErrorAction SilentlyContinue)) {
    throw "Service $svc not found. Install WireGuard tunnel first."
}

# Replace IU ACE so Interactive Users can START (RP) + STOP (WP)
# Previous IU ACE lacked RP/WP → start/stop failed for normal users.
$sd = ((sc.exe sdshow $svc) | Out-String).Trim()
Write-Host "Old SDDL: $sd"

$iuFull = '(A;;CCLCSWRPWPDTLOCRRC;;;IU)'
# Remove existing IU ACEs then insert full one after D:
$sd2 = [regex]::Replace($sd, '\(A;;[^)]*;;;IU\)', '')
if ($sd2 -match '^D:') {
    $sd2 = $sd2 -replace '^D:', "D:$iuFull"
} else {
    $sd2 = "D:$iuFull$sd2"
}

Write-Host "New SDDL: $sd2"
$r = sc.exe sdset $svc $sd2
Write-Host "sc sdset: $r"

# Recreate runnable tasks (optional fallback)
foreach ($pair in @(
    @{ Name = 'PEAK-WG-On';  Args = "start `"$svc`"" },
    @{ Name = 'PEAK-WG-Off'; Args = "stop `"$svc`"" }
)) {
    Unregister-ScheduledTask -TaskName $pair.Name -Confirm:$false -ErrorAction SilentlyContinue

    $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>net.exe</Command>
      <Arguments>$($pair.Args)</Arguments>
    </Exec>
  </Actions>
</Task>
"@
    Register-ScheduledTask -TaskName $pair.Name -Xml $xml -Force | Out-Null

    # Allow Authenticated Users to read + execute the task
    $taskFile = Join-Path $env:WINDIR "System32\Tasks\$($pair.Name)"
    if (Test-Path $taskFile) {
        icacls $taskFile /grant "*S-1-5-11:(RX)" /grant "*S-1-5-32-545:(RX)" | Out-Null
    }
    Write-Host "Task $($pair.Name) ready" -ForegroundColor Green
}

Write-Host @"

Done — NO sign-out required for the service ACL fix.
1. Close PeakWG-Toggle if open.
2. Use Desktop PeakWG-Toggle.exe → Turn OFF / Turn ON (should NOT ask for password).

If Windows still shows a UAC box on *opening* the EXE, right-click → Properties →
Uncheck 'Run this program as an administrator' on Compatibility tab.

"@ -ForegroundColor Green
