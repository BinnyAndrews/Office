# Web filter stand-in for PEAK-POLICY

FortiGate LAN→WAN used profile **PEAK-POLICY**: certificate inspection + default AV + this URL table + FortiGuard categories.

## Explicit URL list (urlfilter table 1)

Block:

- www.netflix.com
- www.primevideo.com
- www.hotstar.com
- www.zee5.com
- www.instagram.com

Allow (exceptions):

- www.indian-designs.com
- wattpower.in
- unifiedportal-mem.epfindia.gov.in/memberinterface/
- www.sebi.gov.in
- ceisiec.com

## FortiGuard categories on PEAK-POLICY

Block: 61 Malicious Websites, 83 Child Abuse, 86 Phishing, 88 Spam URLs, 96 Proxy Avoidance, 98 Cryptomining, 99 PUP.

Warn (treat as allow+log on OPNsense unless you install Zenarmor): 2, 7, 8, 9, 11, 13, 14, 15, 16, 57, 63, 64, 65, 66, 67 (adult, gambling, ads, file sharing, etc.).

Monitor/allow: remaining categories including 1, 3–6, 12, 26, 59, 62.

FortiGuard categories have no 1:1 OPNsense object. Closest stack:

1. **Unbound DNSBL** (Services → Unbound → Blocklist): enable malware/phishing lists; add the five block FQDNs as custom block; add the five allow FQDNs to Unbound access lists / whitelist.
2. **Suricata IDS/IPS** on WAN (and optionally VLAN 100): ET Open rules for malware/phishing. This is not HTTP category filtering.
3. **Zenarmor** (plugin): application/category policy closest to FortiGuard. Use this if you need Instagram/Netflix/Hotstar as apps rather than DNS names (apps use CDNs; DNS block is leaky).
4. Drop FortiGate **certificate-inspection** unless you deploy a TLS inspect CA to every endpoint. OPNsense TLS inspection is optional via plugins and is operationally heavy.

AV on FortiGate was `default`. OPNsense equivalent is optional ClamAV + ICAP or Zenarmor; most offices skip gateway AV and keep endpoint AV.
