# Selective restore / what to bring onto PEAK-CORP-FW

Use this when you prefer **not** to full-restore the whole XML.

Base export: `config-PEAK-CORP-FW-new.xml`  
Merged file: `config-PEAK-CORP-FW.xml`

## Already correct on the live box (keep)

| Item | Current value |
| --- | --- |
| Hostname | PEAK-CORP-FW |
| WAN Airtel | `re1` = `125.19.224.18/30` |
| WAN Jio | `re2` = `47.247.169.94/30` |
| MGMT | `lan` / `re0` = `10.80.99.1/24` |
| DHCP reservations | printers / ACS / WS / TVs (see `download_reservations.csv`) |
| Root password | Keep as set on this box |
| TLS certificate | Keep |

## Must add / change (from migration)

Do in this order in the GUI, **or** full-restore the merged `config-PEAK-CORP-FW.xml`.

### 1. System
- Timezone: **Asia/Kolkata**
- Domain: **peak.local**
- DNS: 8.8.8.8 / 1.1.1.1 (already set)
- Web GUI port: **4444**
- GUI/SSH listen: **lan, opt2** only (not WAN)

### 2. VLANs (on `re0`)
| Tag | Device | Description |
| ---: | --- | --- |
| 100 | `re0_vlan100` | WIRED_CORP |
| 101 | `re0_vlan101` | WL_CORP |
| 102 | `re0_vlan102` | WL_GUEST |

### 3. Interfaces
| If | Device | IP |
| --- | --- | --- |
| lan | `re0` | **10.80.99.1/24** (MGMT, untagged) |
| wan | `re1` | 125.19.224.18/30 + gateway WAN_AIRTEL |
| opt1 | `re2` | 47.247.169.94/30 + gateway WAN_JIO |
| opt2 | `re0_vlan100` | 10.80.100.1/24 |
| opt3 | `re0_vlan101` | 10.80.101.1/24 |
| opt4 | `re0_vlan102` | 10.80.102.1/24 |
| opt5 | `re3` | disabled |

### 4. Gateways
- `WAN_AIRTEL` → 125.19.224.17 (default)
- `WAN_JIO` → 47.247.169.93
- Group `WAN_LB`: both tier 1, trigger member down

### 5. Kea DHCP
Enable on **lan, opt2, opt3, opt4**. Fix routers/DNS on each scope (live export had empty options on 100/101/102). Keep reservations from CSV.

| Scope | Network | Pool | Gateway/DNS |
| --- | --- | --- | --- |
| MGMT | 10.80.99.0/24 | .101–.110 | 10.80.99.1 |
| WIRED_CORP | 10.80.100.0/24 | .101–.200 | 10.80.100.1 |
| WL_CORP | 10.80.101.0/24 | .101–.200 | 10.80.101.1 |
| WL_GUEST | 10.80.102.0/24 | .101–.110 | 10.80.102.1 |

Do **not** create a separate ACS_VLAN 10.80.103 — ACS is `10.80.100.10` on WIRED_CORP.

### 6. Aliases + firewall + NAT + schedule
See merged XML / README. Guest uses schedule `peak_optimised` (Mon–Fri 07:00–19:00).

### 7. Captive Portal (guest) + password policy
Already in merged `config-PEAK-CORP-FW.xml`:
- Zone on **opt4** (`WL_GUEST`), auth = **Local Database**, group **guestportal**
- Template **PeakEnergy-Guest** (Peak Energy logo)
- User **`peakguest`** (no GUI rights) — **set password after restore**: System → Access → Users
- Policy (System → Access → Servers → Local Database): min length **12**, **complexity on**, duration **off** (rotate guest password every **90 days** manually)
- Omada SSID `PETCPL-GUEST`: separate **WPA2-PSK** (do not reuse the portal password)

Rebuild helpers: `python captiveportal\build_peak_guest_portal.py` then `python captiveportal\enable_guest_password_auth.py`

### 8. WireGuard
**Revoked** from `config-PEAK-CORP-FW.xml` (was causing apply panic).  
Do not add WireGuard until VLANs are stable; configure later via GUI if needed.

## After apply — access

- From MGMT client on untagged `re0`: `https://10.80.99.1:4444`
- From VLAN 100: `https://10.80.100.1:4444`
