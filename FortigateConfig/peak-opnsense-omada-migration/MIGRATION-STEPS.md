# Migration steps — FortiGate → OPNsense + Omada

Do this in order. Keep FortiGate running until step 8 verifies.

---

## Phase 0 — Prep (before maintenance)

1. **Inventory ports** on the old FortiSwitch: list every cable on ports 1–40. Map them onto **24 copper ports** on SG2428P (plus SFP uplink).
2. **Label cables**: ACS server, APP/OFFICE_PC, biometrics ×2, printers, workstations, AP-001/002/003 locations.
3. **Confirm static hosts still at:**
   - ACS / attendance DB: `10.80.100.10`
   - PEAK-APP / OFFICE_PC: `10.80.100.103`
   - Optional: PEAK-WS-1/2 reservations `.101` / `.102`
4. **Ask Keka/Akrivia** for their source IP(s) for SQL pull (today object was `34.87.189.127`; policy was open to the world — we will lock it).
5. **Rack** OPNsense, SG2428P, 3× EAP670, Omada controller (or install software controller).
6. **Buy** matching copper/SFP as needed (copper SFP module if OPNsense LAN is RJ45 into switch SFP).

---

## Phase 1 — Build OPNsense (parallel to production)

1. Fresh install OPNsense (latest stable). Complete installer wizard with a **temporary** LAN IP (e.g. `192.168.1.1`) if needed.
2. Open **Interfaces → Assignments**. Write down:
   - NIC for Airtel → `NIC_WAN`
   - NIC for Jio → `NIC_WAN2`
   - NIC for switch trunk → `NIC_LAN`
3. Edit `opnsense/nics.env` with those names.
4. Run: `python opnsense/build_config_xml.py`
5. Restore `opnsense/config.xml` per `opnsense/RESTORE.md`.
6. After restore, connect a laptop to VLAN 100 (or temporary access port), open `https://10.80.100.1:4444`.
7. Verify:
   - Gateways WAN_AIRTEL / WAN_JIO / group WAN_LB online (when ISPs plugged in — can wait)
   - DHCP scopes on VLAN 100/101/102
   - Aliases present
   - Port forwards listed (do not publish RDP)
8. Set a strong **root** password and create an admin user. Do **not** allow GUI/SSH from WAN.

---

## Phase 2 — Omada controller + SG2428P

1. Install/adopt **Omada Controller** (OC200/OC300 or software).
2. Factory-reset SG2428P if needed; adopt into controller.
3. Configure VLANs and ports exactly as in `omada/SWITCH-SG2428P.md`.
4. Set switch management IP: **`10.80.100.2/24`**, gateway `10.80.100.1`.
5. Uplink: **SFP1** (or copper port 24) → OPNsense LAN as **trunk** (tagged 100,101,102; native/untagged 100 optional).
6. Access ports 1–20: untagged VLAN **100**.
7. Ports 21–23: **trunk** for EAP670 (untagged 100 or 1; tagged 101,102).
8. Confirm OPNsense can ping `10.80.100.2` when both are on the same test segment.

---

## Phase 3 — EAP670 × 3

1. Mount APs in the **same locations** as FortiAP AP-001/002/003 if possible.
2. Connect to switch ports **21, 22, 23** (PoE).
3. Adopt APs in Omada controller.
4. Create SSIDs per `omada/WIFI-EAP670.md`:
   - **PETCPL** → VLAN **101**
   - **PETCPL-GUEST** → VLAN **102**, schedule Mon–Fri 07:00–19:00
5. Set new Wi‑Fi passwords (FortiGate passphrases cannot be recovered).
6. Test from a phone: join PETCPL → get `10.80.101.x` from OPNsense DHCP → ping `10.80.101.1`.

---

## Phase 4 — Parallel validation (FortiGate still live)

1. Keep production on FortiGate.
2. On a **test** laptop/cable on the Omada switch VLAN 100:
   - DHCP from OPNsense
   - Ping ACS `10.80.100.10` (if ACS still only on Forti side, skip until cutover)
3. Prefer moving **one non-critical device** to Omada switch overnight if cabling allows.

---

## Phase 5 — Maintenance window cutover

**Expected downtime:** 30–90 minutes depending on cabling.

1. Announce outage.
2. On FortiGate: note current WAN status; take final backup.
3. **Move ISP handoffs:**
   - Airtel → OPNsense `NIC_WAN`
   - Jio → OPNsense `NIC_WAN2`
4. **Move LAN uplink:** Omada trunk → OPNsense `NIC_LAN` (disconnect FortiGate FortiLink).
5. **Move critical cables** from FortiSwitch to SG2428P:
   - ACS `10.80.100.10` → VLAN 100 access
   - APP `10.80.100.103`
   - Biometrics ×2
   - Remaining PCs/printers as planned
6. Power off FortiGate / FortiSwitch / FortiAPs (or leave powered but disconnected).
7. Verify checklist below.

---

## Phase 6 — Post-cutover checks

| Check | Expected |
| --- | --- |
| OPNsense gateways | WAN_AIRTEL and WAN_JIO online / WAN_LB OK |
| Wired PC | DHCP `10.80.100.x`, internet works |
| PETCPL | DHCP `10.80.101.x`, internet |
| PETCPL-GUEST | DHCP `10.80.102.x` only in schedule window |
| ACS | Ping `10.80.100.10`; punches still store |
| Keka / Akrivia | SQL sync via public IP `:1433` (confirm with vendor) |
| App | `http(s)://` public VIP → `10.80.100.103` |
| Switch mgmt | Reach `10.80.100.2` from LAN |
| Omada controller | APs online |
| Security | No WAN access to OPNsense `:4444` / SSH |

---

## Phase 7 — Harden & clean up

1. Confirm ACS VIP source limited to Keka/Akrivia IPs (see CONFIGURABLE-ITEMS).
2. **Do not** recreate public RDP 3389.
3. Update any DNS / bookmarks that pointed at FortiGate.
4. Keep FortiGate offline 1–2 weeks as rollback insurance, then decommission.
5. Cancel FortiGate license renewal when stable.

---

## Rollback (if cutover fails)

1. Move Airtel/Jio cables back to FortiGate wan1/wan2.
2. Reconnect FortiSwitch FortiLink to FortiGate port12.
3. Power FortiAPs as before.
4. Leave Omada powered but unused until next attempt.
