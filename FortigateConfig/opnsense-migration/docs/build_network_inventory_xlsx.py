#!/usr/bin/env python3
"""Build PEAK network inventory Excel from FortiGate config dump."""
from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT.parent / "PEAK-CORP-FW_7-2_1762_202609160923.conf.yaml"
OUT = Path(__file__).resolve().parent / "PEAK-Network-Inventory.xlsx"

HEADER_FILL = PatternFill("solid", fgColor="1E5AA8")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT = Font(bold=True, size=14, color="1E3A5F")


def load_config() -> str:
    return CONFIG.read_text(encoding="utf-8", errors="replace")


def parse_cidr(ip_mask: str) -> tuple[str, str, str]:
    """10.80.100.1 255.255.255.0 -> ip, mask, prefix"""
    parts = ip_mask.strip().split()
    if len(parts) != 2:
        return ip_mask, "", ""
    ip, mask = parts
    masks = {
        "255.255.255.252": "/30",
        "255.255.255.0": "/24",
        "255.255.255.255": "/32",
    }
    return ip, mask, masks.get(mask, "")


def sheet_header(ws, headers: list[str], row: int = 1) -> None:
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col, value=h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def autofit(ws, max_width: int = 48) -> None:
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        width = max(len(str(c.value or "")) for c in col) + 2
        ws.column_dimensions[letter].width = min(width, max_width)


def add_rows(ws, start_row: int, rows: list[list]) -> None:
    for i, row in enumerate(rows, start_row):
        for j, val in enumerate(row, 1):
            ws.cell(row=i, column=j, value=val)


def section_slice(text: str, start_key: str, end_key: str) -> str:
    start = text.find(start_key)
    if start < 0:
        return ""
    start += len(start_key)
    end = text.find(end_key, start)
    return text[start:end] if end > 0 else text[start:]


