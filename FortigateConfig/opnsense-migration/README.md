# PEAK-CORP-FW → OPNsense migration

Source: FortiGate 100F, FortiOS 7.2.13 (`PEAK-CORP-FW`). Hostname, public IPs, VLANs, NAT, and firewall policy are mapped below to OPNsense.

OPNsense cannot import a FortiGate config. Apply this kit on a fresh OPNsense box (the `opnsense` / `OPN` MAC `0e:51:d8:1c:e2:01` is already present on the FortiGate, so you can stage in parallel).

## What maps 1:1

| FortiGate | OPNsense |
| --- | --- |
| Dual WAN + SD-WAN load-balance | Two gateways + gateway group |
| VLAN SVIs 100–104 | VLAN interfaces on the LAN NIC |
| DHCP pools + reservations | ISC/Kea DHCP |
| Address objects / MAC group | Aliases (import `aliases.csv`) |
| VIP port forwards | Firewall → NAT → Port Forward |
| Policy NAT LAN→WAN | Outbound NAT automatic/hybrid |
| SSL VPN (OpenVPN-like tunnel) | WireGuard (recommended) or OpenVPN |
| Captive portal + MAC exempt | Captive Portal + MAC passthrough |
| Guest time window Mon–Fri 07:00–19:00 | Firewall schedule on VLAN 102 |
| DNS 8.8.8.8 / 1.1.1.1 | System → Settings → General |
| NTP, timezone 47 (India) | Asia/Kolkata |
| Admin HTTPS :4444 | System → Settings → Administration |

## What does not migrate

| FortiGate feature | Reality on OPNsense |
| --- | --- |
| FortiLink / FortiSwitch controller | Convert **PEAK-CORE-SW** to standalone *before* cutover. OPNsense is only a router. |
| FortiAP 431F wireless controller (AP-001/002/003) | FortiAPs will not join OPNsense. Keep a tiny FortiGate as WLC, or replace APs (Omada/UniFi/OpenWrt). |
| FortiGuard web filter / AV / cert inspection | Unbound DNSBL + Suricata + optional Zenarmor. Category filtering is not identical. |
| Encrypted passwords (`ENC ...`) | Reset: `binny.andrews`, `admin`, `peakemp`, SSIDs, guest `peakguest`. |
| `allowaccess https ssh` on WAN1/WAN2 | **Do not copy.** Manage OPNsense from LAN/MGMT only. |

## Suggested NIC layout

Assign these in **Interfaces → Assignments**. Replace `igbX` with the NICs you actually have.

| Role | OPNsense name | Address | Notes |
| --- | --- | --- | --- |
| Airtel fiber | `wan` | `125.19.224.18/30` gw `125.19.224.17` | FortiGate `wan1` |
| Jio RF | `opt1` (WAN2) | `47.247.169.94/30` gw `47.247.169.93` | FortiGate `wan2`. Enable **Block private networks** off if the ISP uses CGNAT oddities; this /30 is public. |
| Switch trunk | `lan` parent + VLANs | see VLANs | 802.1Q trunk to FortiSwitch FortiLink port (today `port12` on the FortiGate) |
| Dedicated mgmt (optional) | `optX` | `192.168.77.99/24` | FortiGate `mgmt`. Keep if you still have that OOB network. |

Do not bring up FortiGate system VLANs 4088–4093 (NAC/quarantine/voice/video/rspan) unless you still need them.

## VLAN plan (LAN parent)

| VLAN | Interface | SVI | DHCP | Purpose |
| --- | --- | --- | --- | --- |
| 100 untagged or tagged | `opt2` WIRED_CORP | `10.80.100.1/24` | `10.80.100.101–200`, lease 10h | Wired staff + servers |
| 101 | `opt3` WL_CORP | `10.80.101.1/24` | `10.80.101.101–200`, lease 10h | SSID PETCPL |
| 102 | `opt4` WL_GUEST | `10.80.102.1/24` | `10.80.102.101–200` | SSID PETCPL-GUEST |
| 103 | `opt5` ACS | `10.80.103.1/24` | none today | Defined, unused on the switch |
| 104 | `opt6` CCTV | `10.80.104.1/24` | none today | Defined, unused on the switch |
| 1 | `opt7` DEFAULT | `10.80.10.1/24` | `10.80.10.11–20` | FortiSwitch leftover / unused access ports 41–52 |

