# WL_CORP (opt3) — correct MAC bind rule order

Use on the **live** firewall. Do not full-restore XML for this.

**Firewall → Rules → WL_CORP** (interface **opt3**)

## Goal
- Only MACs in alias **`WL_CORP_MACS`** get internet (and optionally wired LAN)
- Unknown Wi‑Fi clients on VLAN 101 are blocked
- Guest (**opt4**) unchanged

## Current problems (from backup audit)
1. A **block** rule on source `WL_CORP_MACS` (wrong — blocks your allow list)
2. **Pass** `WL_CORP` → `WIRED_CORP` still allows any MAC on opt3
3. Open internet rule for `WL_CORP` is already disabled — keep it disabled/deleted

---

## Target rule order (top → bottom)

| # | Action | Interface | Source | Destination | Gateway | Schedule | Description |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Pass** | WL_CORP | **WL_CORP_MACS** | any | **WAN_LB** | — | Allow listed Wi‑Fi MACs to Internet |
| 2 | **Pass** | WL_CORP | **WL_CORP_MACS** | **WIRED_CORP** | default | — | Allow listed Wi‑Fi MACs to wired LAN |
| 3 | **Pass** | WL_CORP | **WL_CORP_MACS** | **MGMT** | default | — | Optional: listed MACs to MGMT (omit if not needed) |
| 4 | **Block** | WL_CORP | **WL_CORP** | any | — | — | Block unknown Wi‑Fi clients (log = on) |

All rules: IPv4, direction **in**, quick/default as usual, **log** the block.

### Do this in the GUI
1. **Delete or disable** any rule: Action **Block**, Source **WL_CORP_MACS**
2. **Delete or disable** any rule: Action **Pass**, Source **WL_CORP**, Dest **any** (internet) — keep disabled
3. **Edit** “WL_CORP to WIRED_CORP”: change Source from `WL_CORP` → **`WL_CORP_MACS`**
4. **Ensure** one Pass exists: Source **`WL_CORP_MACS`**, Dest **any**, Gateway **WAN_LB**
5. **Add** Block: Source **`WL_CORP`**, Dest **any**, Description `Block unknown WL_CORP MACs`
6. Drag so order matches the table (MAC passes **above** the block)
7. **Apply**

### Optional — also fix Unbound while you’re in the GUI
**Services → Unbound → Overrides**
| Host | Domain | IP |
| --- | --- | --- |
| `acs` | peakenergy.asia | **10.80.100.10** (fix if it points at .103) |
| `app` | peakenergy.asia | **10.80.100.103** |

---

## How to verify
1. Listed laptop on **PETCPL**: browse internet + ping `10.80.100.10` if rule 2 is on  
2. Unknown phone on **PETCPL** (or random MAC): no internet; block hits firewall log  
3. **PETCPL-GUEST**: still portal + schedule (opt4 rules untouched)

## Updated XML (firewall rules fixed)

File: **`C:\tools\PEAK-CORP-FW\config-PEAK-CORP-FW-macfix.xml`**  
(also copied to `config-PEAK-CORP-FW.xml`)

Built from your live backup `config-PEAK-CORP-FW.peakenergy.asia-20260918121107.xml` with:
- opt3: Pass `WL_CORP_MACS` → any (WAN_LB)
- opt3: Pass `WL_CORP_MACS` → WIRED_CORP
- opt3: Block `WL_CORP` → any (unknown MACs)
- Removed broken Block-on-`WL_CORP_MACS` and open `WL_CORP` internet pass
- Unbound: `acs` → 10.80.100.10, `app` → 10.80.100.103

**Caution:** This box panicked on a prior full restore. Prefer applying the three opt3 rules in the GUI (table above). Use full restore of `*-macfix.xml` only if you have console/serial ready.

