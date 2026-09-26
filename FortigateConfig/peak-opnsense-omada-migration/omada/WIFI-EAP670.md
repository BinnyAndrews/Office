# Omada EAP670 — Wi‑Fi configuration

**Hardware:** 3× EAP670 (Wi‑Fi 6), replacing FortiAP 431F AP-001 / AP-002 / AP-003.  
**Controller:** Omada Controller (OC200 / OC300 / software).  
**Country:** India.

Max load discussed: **~40 clients total** across 3 APs — EAP670 is comfortable.

---

## 1. Adoption

1. Connect each EAP670 to SG2428P ports **21, 22, 23** (PoE).
2. Adopt in Omada Controller.
3. Name them to match old roles, e.g.:
   - `AP-001` (was FP431FTF23099DUY)
   - `AP-002` (was FP431FTF23099DJ8)
   - `AP-003` (was FP431FTF23099DHU)
4. Mount in the **same physical locations** as the FortiAPs if possible.

---

## 2. WLAN / SSID settings

### SSID 1 — corporate

| Setting | Value |
| --- | --- |
| SSID name | `PETCPL` |
| VLAN | **101** |
| Security | WPA2/WPA3-Personal (or WPA2-PSK) |
| Password | **Create new** (old FortiGate passphrase not recoverable) |
| Band | 2.4 + 5 GHz |
| Guest network | No |
| Schedule | Always |
| SSID isolation | Optional off |

Clients get DHCP from OPNsense on `10.80.101.0/24`, gateway `10.80.101.1`.

### SSID 2 — guest

| Setting | Value |
| --- | --- |
| SSID name | `PETCPL-GUEST` |
| VLAN | **102** |
| Security | WPA2-PSK |
| Password | **Create new** |
| Guest network | Yes (Omada client isolation) |
| Schedule | **Monday–Friday 07:00–19:00** (matches FortiGate `peak_optimised`) |
| Portal | OPNsense captive portal on VLAN 102 (user `peakguest` + Local Database password) |

Clients get DHCP on `10.80.102.0/24`, gateway `10.80.102.1`. OPNsense also applies the same schedule on guest → WAN rules.

---

## 3. AP LAN / switch side

Each AP uplink port on the switch must be a **trunk**:

- Untagged: VLAN 100 (AP management can use VLAN 100 DHCP or static in `10.80.100.0/24`)
- Tagged: **101, 102**

In Omada, set WLAN VLAN IDs to 101 / 102 (not “untagged only”).

Optional: reserve static IPs for APs, e.g.:

| AP | IP |
| --- | --- |
| AP-001 | 10.80.100.21 |
| AP-002 | 10.80.100.22 |
| AP-003 | 10.80.100.23 |

---

## 4. Radio tips (40 users)

| Setting | Suggestion |
| --- | --- |
| Channel width 5 GHz | 40 or 80 MHz |
| Channel width 2.4 GHz | 20 MHz |
| Channel | Auto initially; fix if interference |
| Tx power | Medium / Auto |
| Band steering | Enable if available |

---

## 5. Verification

1. Join `PETCPL` → IP `10.80.101.x` → browse internet.  
2. Join `PETCPL-GUEST` inside schedule → IP `10.80.102.x` → internet.  
3. Outside schedule → guest SSID down or no WAN (OPNsense schedule).  
4. Confirm guest cannot reach `10.80.100.10` if you enabled guest isolation / OPNsense block rules.

---

## 6. Passwords checklist

- [ ] PETCPL PSK set and shared with staff  
- [ ] PETCPL-GUEST PSK set  
- [ ] Old FortiAP SSIDs disabled (FortiGate powered off)
