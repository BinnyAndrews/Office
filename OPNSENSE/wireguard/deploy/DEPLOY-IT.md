# PEAK-WG — MSI + conf push (non-admin users)

Official WireGuard MSI does **not** embed configs. Push **MSI + per-user `.conf` + install script** as SYSTEM/admin. After that, the tunnel runs as a Windows service — end users do **not** need Builtin Administrators.

Docs: [WireGuard enterprise.md](https://github.com/WireGuard/wireguard-windows/blob/master/docs/enterprise.md)

## Package layout

**Preferred — one Peak Energy VPN EXE for all users**

```text
deploy/
  PeakEnergyVPN.exe
  PeakEnergyLogo.png / .ico
  Install-PeakEnergyVPN.ps1
  wireguard-amd64.msi          # optional
+ per user only:
  venu.gopal.reddy.conf        # (or jagadeshwar.conf / …)
```

```powershell
# Admin once on that PC — same installer, different conf
.\Install-PeakEnergyVPN.ps1 -ConfPath .\venu.gopal.reddy.conf
```

The EXE auto-detects the peer from the installed tunnel service and/or Windows username.

**Legacy — MSI pack per person**

```text
PeakWG-Jagadeshwar/
  wireguard-amd64.msi
  jagadeshwar.conf
  Install-PeakWG.ps1
```

Same for `venu.gopal.reddy` and `poovarasu` (their own `.conf` only).

## Silent commands (run as SYSTEM / admin)

```powershell
msiexec /i wireguard-amd64.msi /qn DO_NOT_LAUNCH=1

powershell.exe -ExecutionPolicy Bypass -File .\Install-PeakWG.ps1 `
  -ConfPath .\jagadeshwar.conf `
  -LimitedUi
```

Or without the script:

```powershell
msiexec /i wireguard-amd64.msi /qn DO_NOT_LAUNCH=1

& "C:\Program Files\WireGuard\wireguard.exe" /installtunnelservice C:\Path\jagadeshwar.conf
sc.exe config WireGuardTunnel$jagadeshwar start= delayed-auto
sc.exe start WireGuardTunnel$jagadeshwar
```

## Intune / SCCM / GPO notes

| Item | Value |
|---|---|
| Context | **System** (required) |
| Detection | service `WireGuardTunnel$jagadeshwar` exists / running |
| Uninstall | `"C:\Program Files\WireGuard\wireguard.exe" /uninstalltunnelservice jagadeshwar` then `msiexec /x wireguard-amd64.msi /qn` |

Create **3 separate apps** (one conf each). Do not ship all three confs to every PC.

## Optional: let user toggle On/Off in UI

After install:

```powershell
reg add HKLM\Software\WireGuard /v LimitedOperatorUI /t REG_DWORD /d 1 /f
net localgroup "Network Configuration Operators" "DOMAIN\username" /add
```

User can start/stop tunnels; they still cannot edit keys.  
If you want always-on VPN, skip Limited UI — leave service **Automatic (Delayed Start)** only.

## After connect (user test)

1. Tunnel service Running  
2. Open `https://10.80.100.54` or PeakPulse URL  
3. Peak Pulse app login as usual  

Endpoint in conf: `125.19.224.18:51820` (Airtel). Alternate: `47.247.169.94:51820` (Jio).
