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

AMC PeakPulse access peers created via `create_amc_peers.py` (WireGuard enabled on firewall).

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
- Phone: QR from the same conf
- Endpoint is Airtel `125.19.224.18:51820`. If that WAN is down, edit Endpoint to `47.247.169.94:51820`.

AllowedIPs `10.80.0.0/16` = split tunnel (admin access to all VLANs, matches FortiGate policy 4). For full tunnel, set `AllowedIPs = 0.0.0.0/0`.

## Rotate

If this folder is copied or committed anywhere public, regenerate all keypairs on OPNsense and re-issue client confs.
