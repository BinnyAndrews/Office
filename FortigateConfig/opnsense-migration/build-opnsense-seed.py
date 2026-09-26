#!/usr/bin/env python3
"""Build an OPNsense seed config from nics.env + WireGuard keys.

This is a *seed*, not a full factory restore. After install:
  1. Edit nics.env with real NIC names from Interfaces → Assignments.
  2. Run: python build-opnsense-seed.py
  3. On OPNsense: System → Configuration → Backups → Restore
     OR copy sections by hand from peak-seed.xml (safer on a live box).

Prefer staging: assign interfaces in the GUI first, then import aliases.csv
and apply NAT/firewall from the seed as a checklist.
"""
from __future__ import annotations

import pathlib
import re
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
ENV = ROOT / "nics.env"
WG_DIR = ROOT / "wireguard"
OUT = ROOT / "peak-seed.xml"


def load_env(path: pathlib.Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def uid() -> str:
    return str(uuid.uuid4())


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main() -> None:
    e = load_env(ENV)
    required = ["NIC_WAN", "NIC_WAN2", "NIC_LAN", "HOSTNAME", "WG_PORT", "WG_ENDPOINT"]
    missing = [k for k in required if not e.get(k)]
    if missing:
        raise SystemExit(f"Missing in nics.env: {', '.join(missing)}")

    for placeholder in ("igb0", "igb1", "igb2"):
        if placeholder in (e["NIC_WAN"], e["NIC_WAN2"], e["NIC_LAN"]):
            print(
                f"WARNING: still using default {placeholder} — "
                "edit nics.env before restoring on production."
            )

    server_priv = (WG_DIR / "server.private.key").read_text(encoding="utf-8").strip()
    server_pub = (WG_DIR / "server.public.key").read_text(encoding="utf-8").strip()
    binny_pub = (WG_DIR / "binny.andrews.public.key").read_text(encoding="utf-8").strip()
    admin_pub = (WG_DIR / "admin.public.key").read_text(encoding="utf-8").strip()

    wg_uuid = uid()
    peer_binny = uid()
    peer_admin = uid()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    mgmt_block = ""
    if e.get("NIC_MGMT"):
        mgmt_block = f"""
    <opt9>
      <if>{esc(e['NIC_MGMT'])}</if>
      <descr>MGMT</descr>
      <enable>1</enable>
      <ipaddr>192.168.77.99</ipaddr>
      <subnet>24</subnet>
      <blockpriv>0</blockpriv>
      <blockbogons>0</blockbogons>
    </opt9>"""

    xml = f"""<?xml version="1.0"?>
<!--
  PEAK-CORP-FW OPNsense seed — generated {now}
  NICs: WAN={esc(e['NIC_WAN'])} WAN2={esc(e['NIC_WAN2'])} LAN={esc(e['NIC_LAN'])}
  DO NOT restore blindly over a production box without reviewing.
  WireGuard server public key: {esc(server_pub)}
-->
<opnsense>
  <system>
    <hostname>{esc(e.get('HOSTNAME', 'PEAK-CORP-FW'))}</hostname>
    <domain>{esc(e.get('DOMAIN', 'peak.local'))}</domain>
    <timezone>{esc(e.get('TIMEZONE', 'Asia/Kolkata'))}</timezone>
    <dnsserver>{esc(e.get('DNS1', '8.8.8.8'))}</dnsserver>
    <dnsserver>{esc(e.get('DNS2', '1.1.1.1'))}</dnsserver>
    <webgui>
      <protocol>https</protocol>
      <port>{esc(e.get('WEBGUI_PORT', '4444'))}</port>
      <ssl-certref>cert1</ssl-certref>
    </webgui>
    <ssh>
      <enabled>enabled</enabled>
      <!-- Permit root login only from LAN; do not expose on WAN -->
    </ssh>
    <language>en_US</language>
  </system>

  <interfaces>
    <wan>
      <if>{esc(e['NIC_WAN'])}</if>
      <descr>WAN_AIRTEL</descr>
      <enable>1</enable>
      <ipaddr>125.19.224.18</ipaddr>
      <subnet>30</subnet>
      <gateway>WAN_AIRTEL</gateway>
      <blockpriv>1</blockpriv>
      <blockbogons>1</blockbogons>
    </wan>
    <opt1>
      <if>{esc(e['NIC_WAN2'])}</if>
      <descr>WAN_JIO</descr>
      <enable>1</enable>
      <ipaddr>47.247.169.94</ipaddr>
      <subnet>30</subnet>
      <gateway>WAN_JIO</gateway>
      <blockpriv>1</blockpriv>
      <blockbogons>1</blockbogons>
      <!-- Mark as WAN in GUI: Interfaces → opt1 → This interface is a WAN -->
    </opt1>
    <lan>
      <if>{esc(e['NIC_LAN'])}</if>
      <descr>LAN_TRUNK</descr>
      <enable>1</enable>
      <!-- Parent only; SVIs live on VLAN interfaces below -->
      <ipaddr>10.80.99.1</ipaddr>
      <subnet>24</subnet>
    </lan>
    <opt2>
      <if>vlan01</if>
      <descr>WIRED_CORP</descr>
      <enable>1</enable>
      <ipaddr>10.80.100.1</ipaddr>
      <subnet>24</subnet>
    </opt2>
    <opt3>
      <if>vlan02</if>
      <descr>WL_CORP</descr>
      <enable>1</enable>
      <ipaddr>10.80.101.1</ipaddr>
      <subnet>24</subnet>
    </opt3>
    <opt4>
      <if>vlan03</if>
      <descr>WL_GUEST</descr>
      <enable>1</enable>
      <ipaddr>10.80.102.1</ipaddr>
      <subnet>24</subnet>
    </opt4>
    <opt5>
      <if>vlan04</if>
      <descr>ACS</descr>
      <enable>1</enable>
      <ipaddr>10.80.103.1</ipaddr>
      <subnet>24</subnet>
    </opt5>
    <opt6>
      <if>vlan05</if>
      <descr>CCTV</descr>
      <enable>1</enable>
      <ipaddr>10.80.104.1</ipaddr>
      <subnet>24</subnet>
    </opt6>
    <opt7>
      <if>vlan06</if>
      <descr>DEFAULT</descr>
      <enable>1</enable>
      <ipaddr>10.80.10.1</ipaddr>
      <subnet>24</subnet>
    </opt7>
    <opt8>
      <if>wg0</if>
      <descr>WIREGUARD</descr>
      <enable>1</enable>
    </opt8>{mgmt_block}
  </interfaces>

  <vlans>
    <vlan>
      <if>{esc(e['NIC_LAN'])}</if>
      <tag>100</tag>
      <vlanif>vlan01</vlanif>
      <descr>WIRED_CORP</descr>
    </vlan>
    <vlan>
      <if>{esc(e['NIC_LAN'])}</if>
      <tag>101</tag>
      <vlanif>vlan02</vlanif>
      <descr>WL_CORP</descr>
    </vlan>
    <vlan>
      <if>{esc(e['NIC_LAN'])}</if>
      <tag>102</tag>
      <vlanif>vlan03</vlanif>
      <descr>WL_GUEST</descr>
    </vlan>
    <vlan>
      <if>{esc(e['NIC_LAN'])}</if>
      <tag>103</tag>
      <vlanif>vlan04</vlanif>
      <descr>ACS</descr>
    </vlan>
    <vlan>
      <if>{esc(e['NIC_LAN'])}</if>
      <tag>104</tag>
      <vlanif>vlan05</vlanif>
      <descr>CCTV</descr>
    </vlan>
    <vlan>
      <if>{esc(e['NIC_LAN'])}</if>
      <tag>1</tag>
      <vlanif>vlan06</vlanif>
      <descr>DEFAULT</descr>
    </vlan>
  </vlans>

  <gateways>
    <gateway_item>
      <interface>wan</interface>
      <gateway>125.19.224.17</gateway>
      <name>WAN_AIRTEL</name>
      <weight>1</weight>
      <ipprotocol>inet</ipprotocol>
      <interval>1</interval>
      <loss_interval>4</loss_interval>
      <descr>Airtel-FIBER (FortiGate wan1)</descr>
      <monitorip>8.8.8.8</monitorip>
      <defaultgw>1</defaultgw>
    </gateway_item>
    <gateway_item>
      <interface>opt1</interface>
      <gateway>47.247.169.93</gateway>
      <name>WAN_JIO</name>
      <weight>1</weight>
      <ipprotocol>inet</ipprotocol>
      <interval>1</interval>
      <descr>JIO-RF (FortiGate wan2)</descr>
      <monitorip>1.1.1.1</monitorip>
    </gateway_item>
    <gateway_group>
      <name>WAN_LB</name>
      <item>WAN_AIRTEL|1|3</item>
      <item>WAN_JIO|1|3</item>
      <trigger>both</trigger>
      <descr>SD-WAN Default_Internet_LB</descr>
    </gateway_group>
  </gateways>

  <dhcpd>
    <opt2>
      <enable></enable>
      <range>
        <from>10.80.100.101</from>
        <to>10.80.100.200</to>
      </range>
      <defaultleasetime>36000</defaultleasetime>
      <gateway>10.80.100.1</gateway>
      <dnsserver>10.80.100.1</dnsserver>
      <staticmap>
        <mac>4c:d7:17:a4:2a:d0</mac>
        <ipaddr>10.80.100.101</ipaddr>
        <hostname>PEAK-WS-1</hostname>
      </staticmap>
      <staticmap>
        <mac>4c:d7:17:a4:2b:11</mac>
        <ipaddr>10.80.100.102</ipaddr>
        <hostname>PEAK-WS-2</hostname>
      </staticmap>
    </opt2>
    <opt3>
      <enable></enable>
      <range>
        <from>10.80.101.101</from>
        <to>10.80.101.200</to>
      </range>
      <defaultleasetime>36000</defaultleasetime>
      <gateway>10.80.101.1</gateway>
      <dnsserver>10.80.101.1</dnsserver>
    </opt3>
    <opt4>
      <enable></enable>
      <range>
        <from>10.80.102.101</from>
        <to>10.80.102.200</to>
      </range>
      <gateway>10.80.102.1</gateway>
      <dnsserver>10.80.102.1</dnsserver>
    </opt4>
    <opt7>
      <enable></enable>
      <range>
        <from>10.80.10.11</from>
        <to>10.80.10.20</to>
      </range>
      <gateway>10.80.10.1</gateway>
      <dnsserver>10.80.10.1</dnsserver>
    </opt7>
  </dhcpd>

  <schedules>
    <schedule>
      <name>peak_optimised</name>
      <descr>Guest SSID window Mon-Fri 07:00-19:00</descr>
      <timerange>
        <position>2,3,4,5,6</position>
        <hour>7:00-19:00</hour>
      </timerange>
    </schedule>
  </schedules>

  <nat>
    <outbound>
      <mode>automatic</mode>
    </outbound>
    <!-- APP HTTP/HTTPS both WANs -->
    <rule>
      <interface>wan</interface>
      <protocol>tcp</protocol>
      <target>10.80.100.103</target>
      <local-port>80</local-port>
      <destination>
        <address>125.19.224.18</address>
        <port>80</port>
      </destination>
      <descr>PEAK-APP-1-Airtel</descr>
      <associated-rule-id></associated-rule-id>
    </rule>
    <rule>
      <interface>wan</interface>
      <protocol>tcp</protocol>
      <target>10.80.100.103</target>
      <local-port>443</local-port>
      <destination>
        <address>125.19.224.18</address>
        <port>443</port>
      </destination>
      <descr>PEAK-APP-2-Airtel</descr>
    </rule>
    <rule>
      <interface>opt1</interface>
      <protocol>tcp</protocol>
      <target>10.80.100.103</target>
      <local-port>80</local-port>
      <destination>
        <address>47.247.169.94</address>
        <port>80</port>
      </destination>
      <descr>PEAK-APP-1-Jio</descr>
    </rule>
    <rule>
      <interface>opt1</interface>
      <protocol>tcp</protocol>
      <target>10.80.100.103</target>
      <local-port>443</local-port>
      <destination>
        <address>47.247.169.94</address>
        <port>443</port>
      </destination>
      <descr>PEAK-APP-2-Jio</descr>
    </rule>
    <!-- ACS SQL/RDP — HARDENED: source AKRIVIA_HR only (not FortiGate any) -->
    <rule>
      <interface>wan</interface>
      <protocol>tcp</protocol>
      <source>
        <address>AKRIVIA_HR</address>
      </source>
      <target>10.80.100.10</target>
      <local-port>1433</local-port>
      <destination>
        <address>125.19.224.18</address>
        <port>1433</port>
      </destination>
      <descr>ACS-SERVER-Airtel</descr>
    </rule>
    <rule>
      <interface>wan</interface>
      <protocol>tcp</protocol>
      <source>
        <address>AKRIVIA_HR</address>
      </source>
      <target>10.80.100.10</target>
      <local-port>3389</local-port>
      <destination>
        <address>125.19.224.18</address>
        <port>3389</port>
      </destination>
      <descr>RDP-ACS-Airtel</descr>
    </rule>
    <rule>
      <interface>opt1</interface>
      <protocol>tcp</protocol>
      <source>
        <address>AKRIVIA_HR</address>
      </source>
      <target>10.80.100.10</target>
      <local-port>1433</local-port>
      <destination>
        <address>47.247.169.94</address>
        <port>1433</port>
      </destination>
      <descr>ACS-SERVER-Jio</descr>
    </rule>
    <rule>
      <interface>opt1</interface>
      <protocol>tcp</protocol>
      <source>
        <address>AKRIVIA_HR</address>
      </source>
      <target>10.80.100.10</target>
      <local-port>3389</local-port>
      <destination>
        <address>47.247.169.94</address>
        <port>3389</port>
      </destination>
      <descr>RDP-ACS-Jio</descr>
    </rule>
  </nat>

  <filter>
    <!-- WireGuard inbound on both WANs -->
    <rule>
      <type>pass</type>
      <interface>wan</interface>
      <ipprotocol>inet</ipprotocol>
      <protocol>udp</protocol>
      <descr>Allow WireGuard</descr>
      <source><any/></source>
      <destination>
        <network>wanip</network>
        <port>{esc(e['WG_PORT'])}</port>
      </destination>
    </rule>
    <rule>
      <type>pass</type>
      <interface>opt1</interface>
      <ipprotocol>inet</ipprotocol>
      <protocol>udp</protocol>
      <descr>Allow WireGuard WAN2</descr>
      <source><any/></source>
      <destination>
        <network>opt1ip</network>
        <port>{esc(e['WG_PORT'])}</port>
      </destination>
    </rule>
    <!-- LAN / WLAN outbound via WAN_LB -->
    <rule>
      <type>pass</type>
      <interface>opt2</interface>
      <ipprotocol>inet</ipprotocol>
      <descr>WIRED_CORP to WAN (FG policy 8)</descr>
      <source><address>WIRED_CORP</address></source>
      <destination><any/></destination>
      <gateway>WAN_LB</gateway>
      <log>1</log>
    </rule>
    <rule>
      <type>pass</type>
      <interface>opt3</interface>
      <ipprotocol>inet</ipprotocol>
      <descr>WL_CORP to WAN (FG policy 8)</descr>
      <source><address>WL_CORP</address></source>
      <destination><any/></destination>
      <gateway>WAN_LB</gateway>
      <log>1</log>
    </rule>
    <rule>
      <type>pass</type>
      <interface>opt4</interface>
      <ipprotocol>inet</ipprotocol>
      <descr>WL_GUEST to WAN (FG policy 8)</descr>
      <source><address>WL_GUEST</address></source>
      <destination><any/></destination>
      <gateway>WAN_LB</gateway>
      <sched>peak_optimised</sched>
      <log>1</log>
    </rule>
    <rule>
      <type>pass</type>
      <interface>opt7</interface>
      <ipprotocol>inet</ipprotocol>
      <descr>DEFAULT VLAN to WAN</descr>
      <source><address>DEFAULT_VLAN</address></source>
      <destination><any/></destination>
      <gateway>WAN_LB</gateway>
    </rule>
    <!-- Inter-VLAN -->
    <rule>
      <type>pass</type>
      <interface>opt2</interface>
      <ipprotocol>inet</ipprotocol>
      <descr>WIRED_CORP to WL_CORP (FG 6)</descr>
      <source><address>WIRED_CORP</address></source>
      <destination><address>WL_CORP</address></destination>
    </rule>
    <rule>
      <type>pass</type>
      <interface>opt3</interface>
      <ipprotocol>inet</ipprotocol>
      <descr>WL_CORP to WIRED_CORP (FG 7)</descr>
      <source><address>WL_CORP</address></source>
      <destination><address>WIRED_CORP</address></destination>
    </rule>
    <!-- WireGuard PEAK-VPN-ADMIN -->
    <rule>
      <type>pass</type>
      <interface>opt8</interface>
      <ipprotocol>inet</ipprotocol>
      <descr>WG ADMIN to all VLANs (FG 4)</descr>
      <source><address>WG_ADMIN_NET</address></source>
      <destination><address>LAN_RFC1918</address></destination>
      <log>1</log>
    </rule>
  </filter>

  <OPNsense>
    <wireguard>
      <server>
        <servers>
          <server uuid="{wg_uuid}">
            <enabled>1</enabled>
            <name>PEAK-WG</name>
            <pubkey>{esc(server_pub)}</pubkey>
            <privkey>{esc(server_priv)}</privkey>
            <port>{esc(e['WG_PORT'])}</port>
            <tunneladdress>10.80.200.1/28</tunneladdress>
            <disableroutes>1</disableroutes>
            <gateway></gateway>
            <carp_depend_on></carp_depend_on>
            <peers>{peer_binny},{peer_admin}</peers>
            <dns>10.80.200.1</dns>
          </server>
        </servers>
      </server>
      <client>
        <clients>
          <client uuid="{peer_binny}">
            <enabled>1</enabled>
            <name>binny.andrews</name>
            <pubkey>{esc(binny_pub)}</pubkey>
            <psk></psk>
            <tunneladdress>10.80.200.2/32</tunneladdress>
            <serveraddress></serveraddress>
            <serverport></serverport>
            <keepalive>25</keepalive>
          </client>
          <client uuid="{peer_admin}">
            <enabled>1</enabled>
            <name>admin</name>
            <pubkey>{esc(admin_pub)}</pubkey>
            <psk></psk>
            <tunneladdress>10.80.200.3/32</tunneladdress>
            <serveraddress></serveraddress>
            <serverport></serverport>
            <keepalive>25</keepalive>
          </client>
        </clients>
      </client>
      <general>
        <enabled>1</enabled>
      </general>
    </wireguard>
  </OPNsense>

  <revision>
    <description>PEAK FortiGate migration seed {esc(now)}</description>
    <time>{esc(now)}</time>
    <username>migration</username>
  </revision>
</opnsense>
"""

    # Soft check: no leftover template markers
    if re.search(r"__NIC_|TODO_NIC", xml):
        raise SystemExit("Unresolved NIC placeholders in output")

    OUT.write_text(xml, encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"WireGuard server public key: {server_pub}")
    print("Next: import aliases.csv in the GUI, then review peak-seed.xml before restore.")


if __name__ == "__main__":
    main()
