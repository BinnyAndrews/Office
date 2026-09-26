#!/usr/bin/env python3
"""
Build a restore-ready OPNsense config.xml for PEAK:
  OPNsense firewall + Omada SG2428P + EAP670
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = ROOT / "nics.env"
OUT = ROOT / "config.xml"


def load_env(path: Path) -> dict[str, str]:
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


def alias_xml(name: str, atype: str, address: str, descr: str) -> str:
    return f"""    <alias uuid="{uid()}">
      <enabled>1</enabled>
      <name>{esc(name)}</name>
      <type>{esc(atype)}</type>
      <proto></proto>
      <interface></interface>
      <counters>0</counters>
      <updatefreq></updatefreq>
      <content>{esc(address)}</content>
      <descr>{esc(descr)}</descr>
    </alias>
"""


def filter_rule(
    tracker: int,
    interface: str,
    descr: str,
    source: str,
    destination: str = "any",
    gateway: str = "",
    schedule: str = "",
    protocol: str = "any",
    log: bool = True,
) -> str:
    """source/destination: 'any' or alias/network name."""
    if source == "any":
        src = "<any>1</any>"
    else:
        src = f"<address>{esc(source)}</address>"
    if destination == "any":
        dst = "<any>1</any>"
    else:
        dst = f"<address>{esc(destination)}</address>"
    gw = f"<gateway>{esc(gateway)}</gateway>" if gateway else "<gateway></gateway>"
    sched = f"<sched>{esc(schedule)}</sched>" if schedule else "<sched></sched>"
    log_xml = "<log>1</log>" if log else "<log></log>"
    return f"""    <rule uuid="{uid()}">
      <type>pass</type>
      <interface>{esc(interface)}</interface>
      <ipprotocol>inet</ipprotocol>
      <protocol>{esc(protocol)}</protocol>
      <statetype>keep state</statetype>
      <direction>in</direction>
      <quick>1</quick>
      <floating>0</floating>
      <descr>{esc(descr)}</descr>
      <source>{src}</source>
      <destination>{dst}</destination>
      {gw}
      {sched}
      {log_xml}
      <enabled>1</enabled>
      <category></category>
    </rule>
"""


def nat_rule(
    interface: str,
    descr: str,
    target: str,
    local_port: str,
    dest_port: str,
    source_alias: str = "",
) -> str:
    src = ""
    if source_alias:
        src = f"""      <source>
        <address>{esc(source_alias)}</address>
      </source>"""
    else:
        src = """      <source>
        <any>1</any>
      </source>"""
    return f"""    <rule uuid="{uid()}">
      <protocol>tcp</protocol>
      <interface>{esc(interface)}</interface>
      <ipprotocol>inet</ipprotocol>
      <target>{esc(target)}</target>
      <local-port>{esc(local_port)}</local-port>
{src}
      <destination>
        <network>{esc(interface)}ip</network>
        <port>{esc(dest_port)}</port>
      </destination>
      <descr>{esc(descr)}</descr>
      <associated-rule-id></associated-rule-id>
      <natreflection>purenat</natreflection>
      <enabled>1</enabled>
    </rule>