Enable DHCP DNS/gateway = the SVI on each VLAN. Unbound on OPNsense can be the DNS (FortiGate “dns-service: default” used 8.8.8.8/1.1.1.1).

## Cutover order

1. Stage OPNsense on a spare NIC/VLAN with a temporary IP. Import aliases from `aliases.csv`.
2. Convert FortiSwitch **S148FFTF23020423 / PEAK-CORE-SW** to standalone. Trunk VLANs 1,100–104 toward OPNsense. Access ports 1–40 stay untagged VLAN 100. Ports 41–42 were AP trunks (`allowed-vlans-all`); keep them tagged 101/102. See `switch-and-wifi.md`.
3. Configure WAN1, WAN2, gateways, gateway group `WAN_LB` (both Tier 1). Enable gateway monitoring (ICMP to 1.1.1.1 / 8.8.8.8).
4. Create VLAN SVIs + DHCP. Add static maps from `dhcp-static-maps.csv`.
5. Add NAT port forwards from `nat-and-firewall.md`. Prefer locking 3389/1433 to VPN or `Akrivia_HR` (`34.87.189.127`) instead of `any`.
6. Add firewall rules in the same order as FortiGate (LAN/WLAN → WAN first, then inter-VLAN, then WAN inbound).
7. Replace SSL VPN with WireGuard (`vpn-wireguard.md`). Users: `binny.andrews` and `admin` in PEAK-VPN-ADMIN. PEAK-VPN-STAFF had **no members**.
8. Recreate captive portal on VLAN 100 with MAC passthrough from `mac-whitelist.csv` if you still want device allowlisting.
9. Move the switch uplink from FortiGate `port12` to the OPNsense LAN NIC. Keep FortiGate powered until DHCP/NAT/VPN are verified.
10. Point inbound ISP routes/forwards (if any) stay on the same public IPs; only the LAN MAC of the gateway changes.

## Files in this folder

| File | Use |
| --- | --- |
| `nics.env` | **Edit first** — set real WAN/WAN2/LAN NIC names |
| `build-opnsense-seed.py` | Builds `peak-seed.xml` after you edit `nics.env` |
| `peak-seed.xml` | Generated seed (interfaces, VLANs, DHCP, NAT, FW, WireGuard) |
| `wireguard/` | Ready peer pack: `binny.andrews.conf`, `admin.conf` |
| `aliases.csv` | Firewall → Aliases → Import |
| `mac-whitelist.csv` | Captive portal MAC passthrough / alias `MAC_WHITELIST` |
| `dhcp-static-maps.csv` | DHCP reservations |
| `nat-and-firewall.md` | Port forwards + rule order |
| `switch-and-wifi.md` | FortiSwitch standalone + FortiAP replacement |
| `vpn-wireguard.md` | SSL VPN replacement notes |
| `webfilter.md` | PEAK-POLICY URL/category stand-in |
| `config-fragment.xml` | Older reference fragment |
| `docs/PEAK-Network-Landscape-and-Migration.docx` | Full Word doc with landscape visuals |
| `docs/images/*.png` | Standalone diagrams (landscape, VLANs, biometric/Keka, OPNsense) |
| `docs/build_documentation.py` | Regenerates the Word file and PNGs |
| `docs/PEAK-Network-Inventory.xlsx` | VLANs, IPs, MACs, DHCP, NAT, switch ports |
| `docs/build_network_inventory_xlsx.py` | Regenerates the Excel inventory |

## Quick start (seed + VPN)

1. On OPNsense, note NIC names under **Interfaces → Assignments**.
2. Edit `nics.env` (`NIC_WAN`, `NIC_WAN2`, `NIC_LAN`).
3. Run `python build-opnsense-seed.py` → writes `peak-seed.xml`.
4. Import `aliases.csv`, then apply the seed carefully (prefer GUI for a live box; full restore only on a fresh install you are willing to wipe).
5. Import `wireguard/binny.andrews.conf` and `wireguard/admin.conf` on your clients.
6. Private keys are secrets — `wireguard/*.conf` and `*.private.key` are listed in `.gitignore`.
