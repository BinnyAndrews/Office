#Requires -RunAsAdministrator
<#
.SYNOPSIS
  One-time admin step so Peak Energy VPN can turn the tunnel on and off
  without a UAC prompt.

.DESCRIPTION
  Grants Interactive Users start/stop on each WireGuardTunnel$* service.
  Tunnel configuration stays restricted to SYSTEM and Administrators.
  Also sets WireGuard LimitedOperatorUI.

  Run again after a tunnel is reinstalled; /installtunnelservice resets
  the service permissions.
#>
$ErrorActionPreference = "Stop"

reg add "HKLM\Software\WireGuard" /v LimitedOperatorUI /t REG_DWORD /d 1 /f | Out-Null

# Default WireGuard DACL, plus start (RP), stop (WP), and pause (DT) for
# interactive users. Query rights they already had stay in place.
$sddl = "D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWRPWPDTLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)"

$services = @(Get-Service -Name "WireGuardTunnel$*" -ErrorAction SilentlyContinue)
if ($services.Count -eq 0) {
    throw "No WireGuardTunnel$* service found. Install the tunnel first."
}

foreach ($svc in $services) {
    & sc.exe sdset $svc.Name $sddl | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "sdset failed for $($svc.Name) exit $LASTEXITCODE"
    }
    Write-Host "Toggle allowed for interactive users: $($svc.Name)"
}

Write-Host "Done. Peak Energy VPN can Turn ON / Turn OFF without an admin password."
