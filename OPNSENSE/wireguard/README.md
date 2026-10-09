# WireGuard peer pack (replaces FortiGate SSL VPN)

Generated for PEAK-CORP-FW migration. Treat `*.private.key` and `*.conf` as secrets.

## Peers (PEAK-WG)

| Peer | Tunnel IP | Client file |
| --- | --- | --- |
| Server (OPNsense wg0) | 10.80.200.1/28 | keys on server + seed XML |
| binny.andrews | 10.80.200.2/32 | `binny.andrews.conf` |
| admin | 10.80.200.3/32 | `admin.conf` |
| Jagadeshwar | 10.80.200.4/32 | `jagadeshwar.conf` |
| Venu Gopal Reddy | 10.80.200.5/32 | `venu.gopal.reddy.conf` |
| Poovarasu | 10.80.200.6/32 | `poovarasu.conf` |
| Sanoj James | 10.80.200.7/32 | `sanoj.james.conf` |

AMC PeakPulse access peers created via `create_amc_peers.py` (WireGuard enabled on firewall). Sanoj added via `add_sanoj_james.py`.

**WG access split**
- `WG_FW_ADMINS` (`binny.andrews` / `admin`): firewall `(self)` + full MGMT `10.80.99.0/24` (OC200, switch, APs)
- All WG peers: `CORP_INTERNAL` only (`10.80.100.0/24` + `10.80.101.0/24` — PeakPulse etc.); no MGMT / no FW GUI
- RDP (TCP 3389): blocked for `WG_NO_RDP` (Venu / Poovarasu / Sanoj). Allowed for binny, admin, Jagadeshwar.

## Install on OPNsense

1. VPN → WireGuard → **Local** instance:
   - Name: `PEAK-WG`
   - Listen port: `51820`
   - Tunnel address: `10.80.200.1/28`
   - Paste `server.private.key` / `server.public.key`
   - Disable routes: yes (use firewall on `opt8`)
2. Add **Endpoints** for binny and admin with their public keys and `/32` tunnel addresses.
3. Assign interface `opt8` to the WireGuard device.
4. Firewall: pass UDP 51820 on wan + opt1; pass from `WG_ADMIN_NET` to `LAN_RFC1918` on opt8.
5. Or run `python build-opnsense-seed.py` after editing `nics.env` and restore/review `peak-seed.xml`.

## Install on clients

- Windows: WireGuard app → Import tunnel(s) from `binny.andrews.conf` / `admin.conf`

**On-site vs remote:** With `AllowedIPs = 10.80.0.0/16`, a **running** tunnel sends all corp IPs through WireGuard. On **PETCPL / corp Wi‑Fi** (`10.80.100.x` or `10.80.101.x`), **deactivate WireGuard** so traffic uses the local LAN. After switching from hotspot, if firewall/RDP/internet break, run elevated `deploy\Fix-OnCorpWifi.ps1` or manually deactivate the tunnel in the WireGuard app.

**Peak Energy VPN (one EXE for all PCs):** `deploy\PeakEnergyVPN.exe`  
Auto-detects peer from (1) installed `WireGuardTunnel$*` service (2) Windows / AzureAD login → peer:

| Login | WireGuard peer |
|---|---|
| `binny.andrews@peakenergy.asia` | `binny.andrews` |
| `jagadeshwar@peakenergy.asia` | `jagadeshwar` |
| `Venugopal.reddy@peakenergy.asia` | `venu.gopal.reddy` |
| `Poovarasu.Manickam@peakenergy.asia` | `poovarasu` |
| `SJ@peakenergy.asia` | `sanoj.james` |

**Machine install (Admin once per PC)** — same EXE everywhere; only the `.conf` differs:
```powershell
cd C:\DEV\OFFICE\OPNSENSE\wireguard\deploy
powershell -ExecutionPolicy Bypass -File .\Install-PeakEnergyVPN.ps1 -ConfPath ..\venu.gopal.reddy.conf
```
Installs app to `Program Files\Peak Energy VPN`, conf to `ProgramData\PeakEnergyVPN`, tunnel service, no-UAC ACL, Desktop shortcut. Rebuild EXE: `build-PeakWG-Toggle.cmd`.
- Phone: QR from the same conf
- Endpoint is Airtel `125.19.224.18:51820`. If that WAN is down, edit Endpoint to `47.247.169.94:51820`.

AllowedIPs `10.80.0.0/16` = split tunnel (admin access to all VLANs, matches FortiGate policy 4). For full tunnel, set `AllowedIPs = 0.0.0.0/0`.

DNS must be `10.80.100.1` (Unbound on WIRED_CORP), not `10.80.200.1` — Unbound does not listen on the WireGuard interface. That makes `peakpulse-dev.peakenergy.asia` resolve to `10.80.100.54` over VPN. Public WAN HTTP/HTTPS to PeakPulse stays disabled; access is WireGuard-only.

To refresh Binny’s installed tunnel after a DNS fix: elevated `deploy\Fix-BinnyWgDns.ps1`.

## Rotate

If this folder is copied or committed anywhere public, regenerate all keypairs on OPNsense and re-issue client confs.
