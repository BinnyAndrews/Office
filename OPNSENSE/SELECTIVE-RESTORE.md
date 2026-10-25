# PEAK-CORP-FW — running configuration

Do **not** full-restore an old XML onto this firewall. Change one area in the GUI. This page is the live layout, not a build checklist.

Backup of record: `OPNSENSE_BACKUP/config-PEAK-CORP-FW.CURRENT.xml` (older than some VPN peer adds; peer list of record is `wireguard/README.md`).

## System

| Item | Value |
| --- | --- |
| Hostname | PEAK-CORP-FW |
| Timezone | Asia/Kolkata |
| Domain | **peakenergy.asia** |
| DNS | 8.8.8.8 / 1.1.1.1 |
| Web GUI | HTTPS **4444** |
| GUI and SSH listen | **lan, opt2, opt3, opt6** (never WAN) |

## Interfaces

| If | Device | IP |
| --- | --- | --- |
| lan | `re0` | 10.80.99.1/24 (MGMT, untagged) |
| wan | `re1` | 125.19.224.18/30, gateway WAN_AIRTEL |
| opt1 | `re2` | 47.247.169.94/30, gateway WAN_JIO |
| opt2 | `re0_vlan100` | 10.80.100.1/24 WIRED_CORP |
| opt3 | `re0_vlan101` | 10.80.101.1/24 WL_CORP |
| opt4 | `re0_vlan102` | 10.80.102.1/24 WL_GUEST |
| opt5 | `re3` | disabled |
| opt6 | `wg0` | WIREGUARD, tunnel 10.80.200.1/28 |

VLANs on `re0`: 100 WIRED_CORP, 101 WL_CORP, 102 WL_GUEST. There is no separate ACS VLAN. ACS is `10.80.100.10`.

## Gateways

- `WAN_AIRTEL` → 125.19.224.17
- `WAN_JIO` → 47.247.169.93
- Group `WAN_LB`: both tier 1, trigger member down

## Kea DHCP

Enabled on lan, opt2, opt3, opt4. Each scope hands out its own gateway as DNS, domain `peakenergy.asia`.

| Scope | Network | Pool | Gateway/DNS |
| --- | --- | --- | --- |
| MGMT | 10.80.99.0/24 | .101–.200 | 10.80.99.1 |
| WIRED_CORP | 10.80.100.0/24 | .101–.200 | 10.80.100.1 |
| WL_CORP | 10.80.101.0/24 | .101–.200 | 10.80.101.1 |
| WL_GUEST | 10.80.102.0/24 | .101–.200 | 10.80.102.1 |

## NAT and schedules in force

- PeakPulse HTTP/HTTPS DNAT on both WANs: present, **disabled**
- ACS SQL TCP 1433 on both WANs: **KEKA_HR** → `10.80.100.10`
- Guest internet schedule `peak_optimised`: Mon–Fri 07:00–19:00

## Captive portal (guest)

- Zone on **opt4** (`WL_GUEST`), auth = local database, group **guestportal**
- Template **PeakEnergy-Guest**
- SSID `PETCPL-GUEST` uses its own WPA2-PSK. That password is not the portal password.
- Rotate the portal password about every 90 days (System → Access → Users)

Rebuild helpers, if the template is edited: `python captiveportal\build_peak_guest_portal.py` then `python captiveportal\enable_guest_password_auth.py`

## WireGuard

Live. Do not restore `wireguard/wireguard-peak-admin.xml`.

Instance **PEAK-WG**, interface **opt6 / wg0**, UDP **51820** on both WANs. Peers `10.80.200.2`–`.9`. Admins (`.2`/`.3`) reach the firewall and MGMT. Other peers reach CORP only. RDP is blocked for every AMC peer except Jagadeshwar. Detail: `wireguard/README.md`.

## Admin URLs

- From MGMT: `https://10.80.99.1:4444`
- From VLAN 100: `https://10.80.100.1:4444`
