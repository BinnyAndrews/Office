#!/usr/bin/env python3
"""Pull WL_CORP DHCP leases and list likely laptop / mobile MACs."""
from __future__ import annotations

import base64
import csv
import json
import re
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(__file__).resolve().parent / "OPNSENSE_BACKUP" / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
ALLOW = Path(__file__).resolve().parent / "wl-corp-mac-allowlist.csv"
OUT_LAPTOPS = Path(__file__).resolve().parent / "wl-corp-leases-laptops.csv"
OUT_MOBILES = Path(__file__).resolve().parent / "wl-corp-leases-mobiles.csv"
CTX = ssl._create_unverified_context()

MOBILE_RE = re.compile(
    r"(iphone|ipad|android|galaxy|pixel|oneplus|redmi|xiaomi|vivo|oppo|"
    r"realme|samsung|mobile|phone|huawei|honor|motorola|nord|"
    r"\bs[2-9]\d\b|\bm\d{2}\b|edge[-_]|watch)",
    re.I,
)
LAPTOP_RE = re.compile(
    r"(laptop|desktop|notebook|pc-|win-|windows|macbook|thinkpad|latitude|"
    r"inspiron|elitebook|probook|surface|DESKTOP-|LAPTOP-|peak801-lp|lp\d{3})",
    re.I,
)
# devices that are neither laptop nor phone allowlist targets
SKIP_RE = re.compile(r"(^tv-|\btv\b|printer|camera|ap-|eap)", re.I)
PC_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,}$")


def load_creds() -> tuple[str, str]:
    key = secret = ""
    for line in CRED.read_text(encoding="utf-8").splitlines():
        if line.startswith("key="):
            key = line[4:]
        elif line.startswith("secret="):
            secret = line[7:]
    return key, secret


def api_get(path: str):
    key, secret = load_creds()
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    req = urllib.request.Request(BASE + path, method="GET")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        return json.loads(r.read().decode())


def is_local_admin(mac: str) -> bool:
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except Exception:
        return False


def classify(hostname: str, mac: str) -> tuple[str, str]:
    host = (hostname or "").strip()
    local = is_local_admin(mac)
    if SKIP_RE.search(host):
        return "skip", "non-endpoint"
    if MOBILE_RE.search(host):
        return "mobile", "hostname"
    if LAPTOP_RE.search(host):
        return "laptop", "hostname"
    if host and PC_HOST_RE.match(host):
        if local:
            # randomized + generic host → usually phone/private-MAC; keep reviewable
            return "likely-mobile", "pc-hostname+randomized-mac"
        return "laptop", "pc-hostname+universal-mac"
    if not host:
        if local:
            return "likely-mobile", "no-hostname+randomized-mac"
        return "unknown", "no-hostname"
    return "unknown", "hostname-unclassified"


def main() -> None:
    allow: dict[str, str] = {}
    if ALLOW.exists():
        with ALLOW.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                allow[row["mac"].lower()] = row["user"]

    rows = api_get("/api/kea/leases4/search")["rows"]
    wl = [
        r
        for r in rows
        if r.get("if_descr") == "WL_CORP"
        or str(r.get("address", "")).startswith("10.80.101.")
    ]

    classified = []
    for r in wl:
        mac = (r.get("hwaddr") or "").lower()
        host = (r.get("hostname") or "").strip()
        kind, reason = classify(host, mac)
        classified.append(
            {
                "kind": kind,
                "ip": r.get("address"),
                "mac": mac,
                "hostname": host or "-",
                "known_user": allow.get(mac, "-"),
                "randomized": "yes" if is_local_admin(mac) else "no",
                "reason": reason,
            }
        )

    print(f"Total leases: {len(rows)} | WL_CORP leases: {len(wl)}")
    print()
    print("=== ALL WL_CORP (VLAN 101) leases ===")
    hdr = f"{'kind':<16} {'ip':<16} {'mac':<20} {'hostname':<28} {'known_user':<18} rand"
    print(hdr)
    for c in sorted(classified, key=lambda x: (x["kind"], x["hostname"])):
        print(
            f"{c['kind']:<16} {c['ip']:<16} {c['mac']:<20} "
            f"{c['hostname'][:27]:<28} {c['known_user'][:17]:<18} {c['randomized']}"
        )

    fields = [
        "mac",
        "ip",
        "hostname",
        "known_user",
        "kind",
        "randomized",
        "reason",
    ]

    def write_csv(path: Path, rows: list[dict]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for c in sorted(rows, key=lambda x: x["hostname"]):
                w.writerow({k: c[k] for k in fields})

    def print_group(title: str, alias: str, rows: list[dict]) -> None:
        print()
        print(f"=== {title}: {len(rows)} ===")
        for c in sorted(rows, key=lambda x: x["hostname"]):
            print(
                f"{c['mac']}  {c['ip']:<15}  {c['hostname']:<28}  {c['known_user']}"
            )
        print()
        print(f"=== Paste into {alias} alias ===")
        for c in sorted(rows, key=lambda x: x["mac"]):
            print(c["mac"])

    laptops = [c for c in classified if c["kind"] in ("laptop", "likely-laptop")]
    mobiles = [c for c in classified if c["kind"] in ("mobile", "likely-mobile")]
    unknown = [c for c in classified if c["kind"] in ("unknown", "skip")]

    print_group("LAPTOP candidates", "WL_CORP_LAPTOPS", laptops)
    print_group("MOBILE candidates", "WL_CORP_MOBILES", mobiles)

    if unknown:
        print()
        print(f"=== UNKNOWN (review manually): {len(unknown)} ===")
        for c in sorted(unknown, key=lambda x: x["hostname"]):
            print(
                f"{c['mac']}  {c['ip']:<15}  {c['hostname']:<28}  {c['known_user']}"
            )

    write_csv(OUT_LAPTOPS, laptops)
    write_csv(OUT_MOBILES, mobiles)
    print()
    print(f"Wrote {OUT_LAPTOPS}")
    print(f"Wrote {OUT_MOBILES}")


if __name__ == "__main__":
    main()