def parse_interface_blocks(section: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    current_name = None
    current_lines: list[str] = []
    for line in section.splitlines():
        m = re.match(r"    - ([^:]+):\s*$", line)
        if m:
            if current_name is not None:
                blocks.append((current_name, "\n".join(current_lines)))
            current_name = m.group(1).strip()
            current_lines = []
        elif current_name and line.startswith("        "):
            current_lines.append(line.strip())
    if current_name is not None:
        blocks.append((current_name, "\n".join(current_lines)))
    return blocks


def extract_vlans(text: str) -> list[list]:
    section = section_slice(text, "system_interface:", "system_physical-switch:")
    dhcp_map = {
        "": "10.80.99.2-10",
        "1": "10.80.10.11-20",
        "100": "10.80.100.101-200",
        "101": "10.80.101.101-200",
        "102": "10.80.102.101-200",
        "4088": "10.255.13.2-254",
        "4092": "10.255.12.2-254",
        "4093": "10.255.11.2-254",
    }
    switch_use = {
        "1": "Switch ports 41-52 native/spare",
        "100": "Switch ports 1-40 access; ACS .10, APP .103, biometrics",
        "101": "Wi-Fi PETCPL (AP trunk 41-42)",
        "102": "Wi-Fi PETCPL-GUEST (AP trunk)",
        "103": "Defined on FG; not assigned on switch",
        "104": "Defined on FG; not assigned on switch",
        "4088": "NAC segment (controller)",
        "4089": "NAC onboarding (controller)",
        "4090": "FortiCamera video (controller)",
        "4091": "FortiVoice (controller)",
        "4092": "RSPAN sniffer (controller)",
        "4093": "Quarantine allowed on all switch ports",
    }
    rows: list[list] = []
    for name, body in parse_interface_blocks(section):
        on_fortilink = name == "fortilink" or 'interface: "fortilink"' in body
        if not on_fortilink:
            continue
        vid_m = re.search(r"vlanid: (\d+)", body)
        vid = vid_m.group(1) if vid_m else ("FortiLink" if name == "fortilink" else "")
        ip_m = re.search(r"ip: ([\d.]+ [\d.]+)", body)
        alias_m = re.search(r'alias: "([^"]*)"', body)
        desc_m = re.search(r'description: "([^"]*)"', body)
        if ip_m:
            ip, mask, _ = parse_cidr(ip_m.group(1))
            network = f"{'.'.join(ip.split('.')[:3])}.0/24" if mask == "255.255.255.0" else ""
            gateway = ip
        else:
            ip, mask, network, gateway = "", "", "", ""
        if name == "fortilink":
            vid, ip, mask, network, gateway = "FortiLink", "10.80.99.1", "255.255.255.0", "10.80.99.0/24", "10.80.99.1"
        purpose = desc_m.group(1) if desc_m else switch_use.get(str(vid), "")
        rows.append([
            vid,
            name,
            alias_m.group(1) if alias_m else "",
            ip,
            mask,
            network,
            gateway,
            dhcp_map.get(str(vid), ""),
            "Yes" if str(vid) in dhcp_map else "No",
            purpose,
        ])
    # Physical WAN/mgmt not on fortilink
    for name, body in parse_interface_blocks(section):
        if name in ("wan1", "wan2", "mgmt", "dmz"):
            ip_m = re.search(r"ip: ([\d.]+ [\d.]+)", body)
            alias_m = re.search(r'alias: "([^"]*)"', body)
            ip, mask, _ = parse_cidr(ip_m.group(1)) if ip_m else ("", "", "")
            gw = {"wan1": "125.19.224.17", "wan2": "47.247.169.93"}.get(name, "")
            rows.append([name, name, alias_m.group(1) if alias_m else "", ip, mask, "", gw, "", "No", "Physical interface"])
    return rows


def extract_dhcp(text: str) -> list[list]:
    rows = []
    iface_map = {
        "fortilink": ("FortiLink", "", "10.80.99.1", "10.80.99.2", "10.80.99.10"),
        "quarantine": ("4093", "quarantine", "10.255.11.1", "10.255.11.2", "10.255.11.254"),
        "rspan": ("4092", "rspan", "10.255.12.1", "10.255.12.2", "10.255.12.254"),
        "nac_segment": ("4088", "nac_segment", "10.255.13.1", "10.255.13.2", "10.255.13.254"),
        "_default": ("1", "_default", "10.80.10.1", "10.80.10.11", "10.80.10.20"),
        "WL-CORP": ("101", "WL-CORP", "10.80.101.1", "10.80.101.101", "10.80.101.200"),
        "WL-GUEST": ("102", "WL-GUEST", "10.80.102.1", "10.80.102.101", "10.80.102.200"),
        "WIRED-CORP": ("100", "WIRED-CORP", "10.80.100.1", "10.80.100.101", "10.80.100.200"),
    }
    for iface, (vid, iname, gw, start, end) in iface_map.items():
        lease = "36000" if iname in ("WIRED-CORP", "WL-CORP") else ("300" if vid == "4088" else "default")
        rows.append([vid, iname, iface, gw, start, end, lease, ""])
    # static reservations
    for mac, ip, host in [
        ("4c:d7:17:a4:2a:d0", "10.80.100.101", "PEAK-WS-1"),
        ("4c:d7:17:a4:2b:11", "10.80.100.102", "PEAK-WS-2"),
    ]:
        rows[-2 if host.startswith("PEAK") else -1]  # noop anchor
    return rows


def extract_dhcp_static(text: str) -> list[list]:
    rows = []
    for m in re.finditer(
        r"reserved-address:.*?mac: ([0-9a-f:]+).*?ip: ([\d.]+)",
        text,
        re.DOTALL,
    ):
        mac, ip = m.group(1), m.group(2)
        host = "PEAK-WS-1" if ip.endswith(".101") else "PEAK-WS-2" if ip.endswith(".102") else ""
        rows.append(["100", "WIRED-CORP", ip, mac.lower(), host, "DHCP reservation"])
    return rows


def extract_addresses(text: str) -> list[list]:
    section = section_slice(text, "firewall_address:", "firewall_multicast-address:")
    rows = []
    for name, body in parse_interface_blocks(section.replace("    - ", "    - ", 1)):
        row = parse_address_obj(name, body.split("\n"))
        if row:
            rows.append(row)
    return rows


def parse_address_obj(name: str, lines: list[str]) -> list | None:
    data = {}
    for ln in lines:
        if ":" in ln:
            k, _, v = ln.partition(":")
            data[k.strip()] = v.strip().strip('"')
    if name in ("all", "FABRIC_DEVICE", "FIREWALL_AUTH_PORTAL_ADDRESS"):
        return None
    atype = data.get("type", "subnet")
    vlan = ""
    if data.get("associated-interface"):
        vlan = data["associated-interface"]
    if atype == "mac":
        macs = data.get("macaddr", "").split()
        return None  # handled in MAC sheet
    if atype == "iprange":
        return [name, atype, "", "", f"{data.get('start-ip','')}-{data.get('end-ip','')}", "", vlan, data.get("comment", "")]
    if atype == "fqdn":
        return [name, atype, data.get("fqdn", ""), "", "", "", "", ""]
    if "subnet" in data:
        ip, mask, _ = parse_cidr(data["subnet"])
        return [name, atype, ip, mask, "", "", vlan, data.get("comment", "")]
    return [name, atype, "", "", "", "", vlan, ""]


def extract_mac_addresses(text: str) -> list[list]:
    rows = []
    in_section = False
    current = None
    body: dict[str, str] = {}
    whitelist = set()
    wg = re.search(
        r'MAC WHITELIST:.*?member: "([^"]+)"',
        text,
        re.DOTALL,
    )
    if wg:
        for m in re.findall(r"(_\w+|PEAK[\w-]+|\w+)", wg.group(1)):
            whitelist.add(m)

    for line in text.splitlines():
        if line.startswith("firewall_address:"):
            in_section = True
            continue
        if in_section and line.startswith("firewall_multicast-address:"):
            break
        if not in_section:
            continue
        m = re.match(r"    - ([^:]+):", line)
        if m:
            if current and body.get("type") == "mac":
                for mac in body.get("macaddr", "").split():
                    rows.append([
                        current.lstrip("_"),
                        mac.lower(),
                        body.get("associated-interface", ""),
                        "Yes" if current in whitelist or current.lstrip("_") in whitelist else "No",
                        body.get("comment", ""),
                    ])
            current = m.group(1).strip()
            body = {}
        elif current and line.startswith("        "):
            ln = line.strip()
            if ln.startswith("type:"):
                body["type"] = ln.split(":", 1)[1].strip()
            elif ln.startswith("macaddr:"):
                body["macaddr"] = ln.split(":", 1)[1].strip().strip('"')
            elif ln.startswith("associated-interface:"):
                body["associated-interface"] = ln.split(":", 1)[1].strip().strip('"')
            elif ln.startswith("comment:"):
                body["comment"] = ln.split(":", 1)[1].strip().strip('"')

    if current and body.get("type") == "mac":
        for mac in body.get("macaddr", "").split():
            rows.append([
                current.lstrip("_"),
                mac.lower(),
                body.get("associated-interface", ""),
                "Yes" if current in whitelist or current.lstrip("_") in whitelist else "No",
                body.get("comment", ""),
            ])
    return rows


def extract_hosts(text: str) -> list[list]:
    """Known hosts with IPs — static, VIP targets, infra."""
    rows = [
        ["PEAK-CORP-FW", "FortiGate 100F", "wan1", "125.19.224.18", "/30", "125.19.224.17", "Airtel-FIBER", ""],
        ["PEAK-CORP-FW", "FortiGate 100F", "wan2", "47.247.169.94", "/30", "47.247.169.93", "JIO-RF", ""],
        ["PEAK-CORP-FW", "FortiGate 100F", "mgmt", "192.168.77.99", "/24", "", "Dedicated mgmt", ""],
        ["PEAK-CORP-FW", "FortiGate 100F", "fortilink", "10.80.99.1", "/24", "", "FortiLink port12", ""],
        ["PEAK-CORE-SW", "FortiSwitch 148F", "fortilink", "10.80.99.2", "/24", "10.80.99.1", "S148FFTF23020423", ""],
        ["ACS-SERVER", "Attendance DB", "WIRED-CORP", "10.80.100.10", "/32", "10.80.100.1", "SQL 1433, RDP 3389", ""],
        ["OFFICE_PC / PEAK-APP", "Application", "WIRED-CORP", "10.80.100.103", "/32", "10.80.100.1", "HTTP/HTTPS VIP", ""],
        ["Clone of OFFICE_PC", "Application", "WIRED-CORP", "10.80.100.104", "/32", "10.80.100.1", "", ""],
        ["PEAK-WS-1", "Workstation", "WIRED-CORP", "10.80.100.101", "/32", "10.80.100.1", "DHCP static", "4c:d7:17:a4:2a:d0"],
        ["PEAK-WS-2", "Workstation", "WIRED-CORP", "10.80.100.102", "/32", "10.80.100.1", "DHCP static", "4c:d7:17:a4:2b:11"],
        ["Akrivia_HR", "External cloud", "WAN", "34.87.189.127", "/32", "", "HR/Keka connector (intended)", ""],
        ["OPNsense (planned)", "Firewall staging", "WIRED-CORP", "", "", "10.80.100.1", "MAC 0e:51:d8:1c:e2:01", "0e:51:d8:1c:e2:01"],
        ["AP-001", "FortiAP 431F", "CAPWAP", "", "", "", "FP431FTF23099DUY", ""],
        ["AP-002", "FortiAP 431F", "CAPWAP", "", "", "", "FP431FTF23099DJ8", ""],
        ["AP-003", "FortiAP 431F", "CAPWAP", "", "", "", "FP431FTF23099DHU", ""],
    ]
    # SSL VPN pool
    rows.append(["SSLVPN_POOL", "SSL VPN", "ssl.root", "10.80.200.1-10", "/28", "10.80.200.1", "Remote access pool", ""])
    return rows


def extract_vips(text: str) -> list[list]:
    rows = []
    for m in re.finditer(
        r"    - ([^:]+):\n(?:        .+\n)*?        extip: ([\d.]+)\n(?:        .+\n)*?        mappedip: \"([\d.]+)\"",
        text,
    ):
        name, ext, mapped = m.group(1), m.group(2), m.group(3)
        port_m = re.search(
            rf"    - {re.escape(name)}:.*?(?:extport: (\d+).*?mappedport: (\d+)|)",
            text,
            re.DOTALL,
        )
        extport = mappedport = ""
        block = re.search(rf"    - {re.escape(name)}:((?:\n        .+)+)", text)
        if block:
            extport_m = re.search(r"extport: (\d+)", block.group(1))
            mappedport_m = re.search(r"mappedport: (\d+)", block.group(1))
            if extport_m:
                extport = extport_m.group(1)
            if mappedport_m:
                mappedport = mappedport_m.group(1)
        wan = "Airtel" if ext == "125.19.224.18" else "Jio"
        rows.append([name, wan, ext, extport, mapped, mappedport, "TCP"])
    return rows


def extract_wifi(text: str) -> list[list]:
    return [
        ["PETCPL", "PETCPL", "101", "WL-CORP", "10.80.101.0/24", "always", "Corporate Wi-Fi", "FAP-431F local-bridging"],
        ["PETCPL-GUEST", "PETCPL-GUEST", "102", "WL-GUEST", "10.80.102.0/24", "peak_optimised Mon-Fri 07-19", "Guest Wi-Fi", "FAP-431F local-bridging"],
    ]


def extract_switch_ports(text: str) -> list[list]:
    section = section_slice(text, "switch-controller_managed-switch:", "switch-controller_remote-log:")
    rows: list[list] = []
    current_port = None
    body_lines: list[str] = []
    for line in section.splitlines():
        m = re.match(r"            - (port\d+):\s*$", line)
        if m:
            if current_port:
                rows.append(_parse_switch_port(current_port, body_lines))
            current_port = m.group(1)
            body_lines = []
        elif current_port and line.startswith("                "):
            body_lines.append(line.strip())
    if current_port:
        rows.append(_parse_switch_port(current_port, body_lines))
    return rows


def _parse_switch_port(port: str, lines: list[str]) -> list:
    body = "\n".join(lines)
    vlan = re.search(r'vlan: "([^"]+)"', body)
    allowed_all = "allowed-vlans-all: enable" in body
    allowed = re.search(r'allowed-vlans: "([^"]+)"', body)
    untag = re.search(r'untagged-vlans: "([^"]+)"', body)
    mac = re.search(r"mac-addr: ([0-9a-f:]+)", body)
    poe = "Yes" if "poe-capable: 1" in body else "No"
    num = int(port.replace("port", ""))
    if num <= 40:
        mode, note = "Access", "Users, biometrics, ACS, printers"
    elif num <= 42:
        mode, note = "Trunk (AP)", "FortiAP uplink"
    else:
        mode, note = "Access", "Spare / default VLAN"
    return [
        port,
        num,
        mode,
        vlan.group(1) if vlan else "",
        "ALL" if allowed_all else (allowed.group(1) if allowed else ""),
        untag.group(1) if untag else "",
        poe,
        mac.group(1) if mac else "",
        note,
    ]


def build_workbook() -> Path:
    text = load_config()
    wb = Workbook()

    # --- VLANs ---
    ws = wb.active
    ws.title = "VLANs"
    ws["A1"] = "PEAK VLAN Inventory (FortiGate)"
    ws["A1"].font = TITLE_FONT
    headers = [
        "VLAN ID", "Interface", "Alias", "SVI IP", "Subnet mask", "Network",
        "Gateway", "DHCP range", "DHCP enabled", "Purpose / switch use",
    ]
    sheet_header(ws, headers, 3)
    add_rows(ws, 4, extract_vlans(text))
    autofit(ws)

    # --- Hosts ---
    ws2 = wb.create_sheet("Hosts and IPs")
    ws2["A1"] = "Infrastructure and static hosts"
    ws2["A1"].font = TITLE_FONT
    h2 = ["Hostname", "Device type", "Interface/VLAN", "IP address", "Prefix", "Gateway", "Notes", "MAC"]
    sheet_header(ws2, h2, 3)
    add_rows(ws2, 4, extract_hosts(text))
    autofit(ws2)

    # --- IP address objects ---
    ws3 = wb.create_sheet("Address objects")
    ws3["A1"] = "FortiGate firewall_address (non-MAC)"
    ws3["A1"].font = TITLE_FONT
    h3 = ["Object name", "Type", "IP/FQDN", "Mask", "Range", "Associated VLAN", "Interface", "Comment"]
    sheet_header(ws3, h3, 3)
    add_rows(ws3, 4, extract_addresses(text))
    autofit(ws3)

    # --- MAC addresses ---
    ws4 = wb.create_sheet("MAC addresses")
    ws4["A1"] = "MAC address objects (one row per MAC)"
    ws4["A1"].font = TITLE_FONT
    h4 = ["Owner / object name", "MAC address", "Associated interface", "In MAC WHITELIST", "Comment"]
    sheet_header(ws4, h4, 3)
    mac_rows = extract_mac_addresses(text)
    add_rows(ws4, 4, mac_rows)
    autofit(ws4)

    # --- DHCP ---
    ws5 = wb.create_sheet("DHCP")
    ws5["A1"] = "DHCP scopes and reservations"
    ws5["A1"].font = TITLE_FONT
    h5 = ["VLAN ID", "Interface", "FG interface", "Gateway", "Range start", "Range end", "Lease (sec)", "Notes"]
    sheet_header(ws5, h5, 3)
    add_rows(ws5, 4, extract_dhcp(text))
    start = 4 + len(extract_dhcp(text)) + 2
    ws5.cell(row=start, column=1, value="Static reservations").font = Font(bold=True)
    h5b = ["VLAN ID", "Interface", "IP", "MAC", "Hostname", "Notes"]
    sheet_header(ws5, h5b, start + 1)
    add_rows(ws5, start + 2, extract_dhcp_static(text))
    autofit(ws5)

    # --- NAT VIPs ---
    ws6 = wb.create_sheet("NAT VIPs")
    ws6["A1"] = "Port forwards (public services)"
    ws6["A1"].font = TITLE_FONT
    h6 = ["VIP name", "WAN", "External IP", "Ext port", "Internal IP", "Int port", "Protocol"]
    sheet_header(ws6, h6, 3)
    add_rows(ws6, 4, extract_vips(text))
    autofit(ws6)

    # --- Wi-Fi ---
    ws7 = wb.create_sheet("Wi-Fi")
    ws7["A1"] = "SSID and wireless mapping"
    ws7["A1"].font = TITLE_FONT
    h7 = ["SSID", "VAP name", "VLAN ID", "Interface", "Subnet", "Schedule", "Purpose", "Notes"]
    sheet_header(ws7, h7, 3)
    add_rows(ws7, 4, extract_wifi(text))
    autofit(ws7)

    # --- Switch ports ---
    ws8 = wb.create_sheet("Switch ports")
    ws8["A1"] = "PEAK-CORE-SW port VLAN map"
    ws8["A1"].font = TITLE_FONT
    h8 = ["Port", "Port #", "Mode", "Native VLAN", "Allowed VLANs", "Untagged extra", "PoE", "Switch MAC", "Notes"]
    sheet_header(ws8, h8, 3)
    add_rows(ws8, 4, extract_switch_ports(text))
    autofit(ws8)

    # --- Summary ---
    ws9 = wb.create_sheet("README")
    ws9["A1"] = "PEAK Network Inventory"
    ws9["A1"].font = TITLE_FONT
    notes = [
        f"Source: {CONFIG.name}",
        "Generated from FortiGate 7.2.13 config dump.",
        "",
        "Sheets:",
        "  VLANs — All FortiLink VLANs and SVIs",
        "  Hosts and IPs — Firewall, switch, APs, servers, key static IPs",
        "  Address objects — firewall_address (subnet/FQDN/range, not MAC)",
        "  MAC addresses — One row per MAC; MAC WHITELIST column for captive portal",
        "  DHCP — Scopes on FortiGate + static reservations",
        "  NAT VIPs — Internet port forwards (Keka/ACS, web app)",
        "  Wi-Fi — SSID to VLAN mapping",
        "  Switch ports — All 52 ports on PEAK-CORE-SW",
        "",
        "Not in config dump:",
        "  - FortiAP management IPs (CAPWAP; check live FG GUI)",
        "  - Biometric device IPs (same VLAN 100; no FG objects)",
        "  - Live DHCP leases",
    ]
    for i, n in enumerate(notes, 3):
        ws9.cell(row=i, column=1, value=n)
    ws9.column_dimensions["A"].width = 80

    wb.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build_workbook()
    print(f"Wrote {path}")
