# NAT and firewall (FortiGate → OPNsense)

Interface names below assume:

- `wan` = Airtel `125.19.224.18`
- `opt1` = Jio `47.247.169.94` (enable **WAN2** checkbox: Interfaces → opt1 → **This interface is a WAN**)
- `opt2` = VLAN 100 WIRED_CORP
- `opt3` = VLAN 101 WL_CORP
- `opt4` = VLAN 102 WL_GUEST
- `opt5` = VLAN 103 ACS
- `opt6` = VLAN 104 CCTV
- `opt7` = VLAN 1 DEFAULT
- `opt8` = WireGuard `wg0`

Create a **schedule** `peak_optimised`: Mon–Fri 07:00–19:00 (Firewall → Settings → Schedules).

Create gateway group **WAN_LB**: both WAN gateways **Tier 1**, trigger **Packet Loss or High Latency**, load-balancing.

Outbound NAT: **Automatic** (covers LAN/WLAN → both WANs).

## Port forwards

FortiGate VIPs are duplicated per WAN IP. Recreate each pair. Set **Filter rule association** to **Pass** only after you have tightened source (see hardening).

| FortiGate VIP | Interface | External IP | Ext port | Target | Local port |
| --- | --- | --- | --- | --- | --- |
| PEAK-APP-1-Airtel | wan | 125.19.224.18 | TCP 80 | 10.80.100.103 | 80 |
| PEAK-APP-2-Airtel | wan | 125.19.224.18 | TCP 443 | 10.80.100.103 | 443 |
| ACS-SERVER-Airtel | wan | 125.19.224.18 | TCP 1433 | 10.80.100.10 | 1433 |
| RDP of ACS-SERVER-Airtel | wan | 125.19.224.18 | TCP 3389 | 10.80.100.10 | 3389 |
| PEAK-APP-1-Jio | opt1 | 47.247.169.94 | TCP 80 | 10.80.100.103 | 80 |
| PEAK-APP-2-Jio | opt1 | 47.247.169.94 | TCP 443 | 10.80.100.103 | 443 |
| ACS-SERVER-Jio | opt1 | 47.247.169.94 | TCP 1433 | 10.80.100.10 | 1433 |
| RDP of ACS-SERVER-Jio | opt1 | 47.247.169.94 | TCP 3389 | 10.80.100.10 | 3389 |

FortiGate policy **Akrivia_HR>LAN** used `srcaddr: all` despite the name. The object `Akrivia_HR` (`34.87.189.127`) was never used as source. **Do not publish 3389/1433 to the world.** Limit those four forwards to alias `AKRIVIA_HR` or to WireGuard.

Reflection: enable **NAT reflection** if staff must hit the public hostname from inside VLAN 100.

## Firewall rules (same order as FortiGate)

OPNsense is first-match. Put these on the **source interface**. Default deny at the end is implicit.

### opt2 / opt3 / opt4 / opt7 (LAN/WLAN → WAN)

FortiGate policy 8 `LAN > WAN`: src `_default`, `WL-CORP`, `WL-GUEST`, `WIRED-CORP` → SD-WAN, NAT, any service.

| # | Interface | Action | Source | Dest | Service | Gateway | Schedule | Extra |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | opt2 | pass | WIRED_CORP | * | * | WAN_LB | always | log |
| 2 | opt3 | pass | WL_CORP | * | * | WAN_LB | always | log |
| 3 | opt4 | pass | WL_GUEST | * | * | WAN_LB | peak_optimised | log; guest SSID was also time-limited on the AP |
| 4 | opt7 | pass | DEFAULT_VLAN | * | * | WAN_LB | always | only if you still use VLAN 1 |

Allow IPv4+IPv6 only if you use IPv6. FortiGate had no IPv6 LAN.

Block guest → RFC1918 on opt4 **above** the WAN allow if you want guest isolation (FortiGate did not isolate guest from corp via policy; guest was simply omitted from inter-VLAN allows).

