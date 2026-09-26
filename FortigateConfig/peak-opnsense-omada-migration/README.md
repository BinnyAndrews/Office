# PEAK migration — OPNsense + Omada SG2428P + EAP670

**Goal:** Remove FortiGate completely. OPNsense is the only firewall/router. Omada switch + APs replace FortiSwitch and FortiAP.

| Role | Hardware / software |
| --- | --- |
| Firewall / router | **OPNsense** (fresh install) |
| Core switch | **Omada SG2428P** (24× PoE+ + 4× SFP) |
| Wi‑Fi | **Omada EAP670** × 3 (recommended) |
| Omada controller | OC200 / OC300 / software controller on a VM |

## Important change vs FortiSwitch

Your FortiSwitch had **48 copper access ports**. **SG2428P has 24 copper PoE ports**. Consolidate devices onto fewer ports before cutover (or keep a second unmanaged/dumb switch for overflow on VLAN 100 only — not ideal).

## Target topology

```text
Airtel 125.19.224.18/30 ─┐
                         ├─► OPNsense
Jio    47.247.169.94/30 ─┘         │
                                   │ 802.1Q trunk (VLAN 100,101,102)
                                   ▼
                            Omada SG2428P
                     ┌─────────┼─────────┐
                     │         │         │
              ports 1–20   21–23      SFP1
              VLAN 100     EAP670    to OPNsense
              (wired)      trunks
```

## Folder contents

| Path | Purpose |
| --- | --- |
| [MIGRATION-STEPS.md](MIGRATION-STEPS.md) | Ordered cutover procedure |
| [CONFIGURABLE-ITEMS.md](CONFIGURABLE-ITEMS.md) | All settings to enter / verify |
| [omada/SWITCH-SG2428P.md](omada/SWITCH-SG2428P.md) | Switch VLANs and port plan |
| [omada/WIFI-EAP670.md](omada/WIFI-EAP670.md) | SSIDs, VLANs, schedules |
| [opnsense/nics.env](opnsense/nics.env) | **Edit NIC names before restore** |
| [opnsense/build_config_xml.py](opnsense/build_config_xml.py) | Builds `config.xml` |
| [opnsense/config.xml](opnsense/config.xml) | Restore file for fresh OPNsense |
| [opnsense/RESTORE.md](opnsense/RESTORE.md) | How to apply config.xml safely |

## Quick start

1. Install OPNsense on the new box (3 NICs: WAN Airtel, WAN Jio, LAN).
2. Note interface names under **Interfaces → Assignments** (e.g. `igc0`, `igb0`, `em0`).
3. Edit `opnsense/nics.env` with those names.
4. Run: `python opnsense/build_config_xml.py`
5. Restore `opnsense/config.xml` (see RESTORE.md).
6. Configure Omada switch + EAP670 from the Omada docs.
7. Follow **MIGRATION-STEPS.md** for the maintenance-window cutover.

## What moves from FortiGate

| Kept on OPNsense | Dropped |
| --- | --- |
| Dual WAN IPs + gateways | FortiLink / FortiAP controller |
| VLAN 100 / 101 / 102 SVIs + DHCP | VLAN 103/104 (unused on old switch) |
| ACS VIP TCP 1433 (hardened source) | Public RDP 3389 (use LAN/VPN only) |
| App VIP 80/443 → 10.80.100.103 | FortiGuard web filter |
| LAN/WLAN firewall rules | Captive portal (optional later on Omada) |
| DNS 8.8.8.8 / 1.1.1.1, Asia/Kolkata | FortiGate admin on WAN |

WireGuard is **not** included in this pack (not required for Keka). Add later if you need remote admin.