"""


def main() -> None:
    e = load_env(ENV)
    required = ["NIC_WAN", "NIC_WAN2", "NIC_LAN", "HOSTNAME"]
    missing = [k for k in required if not e.get(k)]
    if missing:
        raise SystemExit(f"Missing in nics.env: {', '.join(missing)}")

    for key, default in [
        ("WAN_AIRTEL_IP", "125.19.224.18"),
        ("WAN_AIRTEL_GW", "125.19.224.17"),
        ("WAN_AIRTEL_BITS", "30"),
        ("WAN_JIO_IP", "47.247.169.94"),
        ("WAN_JIO_GW", "47.247.169.93"),
        ("WAN_JIO_BITS", "30"),
        ("AKRIVIA_HR", "34.87.189.127"),
        ("WEBGUI_PORT", "4444"),
        ("TIMEZONE", "Asia/Kolkata"),
        ("DNS1", "8.8.8.8"),
        ("DNS2", "1.1.1.1"),
        ("DOMAIN", "peak.local"),
    ]:
        e.setdefault(key, default)

    wan, wan2, lan = e["NIC_WAN"], e["NIC_WAN2"], e["NIC_LAN"]
    # OPNsense-style VLAN if names
    v100, v101, v102 = f"{lan}_vlan100", f"{lan}_vlan101", f"{lan}_vlan102"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    aliases = "".join(
        [
            alias_xml("WIRED_CORP", "network", "10.80.100.0/24", "VLAN 100 wired"),
            alias_xml("WL_CORP", "network", "10.80.101.0/24", "VLAN 101 Wi-Fi corp"),
            alias_xml("WL_GUEST", "network", "10.80.102.0/24", "VLAN 102 guest Wi-Fi"),
            alias_xml("ACS_SERVER", "host", "10.80.100.10", "Attendance / ACS SQL"),
            alias_xml("OFFICE_PC", "host", "10.80.100.103", "PEAK-APP"),
            alias_xml("AKRIVIA_HR", "host", e["AKRIVIA_HR"], "Keka/Akrivia source — update if needed"),
            alias_xml("LAN_RFC1918", "network", "10.80.0.0/16", "PEAK internal"),
            alias_xml("OMADA_SWITCH", "host", "10.80.100.2", "SG2428P management"),
        ]
    )

    filters = "".join(
        [
            filter_rule(1001, "opt2", "WIRED_CORP to Internet", "WIRED_CORP", "any", "WAN_LB"),
            filter_rule(1002, "opt3", "WL_CORP to Internet", "WL_CORP", "any", "WAN_LB"),
            filter_rule(1003, "opt4", "WL_GUEST to Internet", "WL_GUEST", "any", "WAN_LB", "peak_optimised"),
            filter_rule(1004, "opt2", "WIRED_CORP to WL_CORP", "WIRED_CORP", "WL_CORP"),
            filter_rule(1005, "opt3", "WL_CORP to WIRED_CORP", "WL_CORP", "WIRED_CORP"),
            # Guest isolation: block guest to internal (before any other guest pass — already only WAN pass above)
            f"""    <rule uuid="{uid()}">
      <type>block</type>
      <interface>opt4</interface>
      <ipprotocol>inet</ipprotocol>
      <protocol>any</protocol>
      <direction>in</direction>
      <quick>1</quick>
      <descr>Block WL_GUEST to internal RFC1918</descr>
      <source><address>WL_GUEST</address></source>
      <destination><address>LAN_RFC1918</address></destination>
      <gateway></gateway>
      <sched></sched>
      <log>1</log>
      <enabled>1</enabled>
    </rule>
""",
        ]
    )

    # Put guest block BEFORE guest WAN pass for correctness — rebuild order
    filters = "".join(
        [
            filter_rule(1001, "opt2", "WIRED_CORP to Internet", "WIRED_CORP", "any", "WAN_LB"),
            filter_rule(1002, "opt3", "WL_CORP to Internet", "WL_CORP", "any", "WAN_LB"),
            f"""    <rule uuid="{uid()}">
      <type>block</type>
      <interface>opt4</interface>
      <ipprotocol>inet</ipprotocol>
      <protocol>any</protocol>
      <direction>in</direction>
      <quick>1</quick>
      <descr>Block WL_GUEST to internal networks</descr>
      <source><address>WL_GUEST</address></source>
      <destination><address>LAN_RFC1918</address></destination>
      <log>1</log>
      <enabled>1</enabled>
    </rule>
""",
            filter_rule(1003, "opt4", "WL_GUEST to Internet", "WL_GUEST", "any", "WAN_LB", "peak_optimised"),
            filter_rule(1004, "opt2", "WIRED_CORP to WL_CORP", "WIRED_CORP", "WL_CORP"),
            filter_rule(1005, "opt3", "WL_CORP to WIRED_CORP", "WL_CORP", "WIRED_CORP"),
        ]
    )

    nats = "".join(
        [
            nat_rule("wan", "PEAK-APP-HTTP-Airtel", "10.80.100.103", "80", "80"),
            nat_rule("wan", "PEAK-APP-HTTPS-Airtel", "10.80.100.103", "443", "443"),
            nat_rule("opt1", "PEAK-APP-HTTP-Jio", "10.80.100.103", "80", "80"),
            nat_rule("opt1", "PEAK-APP-HTTPS-Jio", "10.80.100.103", "443", "443"),
            nat_rule("wan", "ACS-SQL-Airtel", "10.80.100.10", "1433", "1433", "AKRIVIA_HR"),
            nat_rule("opt1", "ACS-SQL-Jio", "10.80.100.10", "1433", "1433", "AKRIVIA_HR"),
        ]
    )

    xml = f"""<?xml version="1.0"?>
