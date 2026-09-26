# FortiSwitch and FortiAP after leaving FortiGate

OPNsense will not manage **PEAK-CORE-SW** (`S148FFTF23020423`) or the three FAP-431F APs.

## FortiSwitch — convert before cutover

While the FortiGate is still managing the switch:

1. Backup the FortiSwitch config (from FortiGate: *WiFi & Switch Controller*).
2. Convert to standalone. Fortinet procedure: on the FortiGate, `execute switch-controller switch-info mac-table` / take notes, then factory-reset the switch **or** use FortiSwitch local admin after `set switch-controller-source standalone` equivalent (GUI: *Convert to FortiSwitch OS standalone*).
3. After standalone, configure 802.1Q to match today:

| Switch ports | Mode | VLAN |
| --- | --- | --- |
| 1–40 | access | untagged 100 (WIRED-CORP) |
| 41–42 | trunk | native 1, tagged 100–104 (AP / allowed-vlans-all) |
| 43–52 | access | untagged 1 (`_default`) |
| FortiLink uplink (was FortiGate port12) | trunk | native 1, tagged 100,101,102,103,104 |

PoE stays on for APs/phones. Management IP of the switch was DHCP `10.80.99.2` on FortiLink `10.80.99.0/24`. After conversion, give the switch a static on VLAN 100 (for example `10.80.100.2`) so you can still reach it from OPNsense.

If conversion fails, a layer-2 dump of the current live ports is: access VLAN 100 on 1–40, AP trunks on 41–42.

## FortiAP 431F — will not work on OPNsense

| AP | Serial | SSID |
| --- | --- | --- |
| AP-001 | FP431FTF23099DUY | PETCPL (VLAN 101), PETCPL-GUEST (VLAN 102) |
| AP-002 | FP431FTF23099DJ8 | same |
| AP-003 | FP431FTF23099DHU | same |

VAPs used **local-bridging** with VLAN tags 101/102, country **IN**. Guest SSID schedule `peak_optimised` (weekdays 07:00–19:00). Passphrases are FortiGate-encrypted; set new ones.

Options:

1. **Replace APs** with Omada/UniFi/OpenWrt, SSIDs PETCPL → VLAN 101, PETCPL-GUEST → VLAN 102, trunks on switch ports 41–42.
2. **Keep a FortiGate only as WLC** (not recommended long-term).
3. **Temporary**: one SSID on a spare OPNsense wireless NIC (poor coverage; 100F-class office has 3× 431F for a reason).

Until APs are replaced, wired VLAN 100 still works; wifi will die at FortiGate power-off.

## Captive portal / guest

- Wired portal + `PEAK-LAN-STAFF` (`peakemp`) + MAC exempt list → OPNsense Captive Portal on VLAN 100, or drop it and rely on switch access VLAN 100.
- Guest account `peakguest` expired **2025-05-31**. Recreate only if still needed.
- Guest isolation: add deny rules from `WL_GUEST` to `LAN_RFC1918` except DNS/DHCP.
