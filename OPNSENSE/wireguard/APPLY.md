# WireGuard — apply separately (do not full-restore)

File: `wireguard-peak-admin.xml`  
**Not** a full OPNsense backup. Do **not** upload it under System → Backups → Restore.

## When

Only after the firewall boots cleanly and base LAN/WAN (or `config-PEAK-CORP-FW-new.xml`) is stable. Add WireGuard **last**.

## GUI steps (recommended)

### 1. VPN → WireGuard → Local
| Field | Value |
| --- | --- |
| Enabled | yes |
| Name | `PEAK-WG` |
| Listen port | `51820` |
| Tunnel address | `10.80.200.1/28` |
| Disable routes | yes |
| DNS | `10.80.200.1` |
| Keys | paste from `server.private.key` / `server.public.key` (or use Generate) |

### 2. VPN → WireGuard → Endpoints (peers)
| Name | Public key | Tunnel address | Keepalive |
| --- | --- | --- | --- |
| binny.andrews | `binny.andrews.public.key` | `10.80.200.2/32` | 25 |
| admin | `admin.public.key` | `10.80.200.3/32` | 25 |

Attach both peers to instance `PEAK-WG`. Enable WireGuard → Apply.

### 3. Interfaces → Assignments
Assign `wg0` → e.g. **opt6**, description `WIREGUARD`, enable (no extra IPv4 needed if tunnel address is on the instance).

### 4. Firewall
- **wan** + **opt1**: pass UDP **51820** in  
- **opt6**: pass `10.80.200.0/28` → `10.80.0.0/16` and → This Firewall  

### 5. System → Settings → Administration
Add **opt6** to GUI/SSH listen interfaces (keep lan/opt2). **Never** expose GUI on WAN.

### 6. Client
Import `binny.andrews.conf` or `admin.conf` → Activate → open `https://10.80.99.1:4444`

## Files
| File | Purpose |
| --- | --- |
| `wireguard-peak-admin.xml` | Reference XML (this pack) |
| `binny.andrews.conf` / `admin.conf` | Client tunnels |
| `*.public.key` / `server.private.key` | Keys for GUI paste |