<!--
  PEAK OPNsense config — Omada SG2428P + EAP670 migration
  Generated: {now}
  NICs: WAN={esc(wan)} WAN2={esc(wan2)} LAN={esc(lan)}
  Restore on a FRESH install after editing nics.env and rebuilding.
  GUI: https://10.80.100.1:{esc(e['WEBGUI_PORT'])} from VLAN 100
-->
<opnsense>
  <trigger_initial_wizard>0</trigger_initial_wizard>
  <system>
    <optimization>normal</optimization>
    <hostname>{esc(e['HOSTNAME'])}</hostname>
    <domain>{esc(e['DOMAIN'])}</domain>
    <timezone>{esc(e['TIMEZONE'])}</timezone>
    <language>en_US</language>
    <dnsserver>{esc(e['DNS1'])}</dnsserver>
    <dnsserver>{esc(e['DNS2'])}</dnsserver>
    <dnsallowoverride>1</dnsallowoverride>
    <webgui>
      <protocol>https</protocol>
      <port>{esc(e['WEBGUI_PORT'])}</port>
      <ssl-certref></ssl-certref>
      <interfaces>lan,opt2</interfaces>
    </webgui>
    <ssh>
      <group>admins</group>
      <interfaces>lan,opt2</interfaces>
      <enabled>enabled</enabled>
    </ssh>
    <firmware>
      <mirror></mirror>
      <flavour></flavour>
    </firmware>
    <disablenatreflection>yes</disablenatreflection>
    <enableallowallwan>0</enableallowallwan>
  </system>

  <interfaces>
    <wan>
      <if>{esc(wan)}</if>
      <descr>WAN_AIRTEL</descr>
      <enable>1</enable>
      <lock>1</lock>
      <ipaddr>{esc(e['WAN_AIRTEL_IP'])}</ipaddr>
      <subnet>{esc(e['WAN_AIRTEL_BITS'])}</subnet>
      <gateway>WAN_AIRTEL</gateway>
      <blockpriv>1</blockpriv>
      <blockbogons>1</blockbogons>
    </wan>
    <lan>
      <if>{esc(lan)}</if>
      <descr>LAN_TRUNK_PARENT</descr>
      <enable>1</enable>
      <ipaddr>none</ipaddr>
      <subnet></subnet>
    </lan>
    <opt1>
      <if>{esc(wan2)}</if>
      <descr>WAN_JIO</descr>
      <enable>1</enable>
      <ipaddr>{esc(e['WAN_JIO_IP'])}</ipaddr>
      <subnet>{esc(e['WAN_JIO_BITS'])}</subnet>
      <gateway>WAN_JIO</gateway>
      <blockpriv>1</blockpriv>
      <blockbogons>1</blockbogons>
      <type>wan</type>
    </opt1>
    <opt2>
      <if>{esc(v100)}</if>
      <descr>WIRED_CORP</descr>
      <enable>1</enable>
      <ipaddr>10.80.100.1</ipaddr>
      <subnet>24</subnet>
    </opt2>
    <opt3>
      <if>{esc(v101)}</if>
      <descr>WL_CORP</descr>
      <enable>1</enable>
      <ipaddr>10.80.101.1</ipaddr>
      <subnet>24</subnet>
    </opt3>
    <opt4>
      <if>{esc(v102)}</if>
      <descr>WL_GUEST</descr>
      <enable>1</enable>
      <ipaddr>10.80.102.1</ipaddr>
      <subnet>24</subnet>
    </opt4>
  </interfaces>

  <vlans>
    <vlan uuid="{uid()}">
      <if>{esc(lan)}</if>
      <tag>100</tag>
      <pcp></pcp>
      <proto></proto>
      <vlanif>{esc(v100)}</vlanif>
      <descr>WIRED_CORP</descr>
    </vlan>
    <vlan uuid="{uid()}">
      <if>{esc(lan)}</if>
      <tag>101</tag>
      <pcp></pcp>
      <proto></proto>
      <vlanif>{esc(v101)}</vlanif>
      <descr>WL_CORP</descr>
    </vlan>
    <vlan uuid="{uid()}">
      <if>{esc(lan)}</if>
      <tag>102</tag>
      <pcp></pcp>
      <proto></proto>
      <vlanif>{esc(v102)}</vlanif>
      <descr>WL_GUEST</descr>
    </vlan>
  </vlans>

  <gateways>
    <gateway_item uuid="{uid()}">
      <disabled>0</disabled>
      <name>WAN_AIRTEL</name>
      <interface>wan</interface>
      <gateway>{esc(e['WAN_AIRTEL_GW'])}</gateway>
      <defaultgw>1</defaultgw>
      <fargw>0</fargw>
      <monitor_disable>0</monitor_disable>
      <monitorip>8.8.8.8</monitorip>
      <interval>1</interval>
      <weight>1</weight>
      <ipprotocol>inet</ipprotocol>
      <descr>Airtel-FIBER</descr>
    </gateway_item>
    <gateway_item uuid="{uid()}">
      <disabled>0</disabled>
      <name>WAN_JIO</name>
      <interface>opt1</interface>
      <gateway>{esc(e['WAN_JIO_GW'])}</gateway>
      <defaultgw>0</defaultgw>
      <monitor_disable>0</monitor_disable>
      <monitorip>1.1.1.1</monitorip>
      <interval>1</interval>
      <weight>1</weight>
      <ipprotocol>inet</ipprotocol>
      <descr>JIO-RF</descr>
    </gateway_item>
    <gateway_group uuid="{uid()}">
      <name>WAN_LB</name>
      <descr>Dual-WAN load balance (FortiGate SD-WAN replacement)</descr>
      <trigger>both</trigger>
      <item>WAN_AIRTEL|1|3</item>
      <item>WAN_JIO|1|3</item>
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
      <maxleasetime>72000</maxleasetime>
      <gateway>10.80.100.1</gateway>
      <dnsserver>10.80.100.1</dnsserver>
      <domain>{esc(e['DOMAIN'])}</domain>
      <staticmap>
        <mac>4c:d7:17:a4:2a:d0</mac>
        <ipaddr>10.80.100.101</ipaddr>
        <hostname>PEAK-WS-1</hostname>
        <descr>DHCP reservation from FortiGate</descr>
      </staticmap>
      <staticmap>
        <mac>4c:d7:17:a4:2b:11</mac>
        <ipaddr>10.80.100.102</ipaddr>
        <hostname>PEAK-WS-2</hostname>
        <descr>DHCP reservation from FortiGate</descr>
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
      <domain>{esc(e['DOMAIN'])}</domain>
    </opt3>
    <opt4>
      <enable></enable>
      <range>
        <from>10.80.102.101</from>
        <to>10.80.102.200</to>
      </range>
      <gateway>10.80.102.1</gateway>
      <dnsserver>10.80.102.1</dnsserver>
      <domain>{esc(e['DOMAIN'])}</domain>
    </opt4>
  </dhcpd>

  <unbound>
    <enable>1</enable>
    <active_interface>opt2,opt3,opt4</active_interface>
    <outgoing_interface></outgoing_interface>
    <port>53</port>
    <hideidentity>1</hideidentity>
    <hideversion>1</hideversion>
  </unbound>

  <schedules>
    <schedule>
      <name>peak_optimised</name>
      <descr>Guest Wi-Fi window Mon-Fri 07:00-19:00</descr>
      <timerange>
        <position>2,3,4,5,6</position>
        <hour>7:00-19:00</hour>
        <rangedescr>Weekdays business hours</rangedescr>
      </timerange>
    </schedule>
  </schedules>

  <nat>
    <outbound>
      <mode>automatic</mode>
    </outbound>
{nats}
  </nat>

  <filter>
{filters}
  </filter>

  <OPNsense>
    <Firewall>
      <Alias version="1.0.0">
{aliases}      </Alias>
    </Firewall>
  </OPNsense>

  <rrd>
    <enable></enable>
  </rrd>

  <syslog>
    <nologdefaultblock></nologdefaultblock>
  </syslog>

  <revision>
    <description>PEAK Omada+OPNsense migration {esc(now)}</description>
    <time>{esc(now)}</time>
    <username>migration</username>
  </revision>
</opnsense>
"""

    OUT.write_text(xml, encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"  WAN={wan}  WAN2={wan2}  LAN={lan}")
    print(f"  VLANs: {v100}, {v101}, {v102}")
    print("Next: System > Configuration > Backups > Restore this file on fresh OPNsense.")
    if wan.startswith("igb") and wan == "igb0":
        print("WARNING: still using default igb0/igb1/igb2 — edit nics.env for your hardware.")


if __name__ == "__main__":
    main()
