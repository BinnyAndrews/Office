# PEAK-CORP-FW — hardware config merge notes

Live OPNsense export (base): `config-PEAK-CORP-FW-new.xml`  
Merged ready-to-apply file: `config-PEAK-CORP-FW.xml`

Source of truth for *what* to migrate:  
`C:\tools\FortigateConfig\peak-opnsense-omada-migration\`

## Hardware NIC map (this box)

| Role | Device | OPNsense if | Address |
| --- | --- | --- | --- |
| Airtel WAN | `re1` | `wan` | `125.19.224.18/30` → gw `125.19.224.17` |
| Jio WAN | `re2` | `opt1` | `47.247.169.94/30` → gw `47.247.169.93` |
| MGMT (untagged) | `re0` | `lan` | `10.80.99.1/24` |
| Wired corp SVI | `re0_vlan100` | `opt2` | `10.80.100.1/24` |
| Wi‑Fi corp SVI | `re0_vlan101` | `opt3` | `10.80.101.1/24` |
| Guest Wi‑Fi SVI | `re0_vlan102` | `opt4` | `10.80.102.1/24` |
| Spare NIC | `re3` | `opt5` | disabled |

Omada uplink on `re0`: native/untagged = MGMT (99); tagged 100/101/102.

## What the live `*-new.xml` already had

| Setting | Status in export |
| --- | --- |
| Dual WAN public IPs | Present (Airtel + Jio) |
| MGMT `10.80.99.1` on `lan` | Present |
| Kea subnet stubs 99/100/101/102/103 | Present but incomplete options |
| DHCP reservations (printers/ACS/WS/TVs) | Present — **kept** via `download_reservations.csv` |
| VLANs / gateways / WAN_LB / NAT / aliases | **Missing** — added by merge |

## What merge adds

| Setting | Status |
| --- | --- |
| VLAN 100/101/102 SVIs | **Added** |
| Gateways + `WAN_LB` group | **Added** |
| Kea options (routers/DNS) + scopes on lan/opt2–4 | **Fixed** |
| Aliases + firewall rules | **Added** |
| NAT: APP 80/443, ACS SQL 1433 (source AKRIVIA_HR) | **Added** |
| Schedule `peak_optimised` | **Added** |
| Hostname / Asia/Kolkata / GUI `:4444` | **Updated** |
| Root password + TLS cert | **Preserved** from `*-new.xml` |
| Incomplete `ACS_VLAN` 10.80.103 scope | **Dropped** (ACS stays at `10.80.100.10`) |
| Guest captive portal (Peak Energy logo) | **Added** on `opt4` / VLAN 102 |
| WireGuard admin VPN | **Revoked** (apply caused kernel panic; add later via GUI if needed) |

## How this file was built

```powershell
cd C:\tools\PEAK-CORP-FW
python merge_migration_into_hardware.py
```

Uses `config-PEAK-CORP-FW-new.xml` as base → writes `config-PEAK-CORP-FW.xml`.

## Apply on the firewall

**Preferred (safer):** [SELECTIVE-RESTORE.md](SELECTIVE-RESTORE.md)

**Full restore:** System → Configuration → Backups → Restore `config-PEAK-CORP-FW.xml` → reboot.

After apply:

- MGMT: `https://10.80.99.1:4444`
- From VLAN 100: `https://10.80.100.1:4444`  
  user: `root` / existing password (unchanged)

## Related docs (FortigateConfig pack)

- `peak-opnsense-omada-migration\MIGRATION-STEPS.md`
- `peak-opnsense-omada-migration\CONFIGURABLE-ITEMS.md`
- `peak-opnsense-omada-migration\omada\SWITCH-SG2428P.md`
- `peak-opnsense-omada-migration\omada\WIFI-EAP670.md`
