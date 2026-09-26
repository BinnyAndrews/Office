# SSL VPN → WireGuard

FortiGate SSL VPN:

- Listen: wan1 + wan2, cert `Fortinet_Factory`
- Pool: `10.80.200.1–10` (`SSLVPN_TUNNEL_ADDR1`)
- Portals: `full-access` for groups, default `web-access`
- **PEAK-VPN-ADMIN**: `binny.andrews`, `admin` → all LAN VLANs including ACS/CCTV/guest
- **PEAK-VPN-STAFF**: no members → WIRED-CORP + WL-CORP only

Passwords cannot be exported. Create new credentials on OPNsense.

## Why WireGuard

OPNsense SSL VPN (OpenVPN) can mimic FortiClient, but WireGuard is simpler and is what OPNsense recommends for site/user tunnels. If you must keep FortiClient, use OpenVPN TCP/443 on both WANs.

## OPNsense WireGuard (VPN → WireGuard)

1. Instance `wg0`: tunnel address `10.80.200.1/28`, listen port `51820` (UDP). Add firewall pass on **wan** and **opt1** for UDP 51820.
2. Peers (example):

| Peer | Tunnel IP | Allowed IPs | Matches FortiGate group |
| --- | --- | --- | --- |
| binny.andrews | 10.80.200.2/32 | 10.80.200.2/32 | PEAK-VPN-ADMIN |
| admin | 10.80.200.3/32 | 10.80.200.3/32 | PEAK-VPN-ADMIN |

Assign interface `opt8` to `wg0`. Enable **Disable Routes** if you only policy-route via firewall.

3. Client allowed IPs: `10.80.0.0/16` (or split: `10.80.100.0/24, 10.80.101.0/24, …`).
4. Firewall on `opt8` as in `nat-and-firewall.md` (admin vs staff).
5. DNS: OPNsense `10.80.200.1` or `10.80.100.1`.

OpenVPN alternative: tunnel net `10.80.200.0/24`, topology subnet, local group `PEAK-VPN-ADMIN`, redirect-gateway, TLS + user auth. FortiClient can import an `.ovpn` you export from OPNsense.

Do not expose OPNsense web GUI on WAN as a stand-in for SSL VPN web mode.
