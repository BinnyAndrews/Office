#!/usr/bin/env python3
"""Generate Peak Energy network architecture PDF + Word documents."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path(__file__).resolve().parent
DIAGRAM_PNG = OUT / "Peak-Energy-Network-Architecture.png"
PDF_PATH = OUT / "Peak-Energy-Network-Architecture.pdf"
DOCX_PATH = OUT / "Peak-Energy-Network-Architecture.docx"

TODAY = date.today().isoformat()

VLANS = [
    ["VLAN / Role", "Subnet", "Gateway (FW)", "DHCP pool", "Interface"],
    ["MGMT (admin gear)", "10.80.99.0/24", "10.80.99.1", "10.80.99.101–200", "lan / re0"],
    ["WIRED_CORP", "10.80.100.0/24", "10.80.100.1", "10.80.100.101–200", "opt2 / VLAN 100"],
    ["WL_CORP (PETCPL)", "10.80.101.0/24", "10.80.101.1", "10.80.101.101–200", "opt3 / VLAN 101"],
    ["WL_GUEST", "10.80.102.0/24", "10.80.102.1", "10.80.102.101–200", "opt4 / VLAN 102"],
    ["WireGuard VPN", "10.80.200.0/28", "10.80.200.1", "static peers", "opt6 / wg0"],
]

WAN = [
    ["WAN", "Public IP", "Gateway name", "Notes"],
    ["Airtel Fiber", "125.19.224.18/30", "WAN_AIRTEL", "Primary; WG endpoint default"],
    ["Jio RF", "47.247.169.94/30", "WAN_JIO", "Failover / alternate WG endpoint"],
    ["WAN_LB", "—", "WAN_LB", "Dual-WAN load balance + failover"],
]

MGMT_HOSTS = [
    ["IP", "Hostname", "Role"],
    ["10.80.99.1", "PEAK-CORP-FW / OpnSense", "Firewall GUI :4444, SSH, Unbound DNS"],
    ["10.80.99.2", "sg2428p", "Omada switch SG2428P"],
    ["10.80.99.3", "oc200", "Omada OC200 controller https://10.80.99.3/"],
    ["10.80.99.21", "eap670-1", "Wi-Fi AP EAP670"],
    ["10.80.99.22", "eap670-2", "Wi-Fi AP EAP670"],
    ["10.80.99.23", "eap670-3", "Wi-Fi AP EAP670"],
    ["10.80.99.24", "eap225-3", "Wi-Fi AP EAP225"],
]

WIRED_HOSTS = [
    ["IP", "Hostname", "Role"],
    ["10.80.100.1", "—", "WIRED_CORP SVI / DNS"],
    ["10.80.100.10", "biometric-server", "ACS / Attendance SQL"],
    ["10.80.100.11", "biometric-entry", "Biometric entry terminal"],
    ["10.80.100.12", "biometric-exit", "Biometric exit terminal"],
    ["10.80.100.20", "biometric-server-new", "ACS new (reservation)"],
    ["10.80.100.21", "laser-printer", "HP LaserJet (Ethernet)"],
    ["10.80.100.51", "peak-ws-1", "Workstation 1"],
    ["10.80.100.52", "peak-ws-2", "Workstation 2"],
    ["10.80.100.53", "peak-ws-3", "Workstation 3"],
    ["10.80.100.54", "dev-ws-1", "PeakPulse / peakpulse-dev.peakenergy.asia"],
    ["10.80.100.55", "peak801-in-conf", "Conference room PC"],
]

WIFI_HOSTS = [
    ["IP", "Hostname", "Role"],
    ["10.80.101.1", "—", "WL_CORP SVI / DNS"],
    ["10.80.101.21", "laser-printer", "HP LaserJet (Wi-Fi)"],
    ["10.80.101.22", "printer-md", "MD HP Smart Tank Wi-Fi"],
    ["10.80.101.30", "tv-conferance", "TV Conference Room"],
    ["10.80.101.31", "tv-kalaam", "TV Abdul Kalaam"],
    ["10.80.101.32", "tv-ratan", "TV Ratan Tata"],
    ["10.80.101.33", "tv-onm", "TV Operations & Mgmt"],
    ["10.80.101.34", "tv-md", "TV MD"],
]

WG_PEERS = [
    ["Peer", "Tunnel IP", "Access"],
    ["PEAK-WG server", "10.80.200.1/28", "OPNsense wg0 listen UDP 51820"],
    ["binny.andrews", "10.80.200.2/32", "Admin: FW GUI/SSH + MGMT + CORP"],
    ["admin", "10.80.200.3/32", "Admin: FW GUI/SSH + MGMT + CORP"],
    ["jagadeshwar", "10.80.200.4/32", "AMC: CORP only (.100/.101)"],
    ["venu.gopal.reddy", "10.80.200.5/32", "AMC: CORP only"],
    ["poovarasu", "10.80.200.6/32", "AMC: CORP only"],
    ["sanoj.james", "10.80.200.7/32", "AMC: CORP only"],
]

POLICY = [
    ["Topic", "Current policy"],
    ["PeakPulse public WAN", "DISABLED — no public HTTP/HTTPS port-forward"],
    ["PeakPulse access", "WireGuard or on-site LAN only → 10.80.100.54"],
    ["WG DNS", "Client DNS 10.80.100.1 (Unbound); also listens on WG"],
    ["WG AllowedIPs", "10.80.0.0/16 split tunnel"],
    ["WG endpoints", "125.19.224.18:51820 (Airtel) or 47.247.169.94:51820 (Jio)"],
    ["MGMT via VPN", "Only WG_FW_ADMINS (binny + admin)"],
    ["FW GUI via VPN", "Only WG_FW_ADMINS → (self) :4444 / SSH"],
    ["AMC peers via VPN", "CORP .100 + .101 only (PeakPulse etc.)"],
    ["ACS SQL from Internet", "KEKA_HR only → 10.80.100.10:1433"],
    ["Guest Wi-Fi", "VLAN 102 + captive portal; scheduled internet Mon–Fri 07:00–19:00"],
    ["On-site + WG tip", "On PETCPL turn VPN OFF (Peak Energy VPN.exe); remote turn ON"],
]


def draw_diagram(path: Path) -> None:
    """Draw architecture PNG with Pillow."""
    from PIL import Image as PILImage, ImageDraw, ImageFont

    W, H = 1600, 1100
    img = PILImage.new("RGB", (W, H), "#F7F8FA")
    d = ImageDraw.Draw(img)

    def font(size: int):
        for name in (
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
        ):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    f_title = font(28)
    f_h = font(16)
    f_b = font(13)
    f_s = font(11)

    def box(xy, fill, outline, title, lines, title_fill="#111"):
        x1, y1, x2, y2 = xy
        d.rounded_rectangle(xy, radius=12, fill=fill, outline=outline, width=2)
        d.text((x1 + 14, y1 + 10), title, fill=title_fill, font=f_h)
        yy = y1 + 36
        for line in lines:
            d.text((x1 + 14, yy), line, fill="#222", font=f_s)
            yy += 18

    def arrow(a, b, color="#555"):
        d.line([a, b], fill=color, width=3)

    d.text((40, 24), "Peak Energy — Corporate Network Architecture", fill="#0B3D5C", font=f_title)
    d.text((40, 60), f"PEAK-CORP-FW (OPNsense)  ·  Document date {TODAY}", fill="#555", font=f_b)

    # Internet
    box((60, 100, 280, 200), "#E8F1FF", "#2F6FED", "Internet / ISP", [
        "Clients / Keka cloud",
        "Remote VPN users",
    ])

    # WANs
    box((360, 90, 620, 170), "#FFF4E5", "#D97706", "WAN_AIRTEL", [
        "125.19.224.18/30",
        "WG :51820 (primary)",
    ])
    box((360, 190, 620, 270), "#FFF4E5", "#D97706", "WAN_JIO", [
        "47.247.169.94/30",
        "WG :51820 (alternate)",
    ])

    arrow((280, 150), (360, 130))
    arrow((280, 160), (360, 230))

    # Firewall
    box((680, 100, 1040, 280), "#E8F8EF", "#059669", "PEAK-CORP-FW (OPNsense)", [
        "GUI https://10.80.99.1:4444",
        "Unbound DNS · Kea DHCP",
        "WAN_LB dual-WAN",
        "WireGuard PEAK-WG 10.80.200.1/28",
        "Public PeakPulse NAT: DISABLED",
    ])
    arrow((620, 150), (680, 170))
    arrow((620, 230), (680, 200))

    # Switch
    box((1100, 120, 1480, 260), "#F3E8FF", "#7C3AED", "Omada SG2428P  10.80.99.2", [
        "L2 switch · VLANs 99/100/101/102",
        "Trunk to FW + APs",
        "OC200 controller 10.80.99.3",
    ])
    arrow((1040, 190), (1100, 190))

    # MGMT
    box((60, 320, 400, 520), "#FEE2E2", "#DC2626", "MGMT  10.80.99.0/24", [
        ".1  Firewall",
        ".2  Switch SG2428P",
        ".3  OC200",
        ".21–.23  EAP670 APs",
        ".24  EAP225",
        "Admin gear only",
        "WG: binny/admin only",
    ])

    # WIRED
    box((430, 320, 800, 560), "#DBEAFE", "#2563EB", "WIRED_CORP  10.80.100.0/24", [
        ".1  SVI / DNS",
        ".10  ACS biometric-server",
        ".11/.12  Entry/Exit terminals",
        ".21  Laser printer",
        ".51–.53  Workstations",
        ".54  PeakPulse (dev-ws-1)",
        ".55  Conference PC",
        "DHCP .101–.200",
    ])

    # WL CORP
    box((830, 320, 1180, 540), "#D1FAE5", "#059669", "WL_CORP (PETCPL)  10.80.101.0/24", [
        ".1  SVI / DNS",
        "Corp Wi-Fi SSID",
        "TVs .30–.34",
        "Printers .21/.22",
        "DHCP .101–.200",
        "MAC allowlist (optional)",
    ])

    # GUEST
    box((1210, 320, 1540, 500), "#FEF3C7", "#D97706", "WL_GUEST  10.80.102.0/24", [
        "Captive portal",
        "Internet scheduled",
        "No internal access",
        "DHCP .101–.200",
    ])

    # APs
    box((1100, 560, 1480, 680), "#FCE7F3", "#DB2777", "Access Points (MGMT IPs)", [
        "EAP670-1/2/3 · EAP225-3",
        "SSIDs → VLAN 101 / 102",
        "Managed by OC200",
    ])
    arrow((1290, 260), (1290, 320))
    arrow((1290, 500), (1290, 560))

    # VPN
    box((60, 560, 800, 760), "#E0E7FF", "#4F46E5", "Peak Energy VPN (WireGuard PEAK-WG)", [
        "UDP 51820 on both WANs · Tunnel 10.80.200.0/28",
        "Split tunnel AllowedIPs = 10.80.0.0/16",
        "Admins (.2/.3): FW + MGMT + CORP",
        "AMC peers (.4–.7): CORP .100/.101 only (PeakPulse)",
        "Client tool: Peak Energy VPN.exe  ·  On-site: VPN OFF",
    ])
    arrow((860, 280), (430, 560), "#4F46E5")

    # External services
    box((830, 700, 1480, 820), "#F1F5F9", "#64748B", "External / App notes", [
        "peakpulse-dev.peakenergy.asia → 10.80.100.54 (internal DNS; not public)",
        "ACS SQL 1433 from Internet: KEKA_HR only → 10.80.100.10",
        "Domain: peakenergy.asia",
    ])

    d.text((40, 1040), "Source: OPNsense PEAK-CORP-FW config + WireGuard peer pack · Peak Energy IT", fill="#888", font=f_s)
    img.save(path, "PNG", optimize=True)


def style_table(t: Table, header=True):
    style = TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#94A3B8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D5C")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
        ]
    )
    t.setStyle(style)


def build_pdf(diagram: Path, path: Path) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Peak Energy Network Architecture",
        author="Peak Energy IT",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#0B3D5C"), spaceAfter=8)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#0B3D5C"), spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=12)
    story = []

    story.append(Paragraph("Peak Energy — Corporate Network Architecture", h1))
    story.append(Paragraph(f"Firewall: <b>PEAK-CORP-FW</b> (OPNsense) · Generated {TODAY}", body))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This document describes VLANs, WAN links, Omada switching/Wi‑Fi, DHCP reservations, "
        "WireGuard (Peak Energy VPN), and access policy for PeakPulse / ACS.",
        body,
    ))
    story.append(Spacer(1, 8))

    # Landscape-ish diagram scaled to page width
    iw, ih = 170 * mm, 117 * mm
    story.append(Image(str(diagram), width=iw, height=ih))
    story.append(PageBreak())

    story.append(Paragraph("1. WAN links", h2))
    t = Table(WAN, colWidths=[100, 120, 100, 180])
    style_table(t)
    story.append(t)

    story.append(Paragraph("2. VLANs / subnets", h2))
    t = Table(VLANS, colWidths=[110, 90, 80, 100, 110])
    style_table(t)
    story.append(t)

    story.append(Paragraph("3. MGMT hosts (10.80.99.0/24)", h2))
    t = Table(MGMT_HOSTS, colWidths=[90, 140, 270])
    style_table(t)
    story.append(t)

    story.append(Paragraph("4. WIRED_CORP hosts (10.80.100.0/24)", h2))
    t = Table(WIRED_HOSTS, colWidths=[90, 140, 270])
    style_table(t)
    story.append(t)

    story.append(Paragraph("5. WL_CORP hosts (10.80.101.0/24)", h2))
    t = Table(WIFI_HOSTS, colWidths=[90, 140, 270])
    style_table(t)
    story.append(t)

    story.append(PageBreak())
    story.append(Paragraph("6. WireGuard / Peak Energy VPN", h2))
    t = Table(WG_PEERS, colWidths=[120, 100, 280])
    style_table(t)
    story.append(t)

    story.append(Paragraph("7. Security & access policy", h2))
    t = Table(POLICY, colWidths=[140, 360])
    style_table(t)
    story.append(t)

    story.append(Paragraph("8. Logical traffic paths", h2))
    story.append(Paragraph(
        "<b>On-site (PETCPL / wired):</b> Clients use VLAN gateway directly. "
        "Peak Energy VPN should be <b>OFF</b> so 10.80.x is not forced into the tunnel.<br/>"
        "<b>Remote:</b> Peak Energy VPN <b>ON</b> → UDP 51820 → PEAK-WG → CORP (.100/.101). "
        "Admins also reach MGMT (.99) and firewall GUI.<br/>"
        "<b>Guest:</b> VLAN 102 captive portal; blocked from MGMT/CORP; internet by schedule.",
        body,
    ))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<i>Confidential — Peak Energy IT. Derived from OPNsense config-PEAK-CORP-FW and WireGuard peer pack.</i>",
        body,
    ))
    doc.build(story)


def set_cell_shading(cell, hex_color: str):
    from docx.oxml import OxmlElement

    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tcPr.append(shd)
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")


def add_docx_table(doc: Document, rows: list[list[str]]):
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = table.rows[i].cells[j]
            cell.text = str(val)
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)
                    if i == 0:
                        r.font.bold = True
                        r.font.color.rgb = RGBColor(255, 255, 255)
            if i == 0:
                set_cell_shading(cell, "0B3D5C")
    doc.add_paragraph()


def build_docx(diagram: Path, path: Path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)

    title = doc.add_heading("Peak Energy — Corporate Network Architecture", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p = doc.add_paragraph()
    run = p.add_run(f"Firewall: PEAK-CORP-FW (OPNsense)  ·  Generated {TODAY}")
    run.font.size = Pt(11)

    doc.add_paragraph(
        "This document describes VLANs, WAN links, Omada switching/Wi‑Fi, DHCP reservations, "
        "WireGuard (Peak Energy VPN), and access policy for PeakPulse / ACS."
    )

    doc.add_heading("Architecture diagram", level=1)
    doc.add_picture(str(diagram), width=Inches(7.0))

    doc.add_heading("1. WAN links", level=1)
    add_docx_table(doc, WAN)

    doc.add_heading("2. VLANs / subnets", level=1)
    add_docx_table(doc, VLANS)

    doc.add_heading("3. MGMT hosts (10.80.99.0/24)", level=1)
    add_docx_table(doc, MGMT_HOSTS)

    doc.add_heading("4. WIRED_CORP hosts (10.80.100.0/24)", level=1)
    add_docx_table(doc, WIRED_HOSTS)

    doc.add_heading("5. WL_CORP hosts (10.80.101.0/24)", level=1)
    add_docx_table(doc, WIFI_HOSTS)

    doc.add_heading("6. WireGuard / Peak Energy VPN", level=1)
    add_docx_table(doc, WG_PEERS)

    doc.add_heading("7. Security & access policy", level=1)
    add_docx_table(doc, POLICY)

    doc.add_heading("8. Logical traffic paths", level=1)
    doc.add_paragraph(
        "On-site (PETCPL / wired): Clients use the VLAN gateway directly. "
        "Peak Energy VPN should be OFF so 10.80.x is not forced into the tunnel."
    )
    doc.add_paragraph(
        "Remote: Peak Energy VPN ON → UDP 51820 → PEAK-WG → CORP (.100/.101). "
        "Admins also reach MGMT (.99) and the firewall GUI."
    )
    doc.add_paragraph(
        "Guest: VLAN 102 captive portal; blocked from MGMT/CORP; internet by weekday schedule."
    )

    doc.add_paragraph()
    note = doc.add_paragraph()
    r = note.add_run(
        "Confidential — Peak Energy IT. Derived from OPNsense config-PEAK-CORP-FW and WireGuard peer pack."
    )
    r.italic = True
    r.font.size = Pt(9)

    doc.save(str(path))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("Drawing diagram…")
    draw_diagram(DIAGRAM_PNG)
    print("Writing PDF…")
    build_pdf(DIAGRAM_PNG, PDF_PATH)
    print("Writing Word…")
    build_docx(DIAGRAM_PNG, DOCX_PATH)
    print(f"PNG:  {DIAGRAM_PNG}")
    print(f"PDF:  {PDF_PATH}")
    print(f"DOCX: {DOCX_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
