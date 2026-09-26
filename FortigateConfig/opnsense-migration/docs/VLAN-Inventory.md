# PEAK VLAN inventory — FortiGate + FortiSwitch

Source: `PEAK-CORP-FW_7-2_1762_202609160923.conf.yaml`  
Firewall: FortiGate 100F `PEAK-CORP-FW`  
Switch: FortiSwitch `PEAK-CORE-SW` (`S148FFTF23020423`), FortiLink-managed via FortiGate `port12` / interface `fortilink`

---

## 1. All VLANs on the FortiGate (SVIs on FortiLink)

Parent interface for all of these (except FortiLink itself): **`fortilink`** (aggregate, member `port12`, IP `10.80.99.1/24`).

| VLAN ID | Interface name | SVI / network | DHCP on FG | Role / notes | In use on switch? |
| ---: | --- | --- | --- | --- | --- |
| — | `fortilink` | `10.80.99.1/24` | `10.80.99.2–10` (FortiSwitch / FortiExtender VCI) | FortiLink control plane; switch mgmt `10.80.99.2` | Yes (uplink) |
| **1** | `_default` | `10.80.10.1/24` | `10.80.10.11–20` | Default / unused access ports | Yes — ports 41–52 native |
| **100** | `WIRED-CORP` | `10.80.100.1/24` | `10.80.100.101–200` (lease 10h) | Wired corp LAN; ACS `.10`, APP `.103`; captive portal + MAC exempt | Yes — ports 1–40 access |
| **101** | `WL-CORP` | `10.80.101.1/24` | `10.80.101.101–200` (lease 10h) | Corporate Wi‑Fi (SSID **PETCPL**) | Tagged on AP trunks (41–42) |
| **102** | `WL-GUEST` | `10.80.102.1/24` | `10.80.102.101–200` | Guest Wi‑Fi (SSID **PETCPL-GUEST**, schedule Mon–Fri 07–19) | Tagged on AP trunks (41–42) |
| **103** | `ACS-VLAN` | `10.80.103.1/24` | none | Intended ACS segment; address object `ACS` | **No** — no switch port uses it |
| **104** | `CCTV-VLAN` | `10.80.104.1/24` | none | CCTV segment; address object `CCTV` | **No** — no switch port uses it |
| **4088** | `nac_segment` | `10.255.13.1/24` | `10.255.13.2–254` (lease 300s) | NAC segment (FortiSwitch controller feature) | Not assigned as access VLAN |
| **4089** | `onboarding` | (no IPv4 in dump) | — | NAC onboarding; captive portal | Not assigned as access VLAN |
| **4090** | `video` | (no IPv4) | — | FortiCamera / video feature VLAN | Not assigned as access VLAN |
| **4091** | `voice` | (no IPv4) | — | FortiVoice feature VLAN | Not assigned as access VLAN |
| **4092** | `rspan` | `10.255.12.1/24` | `10.255.12.2–254` | RSPAN / sniffer | Not assigned as access VLAN |
| **4093** | `quarantine` | `10.255.11.1/24` | `10.255.11.2–254` | Quarantine; captive portal | Allowed/untagged on **all** switch ports (dynamic quarantine) |

### Wi‑Fi SSID → VLAN (FortiAP / VAP)

| SSID | VAP | VLAN ID | Bridging |
| --- | --- | ---: | --- |
| PETCPL | `PETCPL` | **101** | local-bridging |
| PETCPL-GUEST | `PETCPL-GUEST` | **102** | local-bridging · schedule `peak_optimised` |

`PETCPL` / `PETCPL-GUEST` also appear as `vap-switch` interfaces on the FortiGate (soft switch for the SSIDs); user traffic is still VLAN 101/102 on the wire.

---

## 2. FortiSwitch PEAK-CORE-SW — per-port VLAN map

Native / access VLAN is the `vlan:` field.  
`allowed-vlans` / `untagged-vlans` add **quarantine (4093)** for FortiLink NAC/quarantine behaviour.

| Switch ports | Mode (practical) | Native / access VLAN | Allowed / tagged | Untagged extras |
| --- | --- | --- | --- | --- |
| **port1 – port40** | Access | **WIRED-CORP (100)** | quarantine (4093) | quarantine (4093) |
| **port41 – port42** | Trunk (AP) | **_default (1)** | **all VLANs** (`allowed-vlans-all`) | quarantine (4093) |
| **port43 – port48** | Access | **_default (1)** | quarantine (4093) | quarantine (4093) |
| **port49 – port52** | Access (SFP / auto-module) | **_default (1)** | quarantine (4093) | quarantine (4093) |

### Port groups summarized

```
Ports 1–40   → untagged VLAN 100 (WIRED-CORP)     ← biometrics, PCs, ACS, printers, etc.
Ports 41–42  → native VLAN 1 + all VLANs tagged   ← FortiAP trunks (101/102 client traffic)
Ports 43–52  → untagged VLAN 1 (_default)         ← spare / unused access
```

FortiLink uplink to the FortiGate is the switch’s FortiLink/ISL face toward FG `port12` (not listed as a normal `portN` access assignment in the same way; control plane uses FortiLink `10.80.99.0/24`).

---

## 3. Firewall vs switch — which VLANs actually carry traffic

| VLAN | On firewall | On switch ports | Typical traffic |
| ---: | --- | --- | --- |
| FortiLink 10.80.99.0/24 | Yes | Uplink / mgmt | Switch CAPWAP/FortiLink mgmt |
| 1 | Yes | 41–52 native; 43–52 access | Mostly idle / default |
| 100 | Yes | 1–40 access | **Primary production LAN** |
| 101 | Yes | Tagged on 41–42 | Corporate Wi‑Fi |
| 102 | Yes | Tagged on 41–42 | Guest Wi‑Fi |
| 103 | Yes | **None** | Unused |
| 104 | Yes | **None** | Unused |
| 4088–4093 | Yes (controller defaults) | 4093 allowed on every port | Quarantine/NAC features; not used as normal access |

---

## 4. Related address objects (firewall)

| Object | Network | Maps to VLAN |
| --- | --- | ---: |
| `WIRED-CORP` | `10.80.100.0/24` | 100 |
| `WL-CORP` | `10.80.101.0/24` | 101 |
| `WL-GUEST` | `10.80.102.0/24` | 102 |
| `ACS` | `10.80.103.0/24` | 103 (SVI only; devices not on this VLAN today) |
| `CCTV` | `10.80.104.0/24` | 104 (SVI only) |

Note: ACS server **`10.80.100.10`** and biometrics sit on **VLAN 100**, not VLAN 103.

---

## 5. OPNsense migration notes

Keep on the OPNsense LAN trunk:

| VLAN | Keep? | Reason |
| ---: | --- | --- |
| 100, 101, 102 | **Yes** | Production wired + Wi‑Fi |
| 1 | Optional | Only if ports 43–52 still need default |
| 103, 104 | Optional | Only if you plan to move ACS/CCTV later |
| 4088–4093 | **No** (unless you rebuild NAC) | FortiSwitch-controller leftovers |
| FortiLink 99 | Replace | After standalone switch, use e.g. `10.80.100.2` for switch mgmt |

Standalone switch trunk toward OPNsense should carry at least **tagged 100, 101, 102** (and 1/103/104 if retained), with access ports matching the table in section 2.
