# PEAK-CORP-FW — current setup

OPNsense firewall **PEAK-CORP-FW**. Picture of the network: `docs/Peak-Energy-Network-Architecture.docx` (regenerate with `docs/generate_network_architecture.py`).

## Access

- GUI: `https://10.80.99.1:4444` (also `https://10.80.100.1:4444` from wired corp)
- Listen interfaces: MGMT (`lan`), WIRED_CORP (`opt2`), WL_CORP (`opt3`), WIREGUARD (`opt6`). Not on either WAN.
- Timezone: Asia/Kolkata
- Domain: **peakenergy.asia**
- Upstream DNS: 8.8.8.8 / 1.1.1.1

## Hardware NIC map

| Role | Device | OPNsense if | Address |
| --- | --- | --- | --- |
| Airtel WAN | `re1` | `wan` | `125.19.224.18/30` → gw `125.19.224.17` |
| Jio WAN | `re2` | `opt1` | `47.247.169.94/30` → gw `47.247.169.93` |
| MGMT (untagged) | `re0` | `lan` | `10.80.99.1/24` |
| Wired corp | `re0_vlan100` | `opt2` | `10.80.100.1/24` |
| Corp Wi-Fi (PETCPL) | `re0_vlan101` | `opt3` | `10.80.101.1/24` |
| Guest Wi-Fi | `re0_vlan102` | `opt4` | `10.80.102.1/24` |
| WireGuard | `wg0` | `opt6` | `10.80.200.1/28` |
| Spare NIC | `re3` | `opt5` | disabled |

Omada uplink on `re0`: native/untagged = MGMT; tagged 100/101/102. Gateways `WAN_AIRTEL` and `WAN_JIO` are both tier 1 in group `WAN_LB` (load balance, failover on member down).

## What is running

- WireGuard **PEAK-WG** on UDP **51820** (both WANs). Peers `.2`–`.9` and the access split: `wireguard/README.md`.
- Public PeakPulse HTTP/HTTPS DNAT is **disabled**. `app` and `peakpulse-dev.peakenergy.asia` resolve to `10.80.100.54` for on-site and VPN clients only.
- Active ACS is `10.80.100.10` (`biometric-server`). Entry `.11`, exit `.12`. SQL 1433 is **KEKA_HR** only. `AKRIVIA_HR` is disabled.
- Corp Wi-Fi MAC allowlist rules are kept and **disabled**. PETCPL is open to VLAN 101.
- Guest SSID **PETCPL-GUEST** is VLAN 102 with the captive portal. Internet is scheduled Mon–Fri 07:00–19:00 (`peak_optimised`).

## Related docs

- `SELECTIVE-RESTORE.md` — interface, DHCP, and portal values as they run today
- `UNBOUND-peakenergy.md` — internal DNS names
- `wireguard/README.md` — VPN peers and client install
- `WL-CORP-MAC-RULES.md` — MAC policy if it is turned back on
