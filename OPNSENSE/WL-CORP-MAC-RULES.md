# WL_CORP (opt3) — correct MAC bind rule order

**Current live state:** the MAC allow and “block unknown” rules are **disabled**. PETCPL (VLAN 101) is open to any client on `10.80.101.0/24`. The alias `WL_CORP_MACS` is kept so this policy can be turned back on. The table below is that future order, not what is enforcing traffic today.

Use on the **live** firewall. Do not full-restore XML for this.

**Firewall → Rules → WL_CORP** (interface **opt3**)

## Goal
- Only MACs in alias **`WL_CORP_MACS`** get internet (and optionally wired LAN)
- Unknown Wi‑Fi clients on VLAN 101 are blocked
- Guest (**opt4**) unchanged

## Target rule order when the policy is enabled (top → bottom)

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
| `acs` | peakenergy.asia | **10.80.100.10** |
| `app` | peakenergy.asia | **10.80.100.54** |
| `peakpulse-dev` | peakenergy.asia | **10.80.100.54** |

---

## How to verify
1. Listed laptop on **PETCPL**: browse internet + ping `10.80.100.10` if rule 2 is on  
2. Unknown phone on **PETCPL** (or random MAC): no internet; block hits firewall log  
3. **PETCPL-GUEST**: still portal + schedule (opt4 rules untouched)

Apply the three opt3 rules in the GUI. Do not full-restore an old XML to turn this on.

