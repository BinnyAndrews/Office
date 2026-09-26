#!/usr/bin/env python3
"""Generate PEAK network landscape PNGs and a Word documentation pack."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
IMG = ROOT / "images"
OUT = ROOT / "PEAK-Network-Landscape-and-Migration.docx"

# Palette (flat, print-friendly)
BG = (248, 249, 251)
INK = (28, 32, 40)
MUTED = (90, 98, 110)
LINE = (180, 186, 196)
WAN = (30, 90, 160)
LAN = (20, 120, 90)
WARN = (160, 90, 20)
DANGER = (150, 40, 40)
BOX = (255, 255, 255)
BOX_ALT = (235, 240, 248)
ACCENT = (40, 100, 170)


def font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def new_canvas(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (w, h), BG)
    return img, ImageDraw.Draw(img)


def rounded(draw, xy, fill, outline=LINE, width=2, radius=12):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def box(draw, x, y, w, h, title, lines=None, fill=BOX, title_color=INK, outline=LINE):
    rounded(draw, (x, y, x + w, y + h), fill=fill, outline=outline)
    draw.text((x + 14, y + 10), title, font=font(16, True), fill=title_color)
    if lines:
        ty = y + 36
        for line in lines:
            draw.text((x + 14, ty), line, font=font(13), fill=MUTED)
            ty += 20


def arrow(draw, x1, y1, x2, y2, color=INK, label=None):
    draw.line((x1, y1, x2, y2), fill=color, width=3)
    # simple arrow head
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        draw.polygon(
            [
                (x2, y2),
                (x2 - 10 * direction, y2 - 6),
                (x2 - 10 * direction, y2 + 6),
            ],
            fill=color,
        )
    else:
        direction = 1 if y2 > y1 else -1
        draw.polygon(
            [
                (x2, y2),
                (x2 - 6, y2 - 10 * direction),
                (x2 + 6, y2 - 10 * direction),
            ],
            fill=color,
        )
    if label:
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        draw.text((mx + 6, my - 16), label, font=font(12), fill=color)


def caption(draw, text, y, w):
    draw.text((24, y), text, font=font(12), fill=MUTED)


def diagram_landscape() -> Path:
    img, d = new_canvas(1400, 900)
    d.text((24, 18), "PEAK Corporate Network Landscape (Current — FortiGate)", font=font(22, True), fill=INK)
    d.text((24, 50), "Source: PEAK-CORP-FW FortiOS 7.2.13 · FG100F", font=font(13), fill=MUTED)

    # ISPs
    box(d, 40, 100, 220, 100, "Airtel Fiber (wan1)", ["125.19.224.18/30", "GW 125.19.224.17", "Preferred SD-WAN"], fill=BOX_ALT, title_color=WAN)
    box(d, 40, 230, 220, 100, "Jio RF (wan2)", ["47.247.169.94/30", "GW 47.247.169.93", "Load-balance member"], fill=BOX_ALT, title_color=WAN)

    # FortiGate
    box(d, 340, 140, 280, 160, "FortiGate 100F", [
        "Hostname: PEAK-CORP-FW",
        "SD-WAN virtual-wan-link",
        "Admin HTTPS :4444",
        "FortiLink on port12",
        "DNS 8.8.8.8 / 1.1.1.1",
    ], outline=WAN, title_color=WAN)

    arrow(d, 260, 150, 340, 190, WAN, "WAN1")
    arrow(d, 260, 280, 340, 260, WAN, "WAN2")

    # Switch
    box(d, 700, 120, 300, 200, "FortiSwitch PEAK-CORE-SW", [
        "S148FFTF23020423",
        "Ports 1–40: access VLAN 100",
        "Ports 41–42: AP trunks",
        "Ports 43–52: access VLAN 1",
        "PoE for APs / endpoints",
        "Mgmt was 10.80.99.2 (FortiLink)",
    ], outline=LAN, title_color=LAN)

    arrow(d, 620, 220, 700, 220, LAN, "FortiLink")

    # Downstream devices
    devices = [
        (40, 420, 250, 130, "Biometric × 2", ["On switch access ports", "VLAN 100 WIRED-CORP", "Talk to ACS 10.80.100.10", "No special FW VIP"], WARN),
        (320, 420, 250, 130, "ACS / Attendance DB", ["Host 10.80.100.10", "SQL :1433 published", "RDP :3389 published", "VLAN 100"], DANGER),
        (600, 420, 250, 130, "Office / App hosts", ["10.80.100.103 APP", "10.80.100.104 clone", "HTTP/HTTPS VIPs", "Workstations + printers"], LAN),
        (880, 420, 250, 130, "FortiAP 431F × 3", ["AP-001 / 002 / 003", "SSID PETCPL → VLAN 101", "SSID PETCPL-GUEST → 102", "Country IN"], ACCENT),
        (1160, 420, 200, 130, "Staff / Guest", ["Wired VLAN 100", "Wi‑Fi corp 101", "Guest 102 (07–19)", "MAC whitelist"], MUTED),
    ]
    for x, y, w, h, title, lines, color in devices:
        box(d, x, y, w, h, title, lines, title_color=color, outline=color)

    arrow(d, 800, 320, 165, 420, WARN)
    arrow(d, 850, 320, 445, 420, DANGER)
    arrow(d, 900, 320, 725, 420, LAN)
    arrow(d, 950, 320, 1005, 420, ACCENT)

    # Cloud
    box(d, 1040, 100, 320, 160, "Internet / Cloud HR", [
        "VIP targets on both WANs",
        "Akrivia_HR object 34.87.189.127",
        "Policy source today: ANY",
        "Keka not named in FG config",
        "Pulls attendance via SQL path",
    ], fill=(255, 245, 240), outline=DANGER, title_color=DANGER)
    arrow(d, 620, 180, 1040, 180, DANGER, "1433 / 80 / 443 / 3389")

    caption(d, "Figure 1 — Current production landscape. Biometrics and ACS share VLAN 100; cloud HR reaches ACS over published MSSQL.", 860, 1400)
    path = IMG / "01-landscape-current.png"
    img.save(path, "PNG")
    return path


def diagram_vlans() -> Path:
    img, d = new_canvas(1200, 720)
    d.text((24, 18), "VLAN and Subnet Map", font=font(22, True), fill=INK)
    d.text((24, 50), "SVIs on FortiGate FortiLink · trunk to PEAK-CORE-SW", font=font(13), fill=MUTED)

    rows = [
        ("100", "WIRED-CORP", "10.80.100.0/24", "10.80.100.1", "101–200", "Wired staff, ACS .10, APP .103, printers, biometrics"),
        ("101", "WL-CORP", "10.80.101.0/24", "10.80.101.1", "101–200", "SSID PETCPL (corporate Wi‑Fi)"),
        ("102", "WL-GUEST", "10.80.102.0/24", "10.80.102.1", "101–200", "SSID PETCPL-GUEST · schedule Mon–Fri 07:00–19:00"),
        ("103", "ACS-VLAN", "10.80.103.0/24", "10.80.103.1", "none", "Defined but unused on switch ports"),
        ("104", "CCTV-VLAN", "10.80.104.0/24", "10.80.104.1", "none", "Defined but unused on switch ports"),
        ("1", "_default", "10.80.10.0/24", "10.80.10.1", "11–20", "Leftover access ports 43–52"),
        ("—", "FortiLink", "10.80.99.0/24", "10.80.99.1", "2–10", "Switch mgmt (controller mode)"),
        ("—", "SSL VPN", "10.80.200.1–10", "ssl.root", "pool", "Remote admin/staff (→ WireGuard on OPNsense)"),
    ]

    headers = ["VLAN", "Name", "Network", "Gateway", "DHCP", "Purpose"]
    widths = [70, 140, 160, 130, 100, 480]
    x0, y0 = 24, 100
    # header
    x = x0
    for h, w in zip(headers, widths):
        rounded(d, (x, y0, x + w - 4, y0 + 36), ACCENT, outline=ACCENT, radius=6)
        d.text((x + 10, y0 + 8), h, font=font(13, True), fill=(255, 255, 255))
        x += w
    y = y0 + 44
    for i, row in enumerate(rows):
        x = x0
        fill = BOX if i % 2 == 0 else BOX_ALT
        for cell, w in zip(row, widths):
            rounded(d, (x, y, x + w - 4, y + 48), fill, radius=6)
            d.text((x + 10, y + 14), cell, font=font(12), fill=INK)
            x += w
        y += 54

    caption(d, "Figure 2 — Logical networks. Production endpoints live mainly on VLAN 100; Wi‑Fi on 101/102.", 670, 1200)
    path = IMG / "02-vlan-map.png"
    img.save(path, "PNG")
    return path


def diagram_biometric() -> Path:
    img, d = new_canvas(1300, 780)
    d.text((24, 18), "Biometric Attendance → ACS → External HR (Keka / Akrivia)", font=font(22, True), fill=INK)
    d.text((24, 50), "Inferred from FortiGate objects/policies — Keka is not named in the config", font=font(13), fill=MUTED)

    box(d, 40, 120, 220, 140, "Biometric machine 1", ["Connected to FortiSwitch", "Access VLAN 100", "Same L2 as ACS server"], title_color=WARN, outline=WARN)
    box(d, 40, 300, 220, 140, "Biometric machine 2", ["Connected to FortiSwitch", "Access VLAN 100", "Punch events → ACS app"], title_color=WARN, outline=WARN)

    box(d, 360, 180, 280, 180, "ACS attendance server", [
        "IP 10.80.100.10",
        "VLAN 100 WIRED-CORP",
        "Holds attendance DB",
        "SQL Server listening :1433",
        "RDP :3389 for admin",
    ], title_color=DANGER, outline=DANGER)

    arrow(d, 260, 190, 360, 250, WARN, "LAN / same VLAN")
    arrow(d, 260, 370, 360, 300, WARN, "LAN / same VLAN")

    box(d, 740, 120, 260, 120, "FortiGate VIP", [
        "Both WANs publish :1433",
        "Airtel 125.19.224.18",
        "Jio 47.247.169.94",
    ], title_color=WAN, outline=WAN)
    arrow(d, 640, 250, 740, 180, WAN, "DNAT")

    box(d, 740, 300, 260, 140, "Policy Akrivia_HR>LAN", [
        "WAN → ACS VIPs",
        "Also allows RDP :3389",
        "srcaddr today: all",
        "Object Akrivia_HR unused",
    ], fill=(255, 245, 240), title_color=DANGER, outline=DANGER)

    box(d, 1060, 180, 200, 180, "External HR", [
        "Akrivia (named)",
        "and/or Keka",
        "Pulls DB / sync",
        "Not configured",
        "inside FortiGate",
    ], fill=BOX_ALT, title_color=ACCENT, outline=ACCENT)
    arrow(d, 1000, 180, 1060, 240, ACCENT, "Internet")
    arrow(d, 1000, 370, 1060, 300, ACCENT)

    # notes
    rounded(d, (40, 500, 1260, 700), BOX, outline=LINE)
    d.text((60, 520), "Operational notes", font=font(16, True), fill=INK)
    notes = [
        "1. Device-to-server path never traverses firewall policies (same VLAN 100 broadcast domain).",
        "2. ACS-VLAN 10.80.103.0/24 exists on the FortiGate but switch ports are not assigned to it — biometrics are on VLAN 100.",
        "3. Keka integration settings live in Keka admin / ACS vendor software, not in this FortiGate dump.",
        "4. Security: SQL 1433 and RDP 3389 are currently reachable from the entire Internet on both public IPs — lock to vendor IPs on OPNsense.",
        "5. Address object Akrivia_HR (34.87.189.127) was likely intended as the cloud source but is not referenced by the policy source field.",
    ]
    ty = 555
    for n in notes:
        d.text((60, ty), n, font=font(13), fill=MUTED)
        ty += 26

    caption(d, "Figure 3 — Attendance data path. FortiGate only mediates the Internet → SQL/RDP exposure.", 720, 1300)
    path = IMG / "03-biometric-keka.png"
    img.save(path, "PNG")
    return path


def diagram_services() -> Path:
    img, d = new_canvas(1200, 700)
    d.text((24, 18), "Published Services (NAT / VIP)", font=font(22, True), fill=INK)

    services = [
        ("PEAK-APP HTTP", "80", "10.80.100.103", "both WANs", "Web app"),
        ("PEAK-APP HTTPS", "443", "10.80.100.103", "both WANs", "Web app"),
        ("ACS SQL", "1433", "10.80.100.10", "both WANs", "Attendance DB pull"),
        ("ACS RDP", "3389", "10.80.100.10", "both WANs", "Server admin (risk)"),
        ("SSL VPN", "443/custom", "ssl.root pool", "wan1+wan2", "Remote access"),
        ("Admin GUI", "4444", "FortiGate", "WAN allowaccess", "Do not copy to OPNsense"),
    ]
    headers = ["Service", "Port", "Internal", "External", "Purpose"]
    widths = [180, 120, 180, 180, 420]
    x0, y0 = 24, 90
    x = x0
    for h, w in zip(headers, widths):
        rounded(d, (x, y0, x + w - 4, y0 + 36), ACCENT, outline=ACCENT, radius=6)
        d.text((x + 10, y0 + 8), h, font=font(13, True), fill=(255, 255, 255))
        x += w
    y = y0 + 44
    for i, row in enumerate(services):
        x = x0
        danger = row[1] in ("1433", "3389", "4444")
        fill = (255, 240, 240) if danger else (BOX if i % 2 == 0 else BOX_ALT)
        for cell, w in zip(row, widths):
            rounded(d, (x, y, x + w - 4, y + 52), fill, radius=6)
            d.text((x + 10, y + 16), cell, font=font(13), fill=DANGER if danger else INK)
            x += w
        y += 58

    caption(d, "Figure 4 — Internet-facing services. Red rows should be restricted or removed on OPNsense.", 640, 1200)
    path = IMG / "04-published-services.png"
    img.save(path, "PNG")
    return path


def diagram_opnsense() -> Path:
    img, d = new_canvas(1400, 820)
    d.text((24, 18), "Target Landscape — OPNsense Migration", font=font(22, True), fill=INK)
    d.text((24, 50), "Router/firewall only · FortiSwitch standalone · APs replaced or re-homed", font=font(13), fill=MUTED)

    box(d, 40, 100, 220, 100, "Airtel", ["wan · 125.19.224.18/30", "GW WAN_AIRTEL"], fill=BOX_ALT, title_color=WAN)
    box(d, 40, 230, 220, 100, "Jio", ["opt1 · 47.247.169.94/30", "GW WAN_JIO"], fill=BOX_ALT, title_color=WAN)

    box(d, 340, 130, 300, 180, "OPNsense", [
        "Gateway group WAN_LB",
        "VLANs 100–104 on LAN NIC",
        "DHCP + aliases imported",
        "WireGuard 10.80.200.1/28",
        "GUI :4444 LAN only",
        "No FortiLink / FortiAP",
    ], outline=ACCENT, title_color=ACCENT)
    arrow(d, 260, 150, 340, 190, WAN)
    arrow(d, 260, 280, 340, 260, WAN)

    box(d, 720, 110, 300, 200, "PEAK-CORE-SW (standalone)", [
        "Trunk to OPNsense LAN",
        "Tagged 1,100–104",
        "1–40 untagged 100",
        "41–42 AP trunks",
        "Mgmt e.g. 10.80.100.2",
    ], outline=LAN, title_color=LAN)
    arrow(d, 640, 220, 720, 220, LAN, "802.1Q trunk")

    box(d, 1080, 100, 280, 120, "Replacement Wi‑Fi", [
        "Omada / UniFi / other",
        "PETCPL → VLAN 101",
        "GUEST → VLAN 102",
        "FortiAP will not join OPN",
    ], fill=(255, 248, 230), outline=WARN, title_color=WARN)

    box(d, 1080, 250, 280, 120, "WireGuard clients", [
        "binny.andrews .2",
        "admin .3",
        "Split tunnel 10.80.0.0/16",
        "Endpoint :51820 UDP",
    ], outline=ACCENT, title_color=ACCENT)

    box(d, 200, 420, 280, 140, "Biometrics + ACS", [
        "Stay on VLAN 100",
        "ACS 10.80.100.10",
        "Re-create VIP :1433",
        "Lock source to vendor IP",
    ], title_color=WARN, outline=WARN)
    box(d, 520, 420, 280, 140, "Apps / office", [
        "VIP 80/443 → .103",
        "DHCP reservations",
        "MAC whitelist optional",
    ], title_color=LAN, outline=LAN)
    box(d, 840, 420, 320, 140, "Does not migrate", [
        "FortiGuard PEAK-POLICY",
        "Cert inspection / FG AV",
        "Encrypted passwords",
        "FortiAP controller + FortiLink",
    ], fill=(255, 240, 240), title_color=DANGER, outline=DANGER)

    arrow(d, 870, 310, 340, 420, WARN)
    arrow(d, 900, 310, 660, 420, LAN)

    caption(d, "Figure 5 — Post-cutover architecture. Convert the switch before moving the uplink; replace APs separately.", 760, 1400)
    path = IMG / "05-opnsense-target.png"
    img.save(path, "PNG")
    return path


def diagram_inventory() -> Path:
    img, d = new_canvas(1200, 780)
    d.text((24, 18), "Device Inventory Snapshot", font=font(22, True), fill=INK)

    groups = [
        (40, 90, "Security / Routing", [
            "FortiGate 100F — PEAK-CORP-FW",
            "Serial context FG100FTK23085575",
            "OPNsense staging MAC 0e:51:d8:1c:e2:01",
        ]),
        (420, 90, "Switching", [
            "FortiSwitch 148F — PEAK-CORE-SW",
            "S148FFTF23020423",
            "FortiLink peer today",
        ]),
        (800, 90, "Wireless", [
            "FAP-431F AP-001 FP431FTF23099DUY",
            "FAP-431F AP-002 FP431FTF23099DJ8",
            "FAP-431F AP-003 FP431FTF23099DHU",
        ]),
        (40, 280, "Servers / Apps (VLAN 100)", [
            "ACS / attendance 10.80.100.10",
            "PEAK-APP / OFFICE_PC 10.80.100.103",
            "Clone OFFICE_PC 10.80.100.104",
            "DHCP reservations .101 / .102",
        ]),
        (420, 280, "Identity / Access", [
            "Local users: binny.andrews, admin, peakemp",
            "Groups: PEAK-VPN-ADMIN, PEAK-LAN-STAFF",
            "MAC WHITELIST (~35 people/devices)",
            "Guest peakguest (expired May 2025)",
        ]),
        (800, 280, "External", [
            "Airtel + Jio dual WAN",
            "Akrivia_HR 34.87.189.127",
            "Keka (external SaaS — not in FG)",
            "FQDN allows: ceisiec.com, etc.",
        ]),
        (40, 500, "Endpoints (examples)", [
            "Workstations, printers, TVs (MAC objects)",
            "Conference PEAK801-IN-CONF",
            "TrueNAS MAC e0:51:d8:1c:e0:cb",
            "Biometric × 2 (switch-connected)",
        ]),
        (420, 500, "Policies (7)", [
            "8 LAN>WAN NAT",
            "4/5 SSL-VPN admin/staff",
            "6/7 WIRED ↔ WL-CORP",
            "9/10 WAN inbound VIPs",
        ]),
        (800, 500, "Migration kit", [
            "opnsense-migration/",
            "aliases, DHCP, NAT docs",
            "WireGuard peer pack",
            "peak-seed.xml builder",
        ]),
    ]
    for x, y, title, lines in groups:
        box(d, x, y, 340, 160, title, lines, title_color=ACCENT, outline=LINE)

    caption(d, "Figure 6 — Inventory derived from FortiGate config dump dated 2026-09-16.", 720, 1200)
    path = IMG / "06-inventory.png"
    img.save(path, "PNG")
    return path


def set_cell_shading(cell, color_hex: str):
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color_hex)
    shading.set(qn("w:val"), "clear")
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(shading)


def add_heading_styled(doc, text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        run.font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)
    return p


def add_para(doc, text, bold=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(11)
    run.font.name = "Calibri"
    run.bold = bold
    return p


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(10)
        set_cell_shading(cell, "1E5AA8")
        for p in cell.paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(255, 255, 255)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = str(val)
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)
            if ri % 2:
                set_cell_shading(cell, "F0F4F8")
    doc.add_paragraph()
    return table


def build_docx(images: dict[str, Path]) -> Path:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(0.85)
    section.right_margin = Inches(0.85)

    # Cover
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("PEAK Corporate Network")
    r.bold = True
    r.font.size = Pt(28)
    r.font.color.rgb = RGBColor(0x1E, 0x5A, 0xA8)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("Landscape, Devices, Attendance Integration &\nFortiGate → OPNsense Migration Guide")
    r.font.size = Pt(14)
    r.font.color.rgb = RGBColor(0x5A, 0x62, 0x6E)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = meta.add_run(
        "Source config: PEAK-CORP-FW_7-2_1762_202609160923.conf.yaml\n"
        "Appliance: FortiGate 100F · FortiOS 7.2.13 build 1762\n"
        "Document generated for migration planning"
    )
    r.font.size = Pt(10)
    r.font.color.rgb = RGBColor(0x5A, 0x62, 0x6E)

    doc.add_page_break()

    # TOC-ish
    add_heading_styled(doc, "Contents", 1)
    for item in [
        "1. Executive summary",
        "2. Current network landscape (visual)",
        "3. Device inventory",
        "4. VLAN and addressing plan",
        "5. Dual WAN and SD-WAN",
        "6. Firewall policies and NAT",
        "7. Biometric attendance, ACS, Akrivia and Keka",
        "8. Wireless and FortiSwitch",
        "9. Remote access (SSL VPN → WireGuard)",
        "10. Security findings",
        "11. OPNsense target architecture",
        "12. Cutover checklist",
        "13. File annex (migration kit)",
    ]:
        add_para(doc, item)

    doc.add_page_break()

    # 1
    add_heading_styled(doc, "1. Executive summary", 1)
    add_para(
        doc,
        "PEAK operates a FortiGate 100F (hostname PEAK-CORP-FW) as the edge firewall with dual ISP "
        "connectivity (Airtel fiber and Jio RF), a FortiSwitch core (PEAK-CORE-SW), and three FortiAP 431F "
        "access points. Corporate wired and wireless networks use VLANs 100–102. An attendance/ACS server "
        "at 10.80.100.10 on the wired corporate VLAN stores biometric punch data; that database is exposed "
        "to the Internet on TCP 1433 so an external HR stack (Akrivia named in the firewall; Keka used "
        "operationally) can pull attendance.",
    )
    add_para(
        doc,
        "OPNsense can replace the FortiGate as router/firewall, but cannot run FortiLink or FortiAP "
        "controller functions. The FortiSwitch must be converted to standalone and wireless APs must be "
        "replaced or re-homed before a full cutover. A migration kit under opnsense-migration/ provides "
        "aliases, DHCP maps, NAT/firewall mapping, WireGuard peers, and a fill-in-the-NICs seed XML.",
    )

    # 2
    add_heading_styled(doc, "2. Current network landscape", 1)
    add_para(doc, "Figure 1 shows ISPs, FortiGate, switch, major device classes, and cloud HR exposure.")
    doc.add_picture(str(images["landscape"]), width=Inches(6.5))
    last = doc.paragraphs[-1]
    last.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 3
    add_heading_styled(doc, "3. Device inventory", 1)
    doc.add_picture(str(images["inventory"]), width=Inches(6.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    add_heading_styled(doc, "3.1 Core infrastructure", 2)
    add_table(
        doc,
        ["Role", "Device", "Identity / addressing", "Notes"],
        [
            ["Firewall", "FortiGate 100F", "PEAK-CORP-FW", "Admin HTTPS :4444"],
            ["Core switch", "FortiSwitch 148F", "PEAK-CORE-SW / S148FFTF23020423", "FortiLink managed"],
            ["AP", "FAP-431F", "AP-001 FP431FTF23099DUY", "Remote WTP"],
            ["AP", "FAP-431F", "AP-002 FP431FTF23099DJ8", "Remote WTP"],
            ["AP", "FAP-431F", "AP-003 FP431FTF23099DHU", "Remote WTP"],
            ["Staging", "OPNsense", "MAC 0e:51:d8:1c:e2:01", "Already present as FG object"],
        ],
    )

    add_heading_styled(doc, "3.2 Servers and key hosts (VLAN 100)", 2)
    add_table(
        doc,
        ["Host", "IP", "Role"],
        [
            ["ACS / attendance", "10.80.100.10", "Biometric DB; SQL 1433 + RDP 3389 published"],
            ["OFFICE_PC / PEAK-APP", "10.80.100.103", "HTTP/HTTPS VIP target"],
            ["Clone of OFFICE_PC", "10.80.100.104", "Secondary host object"],
            ["PEAK-WS-1", "10.80.100.101", "DHCP reservation 4c:d7:17:a4:2a:d0"],
            ["PEAK-WS-2", "10.80.100.102", "DHCP reservation 4c:d7:17:a4:2b:11"],
        ],
    )

    add_heading_styled(doc, "3.3 Endpoints called out in config", 2)
    add_para(
        doc,
        "Two biometric attendance machines are connected to the FortiSwitch (access VLAN 100). They are "
        "not individually named as firewall address objects; they reach the ACS server on the same LAN. "
        "Staff devices appear as MAC address objects inside the MAC WHITELIST group used by the wired "
        "captive-portal exempt list. Printers, meeting-room TVs, conference PC, and TrueNAS are also "
        "represented as MAC objects.",
    )

    # 4
    add_heading_styled(doc, "4. VLAN and addressing plan", 1)
    doc.add_picture(str(images["vlans"]), width=Inches(6.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_para(
        doc,
        "Inter-VLAN allow rules exist only between WIRED-CORP and WL-CORP. Guest, ACS-VLAN, CCTV, and "
        "default VLAN have no east-west permits beyond what same-interface routing would require—and "
        "ACS/CCTV VLANs are unused on the switch today.",
    )

    # 5
    add_heading_styled(doc, "5. Dual WAN and SD-WAN", 1)
    add_table(
        doc,
        ["Member", "Interface", "Address", "Gateway", "Role"],
        [
            ["2 (preferred)", "wan1 Airtel-FIBER", "125.19.224.18/30", "125.19.224.17", "Priority in LB service"],
            ["1", "wan2 JIO-RF", "47.247.169.94/30", "47.247.169.93", "Second LB member"],
        ],
    )
    add_para(
        doc,
        "SD-WAN service Default_Internet_LB uses load-balance mode with SLA Default_DNS (latency 250 ms, "
        "jitter 50 ms, loss 5%). Default route uses sdwan-zone virtual-wan-link. On OPNsense this becomes "
        "gateway group WAN_LB with monitoring to 8.8.8.8 / 1.1.1.1.",
    )

    # 6
    add_heading_styled(doc, "6. Firewall policies and NAT", 1)
    doc.add_picture(str(images["services"]), width=Inches(6.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    add_heading_styled(doc, "6.1 IPv4 policies", 2)
    add_table(
        doc,
        ["ID", "Name", "From → To", "Action / NAT", "Notes"],
        [
            ["8", "LAN > WAN", "VLAN 1/100/101/102 → SD-WAN", "Accept + NAT", "UTM + PEAK-POLICY webfilter"],
            ["6", "WIRED → WL-CORP", "100 → 101", "Accept", "Inter-VLAN"],
            ["7", "WL-CORP → WIRED", "101 → 100", "Accept", "Reverse of 6"],
            ["4", "SSL-VPN ADMIN", "ssl.root → LAN VLANs", "Accept", "Group PEAK-VPN-ADMIN"],
            ["5", "SSL-VPN USER", "ssl.root → 100/101", "Accept", "Group PEAK-VPN-STAFF (empty)"],
            ["9", "Akrivia_HR>LAN", "WAN → ACS VIPs", "Accept + NAT", "1433/3389; src=all"],
            ["10", "WAN > WiredCorp", "WAN → APP VIPs", "Accept", "80/443 to .103"],
        ],
    )

    add_heading_styled(doc, "6.2 VIP / port forwards", 2)
    add_table(
        doc,
        ["VIP", "External", "Port", "Internal"],
        [
            ["PEAK-APP-1-Airtel / Jio", "Both WAN IPs", "80", "10.80.100.103"],
            ["PEAK-APP-2-Airtel / Jio", "Both WAN IPs", "443", "10.80.100.103"],
            ["ACS-SERVER-Airtel / Jio", "Both WAN IPs", "1433", "10.80.100.10"],
            ["RDP of ACS-SERVER-*", "Both WAN IPs", "3389", "10.80.100.10"],
        ],
    )

    # 7
    add_heading_styled(doc, "7. Biometric attendance, ACS, Akrivia and Keka", 1)
    doc.add_picture(str(images["biometric"]), width=Inches(6.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    add_heading_styled(doc, "7.1 How it works on site", 2)
    add_para(
        doc,
        "The two biometric machines connect to the FortiSwitch on normal access ports (VLAN 100). "
        "Punch data is sent to the ACS/attendance application on 10.80.100.10. Because devices and server "
        "share the same VLAN, this traffic does not require a FortiGate firewall policy.",
    )
    add_heading_styled(doc, "7.2 How external HR pulls data", 2)
    add_para(
        doc,
        "The FortiGate publishes Microsoft SQL Server port 1433 from both public WAN addresses to "
        "10.80.100.10. Policy Akrivia_HR>LAN permits that path (and RDP 3389). An address object "
        "Akrivia_HR (34.87.189.127) exists but is not used as the policy source—the source is all.",
    )
    add_heading_styled(doc, "7.3 Where Keka fits", 2)
    add_para(
        doc,
        "Keka does not appear anywhere in the FortiGate configuration. Operationally, Keka is the HR "
        "application that consumes attendance. That usually means either (a) Akrivia/ACS middleware syncs "
        "to Keka, or (b) a Keka connector reaches the on-prem SQL database through the published VIP. "
        "Confirm the exact connector URL/IP inside Keka admin and the ACS vendor console—those settings "
        "are outside this firewall dump.",
    )
    add_heading_styled(doc, "7.4 Unused ACS VLAN", 2)
    add_para(
        doc,
        "Interface ACS-VLAN (VLAN 103, 10.80.103.0/24) is defined on the FortiGate, but switch ports are "
        "not assigned to it. Do not assume biometrics use VLAN 103 unless you change switch config later.",
    )

    # 8
    add_heading_styled(doc, "8. Wireless and FortiSwitch", 1)
    add_table(
        doc,
        ["SSID", "VLAN", "Schedule", "Notes"],
        [
            ["PETCPL", "101", "always", "Corporate Wi‑Fi, local-bridging"],
            ["PETCPL-GUEST", "102", "peak_optimised Mon–Fri 07:00–19:00", "Guest; passphrase encrypted in dump"],
        ],
    )
    add_para(
        doc,
        "Switch port summary: 1–40 untagged VLAN 100; 41–42 trunks (allowed-vlans-all) for APs; "
        "43–52 untagged VLAN 1. Converting the switch to standalone is mandatory before OPNsense cutover.",
    )

    # 9
    add_heading_styled(doc, "9. Remote access", 1)
    add_para(
        doc,
        "FortiGate SSL VPN listens on wan1 and wan2 with pool 10.80.200.1–10. PEAK-VPN-ADMIN members are "
        "binny.andrews and admin (full LAN including ACS/CCTV). PEAK-VPN-STAFF has no members. "
        "The migration kit replaces this with WireGuard on 10.80.200.0/28 (client configs for both admins). "
        "OpenVPN remains an option if FortiClient must be retained.",
    )

    # 10
    add_heading_styled(doc, "10. Security findings", 1)
    add_table(
        doc,
        ["Finding", "Risk", "Recommendation"],
        [
            ["SQL 1433 open to Internet on both WANs", "High", "Restrict to Keka/Akrivia source IPs or VPN only"],
            ["RDP 3389 open to Internet on both WANs", "Critical", "Remove public RDP; use WireGuard"],
            ["WAN allowaccess https ssh", "High", "Do not replicate on OPNsense; LAN/MGMT only"],
            ["Akrivia policy src=all despite named object", "High", "Use AKRIVIA_HR / vendor IP alias"],
            ["Guest not isolated from corp by policy", "Medium", "Add deny guest → RFC1918 on OPNsense"],
            ["FortiGuard / cert-inspect not portable", "Info", "Unbound DNSBL + optional Zenarmor"],
        ],
    )

    # 11
    add_heading_styled(doc, "11. OPNsense target architecture", 1)
    doc.add_picture(str(images["opnsense"]), width=Inches(6.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_para(
        doc,
        "Suggested OPNsense roles: wan=Airtel, opt1=Jio (WAN2), LAN parent with VLAN interfaces opt2–opt7, "
        "opt8=WireGuard. Import aliases.csv, apply NAT/firewall from nat-and-firewall.md, edit nics.env and "
        "run build-opnsense-seed.py for peak-seed.xml.",
    )

    # 12
    add_heading_styled(doc, "12. Cutover checklist", 1)
    for step in [
        "Stage OPNsense on spare NIC/VLAN; import aliases; configure WAN_LB and VLANs.",
        "Convert PEAK-CORE-SW to standalone; set trunk to OPNsense; static mgmt on VLAN 100.",
        "Replace or re-home FortiAPs (PETCPL→101, GUEST→102).",
        "Recreate DHCP pools and reservations; verify ACS 10.80.100.10 and APP .103.",
        "Recreate port forwards; lock 1433 to vendor IPs; do not publish 3389/GUI.",
        "Bring up WireGuard; test binny.andrews and admin tunnels.",
        "Confirm biometric punches still land on ACS; confirm Keka/Akrivia sync after VIP move.",
        "Move switch uplink from FortiGate port12 to OPNsense LAN; keep FortiGate powered until verified.",
        "Decommission FortiGate WAN allowaccess and SSL VPN when stable.",
    ]:
        doc.add_paragraph(step, style="List Number")

    # 13
    add_heading_styled(doc, "13. File annex — migration kit", 1)
    add_table(
        doc,
        ["Path", "Purpose"],
        [
            ["opnsense-migration/README.md", "Migration overview"],
            ["opnsense-migration/nics.env", "Fill real NIC names"],
            ["opnsense-migration/build-opnsense-seed.py", "Builds peak-seed.xml"],
            ["opnsense-migration/aliases.csv", "Firewall aliases import"],
            ["opnsense-migration/mac-whitelist.csv", "Captive portal / MAC list"],
            ["opnsense-migration/dhcp-static-maps.csv", "DHCP reservations"],
            ["opnsense-migration/nat-and-firewall.md", "NAT + rule order"],
            ["opnsense-migration/switch-and-wifi.md", "Switch/AP conversion"],
            ["opnsense-migration/wireguard/", "Server keys + client confs"],
            ["opnsense-migration/docs/images/", "Diagram PNGs used in this document"],
        ],
    )

    add_para(
        doc,
        "End of document. Diagrams are also stored as PNG files alongside this Word file for reuse in "
        "presentations.",
        bold=False,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    return OUT


def main():
    IMG.mkdir(parents=True, exist_ok=True)
    images = {
        "landscape": diagram_landscape(),
        "vlans": diagram_vlans(),
        "biometric": diagram_biometric(),
        "services": diagram_services(),
        "opnsense": diagram_opnsense(),
        "inventory": diagram_inventory(),
    }
    print("Diagrams:")
    for k, p in images.items():
        print(f"  {k}: {p}")
    docx_path = build_docx(images)
    print(f"Word document: {docx_path}")


if __name__ == "__main__":
    main()
