# Unbound — peakenergy.asia

These are the live DNS settings. Do not full-restore an XML just to change a name. Edit the override in the GUI.

## 1. System → Settings → General
- Domain: **peakenergy.asia**
- DNS servers: **8.8.8.8**, **1.1.1.1** (keep)

## 2. Services → Unbound DNS → General
| Setting | Value |
| --- | --- |
| Enable | Yes |
| Listen interfaces | lan, opt2, opt3, opt4, **opt6** (WIREGUARD — required for VPN DNS `10.80.200.1`) |
| Local Zone Type | **transparent** |
| Register DHCP leases | Yes |
| DHCP Domain Override | peakenergy.asia |
| Register DHCP static mappings | Yes |

Save → Apply.

## 3. Services → Unbound DNS → Query Forwarding
- **Use System Nameservers**: Yes  
  (uses 8.8.8.8 / 1.1.1.1 — O365 / internet DNS)

## 4. Services → Unbound DNS → Overrides
| Host | Domain | Type | IP |
| --- | --- | --- | --- |
| fw | peakenergy.asia | A | 10.80.99.1 |
| peak-corp-fw | peakenergy.asia | A | 10.80.99.1 |
| fw-corp | peakenergy.asia | A | 10.80.100.1 |
| acs | peakenergy.asia | A | 10.80.100.10 |
| oc200 | peakenergy.asia | A | 10.80.99.3 |
| app | peakenergy.asia | A | 10.80.100.54 |
| peakpulse-dev | peakenergy.asia | A | 10.80.100.54 |

Do **not** add autodiscover / mail / www.

## 5. Kea DHCP (each subnet)
- Domain name: **peakenergy.asia**
- Domain search: **peakenergy.asia**
- DNS servers: that VLAN’s gateway (already set)

## 6. Test (from a corp laptop after renew)
```text
nslookup fw.peakenergy.asia
nslookup outlook.office365.com
ping fw.peakenergy.asia
```

Outlook/Teams should still work. `fw.peakenergy.asia` → 10.80.99.1.

Script used when these overrides were first loaded: `configure_unbound_peakenergy.py`
