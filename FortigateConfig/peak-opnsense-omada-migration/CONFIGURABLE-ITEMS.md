# Configurable items and details

Everything you must set or verify. Values marked **FIXED** come from the FortiGate dump and should stay the same unless you intentionally renumber.

---

## 1. OPNsense — system

| Item | Value | Notes |
| --- | --- | --- |
| Hostname | `PEAK-CORP-FW` | Or `peak-opn` |
| Domain | `peak.local` | Change if you have real DNS |
| Timezone | `Asia/Kolkata` | FortiGate timezone 47 |
| DNS | `8.8.8.8`, `1.1.1.1` | System → Settings → General |
| Web GUI | HTTPS **4444** | LAN only — never WAN |
| SSH | Enabled | LAN only |
| Language | en_US | |

**You must set after restore:** root password, optional admin user.

---

## 2. OPNsense — physical NICs (edit before restore)

| Role | Placeholder in `nics.env` | Fill with |
| --- | --- | --- |
| Airtel WAN | `NIC_WAN` | e.g. `igb0` / `igc0` / `em0` |
| Jio WAN | `NIC_WAN2` | second NIC |
| LAN trunk to switch | `NIC_LAN` | third NIC |

Find names: **Interfaces → Assignments** on the fresh install **before** restore.

---

## 3. OPNsense — WAN addressing (**FIXED** public)

| Interface | IP | Gateway | Alias |
| --- | --- | --- | --- |
| wan | `125.19.224.18/30` | `125.19.224.17` | WAN_AIRTEL / Airtel-FIBER |
| opt1 (WAN2) | `47.247.169.94/30` | `47.247.169.93` | WAN_JIO / JIO-RF |

| Gateway group | Members | Mode |
| --- | --- | --- |
| `WAN_LB` | Both Tier 1 | Load balance / failover on loss+latency |

Monitor IPs: Airtel → `8.8.8.8`, Jio → `1.1.1.1`.

On opt1, enable **“This interface is a WAN”** if the restore does not set it.

---

## 4. OPNsense — VLANs and LAN (**FIXED** subnets)

Parent: `NIC_LAN` (no user gateway on parent — SVIs on VLANs).

| VLAN | OPNsense if | Description | SVI | DHCP |
| ---: | --- | --- | --- | --- |
| 100 | opt2 / vlan0.100 | WIRED_CORP | `10.80.100.1/24` | `101–200`, lease 36000s |
| 101 | opt3 / vlan0.101 | WL_CORP | `10.80.101.1/24` | `101–200`, lease 36000s |
| 102 | opt4 / vlan0.102 | WL_GUEST | `10.80.102.1/24` | `101–200` |

**Not migrated** (unused on old switch): VLAN 103 ACS-VLAN, 104 CCTV, FortiLink 99, 4088–4093.

### DHCP options

| Scope | Gateway | DNS | Static maps |
| --- | --- | --- | --- |
| VLAN 100 | 10.80.100.1 | 10.80.100.1 (Unbound) or 8.8.8.8 | `.101`→`4c:d7:17:a4:2a:d0`, `.102`→`4c:d7:17:a4:2b:11` |
| VLAN 101 | 10.80.101.1 | same | none |
| VLAN 102 | 10.80.102.1 | same | none |

### Known static hosts (configure on the devices, not only OPNsense)

| Host | IP | VLAN |
| --- | --- | --- |
| ACS / attendance DB | `10.80.100.10` | 100 |
| PEAK-APP / OFFICE_PC | `10.80.100.103` | 100 |
| OFFICE_PC clone | `10.80.100.104` | 100 |
| Omada SG2428P mgmt | `10.80.100.2` | 100 |
| Omada controller (if on LAN) | e.g. `10.80.100.3` | 100 |

---

## 5. OPNsense — NAT / port forwards

| Name | WAN | Ext IP | Port | Internal | Keep? |
| --- | --- | --- | --- | --- | --- |
| PEAK-APP HTTP | both | each WAN IP | 80 | `10.80.100.103:80` | Yes |
| PEAK-APP HTTPS | both | each WAN IP | 443 | `10.80.100.103:443` | Yes |
| ACS SQL | both | each WAN IP | 1433 | `10.80.100.10:1433` | Yes — **source lock** |
| ACS RDP | — | — | 3389 | — | **No** — do not publish |

**Configurable:** alias `AKRIVIA_HR` default `34.87.189.127`. Replace with real Keka/Akrivia IPs when confirmed.

Outbound NAT: **automatic**.

---

## 6. OPNsense — firewall rules (logic)

| Order | Interface | Source | Dest | Gateway | Schedule |
| --- | --- | --- | --- | --- | --- |
| 1 | WIRED_CORP | 10.80.100.0/24 | any | WAN_LB | always |
| 2 | WL_CORP | 10.80.101.0/24 | any | WAN_LB | always |
| 3 | WL_GUEST | 10.80.102.0/24 | any | WAN_LB | `peak_optimised` |
| 4 | WIRED_CORP | 10.80.100.0/24 | 10.80.101.0/24 | default | always |
| 5 | WL_CORP | 10.80.101.0/24 | 10.80.100.0/24 | default | always |
| Optional | WL_GUEST | 10.80.102.0/24 | RFC1918 | — | **block** (guest isolation) |

Default deny at end (OPNsense implicit).

Schedule **peak_optimised**: Mon–Fri **07:00–19:00**.

---

## 7. Omada SG2428P

See `omada/SWITCH-SG2428P.md`. Summary:

| Item | Value |
| --- | --- |
| Mgmt IP | `10.80.100.2/24` |
| Gateway | `10.80.100.1` |
| VLAN 100 | Wired corp |
| VLAN 101 | Corp Wi‑Fi |
| VLAN 102 | Guest Wi‑Fi |
| Ports 1–20 | Access VLAN 100 |
| Ports 21–23 | AP trunks (tag 101,102) |
| Port 24 or SFP1 | Trunk to OPNsense |
| PoE budget | 250 W total — 3× EAP670 OK |

**Configurable:** which physical ports get ACS/APP/biometrics (any access VLAN 100 port).

---

## 8. Omada EAP670 × 3

See `omada/WIFI-EAP670.md`. Summary:

| SSID | VLAN | Password | Schedule |
| --- | --- | --- | --- |
| PETCPL | 101 | **new** (you choose) | always |
| PETCPL-GUEST | 102 | **new** | Mon–Fri 07:00–19:00 |

Country: **India**. Channel: Auto or set after site survey.

---

## 9. Keka / Akrivia / biometrics

| Item | Detail |
| --- | --- |
| Biometrics | Plug into VLAN 100 access ports; same L2 as ACS |
| ACS | `10.80.100.10` — SQL listens on 1433 |
| Cloud pull | OPNsense VIP 1433 → ACS; source = vendor IPs |
| Keka admin | Confirm connector URL/IP after cutover |

---

## 10. Passwords / secrets to create (all new)

| Secret | Where |
| --- | --- |
| OPNsense root | System → Access |
| Omada controller admin | Omada UI |
| Switch admin (if local) | Omada / switch web |
| SSID PETCPL | Omada WLAN |
| SSID PETCPL-GUEST | Omada WLAN |
| ACS Windows/SQL (unchanged unless you rotate) | On ACS server |

FortiGate encrypted passwords **cannot** be reused.
