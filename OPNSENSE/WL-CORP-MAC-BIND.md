# Corp Wi‑Fi MAC bind (not guest)

Allowlist built from FortiGate MAC whitelist — **user / laptop / phone MACs only**.  
Printers, TVs, ACS, shared workstations excluded (those stay on wired VLAN 100).

| Metric | Count |
| --- | --- |
| MACs | 103 |
| Users | 29 |
| SSID | PETCPL (VLAN 101) |
| Guest SSID | PETCPL-GUEST — **no MAC filter** (portal password only) |

Files:
- `wl-corp-mac-allowlist.csv` — for Omada import / tracking
- `wl-corp-mac-alias.txt` — paste into OPNsense alias

## Important warning

Modern Windows/iPhone/Android use **randomized Wi‑Fi MACs**. Binding will break when the OS rotates the address unless users disable “Private Wi‑Fi address” for **PETCPL**.

Prefer: ask staff to turn **Private MAC off** for the corp SSID, then capture the real MAC once.

## Option A — Omada (recommended for Wi‑Fi)

1. Omada Controller → **Wireless Networks** → SSID **PETCPL**
2. Enable **MAC Filtering** → **Allow list** (whitelist)
3. Import / add MACs from `wl-corp-mac-allowlist.csv`
4. SSID **PETCPL-GUEST**: leave MAC filter **off**

Unknown MAC cannot associate to corp Wi‑Fi; guest unchanged.

## Option B — OPNsense backup (after DHCP)

1. **Firewall → Aliases** → add `WL_CORP_MACS` type **MAC address**
2. Paste contents of `wl-corp-mac-alias.txt`
3. **Firewall → Rules → opt3 (WL_CORP)** — put **above** the WAN allow:
   - Pass: source MAC alias `WL_CORP_MACS` → any  
   - Block: source WL_CORP net → any (catch-all)
4. Do **not** apply this on opt4 (guest)

Note: MAC filtering in pf is weak (spoofable) and can be awkward with DHCP; Omada allow-list is cleaner for Wi‑Fi.

## After changes

1. On one test laptop: disable private Wi‑Fi MAC for PETCPL → reconnect  
2. Confirm MAC appears in Omada clients / OPNsense leases  
3. Add any missing MAC to the CSV and re-import  

Regenerate: `python build_wl_corp_mac_allowlist.py`