### Inter-VLAN (policies 6 and 7)

| # | Interface | Action | Source | Dest | Service |
| --- | --- | --- | --- | --- | --- |
| 5 | opt2 | pass | WIRED_CORP | WL_CORP | * |
| 6 | opt3 | pass | WL_CORP | WIRED_CORP | * |

No other east-west allows existed. ACS, CCTV, guest, and VLAN 1 cannot talk to each other unless you add rules.

### WireGuard (policies 4 and 5)

| # | Interface | Action | Source | Dest | Service | Auth |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | opt8 | pass | WG_ADMIN_NET | WIRED_CORP, WL_CORP, WL_GUEST, ACS, CCTV | * | PEAK-VPN-ADMIN peers only (10.80.200.2–3) |
| 8 | opt8 | pass | (staff /32s) | WIRED_CORP, WL_CORP | * | PEAK-VPN-STAFF was empty |

### WAN inbound

If port-forward filter association is **Pass**, OPNsense already creates WAN rules. Otherwise add:

| # | Interface | Source | Dest | Service |
| --- | --- | --- | --- | --- |
| 9 | wan + opt1 | AKRIVIA_HR | ACS_SERVER | TCP 1433, TCP 3389 |
| 10 | wan + opt1 | * | OFFICE_PC | TCP 80, TCP 443 |

Do not allow WAN to OPNsense GUI/SSH.

### Optional MAC allowlist on wired LAN

FortiGate captive portal on `WIRED-CORP` exempted `MAC WHITELIST` and authenticated group `PEAK-LAN-STAFF` (`peakemp`).

OPNsense equivalent:

1. Services → Captive Portal on `opt2`.
2. Allowed MAC addresses = `mac-whitelist.csv` (`in_fortigate_group=yes`).
3. Or skip captive portal and use DHCP statics + a firewall rule: source MAC alias `MAC_WHITELIST` pass, then deny others. MAC filtering is weak; treat it as convenience, not security.

## DHCP (Services → ISC DHCPv4)

| Interface | Range | Gateway | Lease | DNS |
| --- | --- | --- | --- | --- |
| opt2 | 10.80.100.101–200 | 10.80.100.1 | 36000s | OPNsense or 8.8.8.8/1.1.1.1 |
| opt3 | 10.80.101.101–200 | 10.80.101.1 | 36000s | same |
| opt4 | 10.80.102.101–200 | 10.80.102.1 | default | same |
| opt7 | 10.80.10.11–20 | 10.80.10.1 | default | same |

Static maps: `dhcp-static-maps.csv`.

Known hosts without DHCP reservations (set statically on the box, or add reservations):

- `10.80.100.10` ACS server
- `10.80.100.103` OFFICE_PC / PEAK-APP
- `10.80.100.104` Clone of OFFICE_PC

No DHCP existed for ACS (103) or CCTV (104).

## Dual-WAN details

FortiGate SD-WAN members:

- member 1: wan2 / Jio gw `47.247.169.93`
- member 2: wan1 / Airtel gw `125.19.224.17`
- service `Default_Internet_LB` mode load-balance, `priority-members: 2 1` (Airtel preferred)
- probe: Default_DNS every 1s, SLA latency 250 ms, jitter 50 ms, loss 5%

OPNsense:

1. System → Gateways → WAN_AIRTEL: interface wan, gw 125.19.224.17, monitor 8.8.8.8
2. WAN_JIO: interface opt1, gw 47.247.169.93, monitor 1.1.1.1
3. Group WAN_LB: both Tier 1 (equal load-balance). To prefer Airtel, put Airtel Tier 1 and Jio Tier 2 (failover instead of LB).
4. System → Routes: default via WAN_LB (policy routing on LAN rules is enough; leave system default on Airtel).
5. Firewall → Settings → Advanced: **Sticky connections** on if HTTPS/app sessions break across WANs.

No OSPF/BGP/RIP was actually configured (empty redistribute stubs only). No extra static routes besides SD-WAN default.
