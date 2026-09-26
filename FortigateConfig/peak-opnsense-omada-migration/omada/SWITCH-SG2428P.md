# Omada SG2428P — switch configuration

**Model:** Omada SG2428P — 24× Gigabit PoE+ + 4× Gigabit SFP, **250 W** PoE budget.

Replaces FortiSwitch PEAK-CORE-SW (48 ports). You must **consolidate** devices onto 24 copper ports.

---

## 1. Management

| Setting | Value |
| --- | --- |
| Management VLAN | 100 |
| IP | `10.80.100.2` |
| Mask | `255.255.255.0` |
| Gateway | `10.80.100.1` (OPNsense) |
| DNS | `10.80.100.1` or `8.8.8.8` |

Adopt into Omada Controller. Prefer controller-managed VLANs/ports so settings survive.

---

## 2. Create VLANs

| VLAN ID | Name | Purpose |
| ---: | --- | --- |
| 100 | WIRED_CORP | Wired users, ACS, APP, biometrics, printers |
| 101 | WL_CORP | SSID PETCPL |
| 102 | WL_GUEST | SSID PETCPL-GUEST |

Do **not** create FortiLink/NAC VLANs (99, 4088–4093).

---

## 3. Port plan (recommended)

| Ports | Type | Untagged (PVID) | Tagged | Use |
| --- | --- | ---: | --- | --- |
| **1–20** | Access | **100** | — | PCs, ACS, APP, biometrics, printers |
| **21–23** | Trunk | 100 | **101, 102** | EAP670 × 3 |
| **24** | Trunk (spare copper uplink) | 100 | 100,101,102 | Alternate uplink to OPNsense |
| **SFP1** | Trunk | 100 | **100, 101, 102** | **Primary uplink → OPNsense LAN** |
| **SFP2–4** | Disabled / spare | — | — | Future |

If OPNsense has only RJ45, use **port 24 copper trunk** to OPNsense and free SFP1, **or** use a copper SFP module in SFP1.

### Suggested device placement (VLAN 100 access)

| Priority | Device | Suggested port |
| --- | --- | ---: |
| Critical | ACS `10.80.100.10` | 1 |
| Critical | PEAK-APP `10.80.100.103` | 2 |
| Critical | Biometric 1 | 3 |
| Critical | Biometric 2 | 4 |
| High | Printers / office servers | 5–8 |
| Normal | Staff PCs | 9–20 |
| AP | EAP670 #1 / #2 / #3 | 21 / 22 / 23 |
| Uplink | OPNsense | SFP1 or 24 |

Fill the rest from your FortiSwitch cable inventory. Devices that do not fit need a **second switch** (VLAN 100 access only, uplink to a SG2428P VLAN 100 port) or a larger Omada switch later.

---

## 4. Trunk to OPNsense (detail)

On the uplink port (SFP1 or 24):

- Mode: **Trunk** / General
- Native / untagged: VLAN **100** (so management and simple links work)
- Tagged: **100, 101, 102** (tag 100 optional if native is 100 — match OPNsense VLAN parent expectation)

On OPNsense, parent `NIC_LAN` carries 802.1Q tags 100/101/102 as VLAN interfaces. Do **not** put an IP on the parent for users; gateways are the SVIs.

---

## 5. PoE

| Device | Approx draw | Ports |
| --- | --- | --- |
| EAP670 × 3 | ~15–20 W each | 21–23 |
| Budget | 250 W total | Plenty of headroom |

Enable PoE on AP ports; leave PoE on for other ports only if devices need it.

---

## 6. Optional Omada features

- **IGMP snooping**: on if you use multicast cameras later
- **Loop protection / STP**: enable RSTP
- **ACL**: optional guest isolation (or do it on OPNsense)
- **802.1X**: not required for this migration

---

## 7. Verification

From a PC on port 1–20:

1. Gets `10.80.100.x` from OPNsense DHCP  
2. Gateway `10.80.100.1`  
3. Can ping `10.80.100.2` (switch) and `10.80.100.1` (OPNsense)  
4. Internet works after WAN cutover  

From Omada controller: switch online, all VLANs present, AP ports up with PoE.
