#!/usr/bin/env python3
"""Compare previous WL_CORP MAC allowlist vs live laptop/mobile aliases,
classify missing MACs, add them, and print a report.
"""
from __future__ import annotations

import base64
import csv
import json
import re
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
ROOT = Path(__file__).resolve().parent
CRED = ROOT / "OPNSENSE_BACKUP" / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
ALLOW_CSV = ROOT / "wl-corp-mac-allowlist.csv"
LAPTOPS_CSV = ROOT / "wl-corp-leases-laptops.csv"
MOBILES_CSV = ROOT / "wl-corp-leases-mobiles.csv"
XML = ROOT / "OPNSENSE_BACKUP" / "config-PEAK-CORP-FW.CURRENT.xml"
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
SKIP_NOTE_RE = re.compile(r"(tv|printer|camera|ap-|eap|object truenas|opnsense)", re.I)


def load_creds() -> tuple[str, str]:
    key = secret = ""
    for line in CRED.read_text(encoding="utf-8").splitlines():
        if line.startswith("key="):
            key = line[4:]
        elif line.startswith("secret="):
            secret = line[7:]
    return key, secret


def api(method: str, path: str, payload=None):
    key, secret = load_creds()
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def parse_macs(content: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in str(content or "").replace(",", "\n").splitlines():
        mac = line.strip().lower()
        if re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac) and mac not in seen:
            seen.add(mac)
            out.append(mac)
    return out


def is_local_admin(mac: str) -> bool:
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except Exception:
        return False


def classify(user: str, notes: str, hostname: str, mac: str) -> str:
    blob = f"{user} {notes} {hostname}"
    if SKIP_NOTE_RE.search(notes) or SKIP_NOTE_RE.search(hostname):
        return "skip"
    if MOBILE_RE.search(blob) or MOBILE_RE.search(hostname):
        return "mobile"
    if LAPTOP_RE.search(blob) or LAPTOP_RE.search(hostname):
        return "laptop"
    # Test Laptop / known users without phone markers → laptop
    if "laptop" in user.lower() or "test laptop" in user.lower():
        return "laptop"
    # randomized MAC with no laptop signal → mobile-ish
    if is_local_admin(mac) and not LAPTOP_RE.search(blob):
        return "mobile"
    # default previous corp allowlist entries that aren't phones → laptop
    return "laptop"


def mac_alias_payload(name: str, macs: list[str], description: str) -> dict:
    return {
        "enabled": "1",
        "name": name,
        "type": "mac",
        "proto": "",
        "interface": "",
        "counters": "0",
        "updatefreq": "",
        "content": "\n".join(sorted(set(macs))),
        "password": "",
        "username": "",
        "authtype": "",
        "expire": "",
        "categories": "",
        "description": description,
        "path_expression": "",
    }


def set_alias(uuid: str, name: str, macs: list[str], description: str) -> None:
    res = api(
        "POST",
        f"/api/firewall/alias/setItem/{uuid}",
        {"alias": mac_alias_payload(name, macs, description)},
    )
    print(f"alias UPDATE {name} n={len(set(macs))}: {res}")


def append_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    existing = set()
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing.add((row.get("mac") or "").lower())
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if path.stat().st_size == 0:
            w.writeheader()
        for row in rows:
            if row["mac"].lower() in existing:
                continue
            w.writerow(row)
            existing.add(row["mac"].lower())


def main() -> int:
    # previous sources
    prev: dict[str, dict] = {}
    with ALLOW_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mac = row["mac"].strip().lower()
            prev[mac] = {
                "user": row.get("user") or "",
                "notes": row.get("notes") or "",
                "source": "csv",
            }

    xml_text = XML.read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r"<name>WL_CORP_MACS</name>.*?<content>(.*?)</content>",
        xml_text,
        re.S,
    )
    xml_macs = parse_macs(m.group(1) if m else "")
    for mac in xml_macs:
        prev.setdefault(mac, {"user": "", "notes": "from XML backup", "source": "xml"})

    # live leases for hostname hints
    lease_host: dict[str, str] = {}
    try:
        for row in api("GET", "/api/kea/leases4/search").get("rows", []):
            mac = (row.get("hwaddr") or "").lower()
            if mac:
                lease_host[mac] = (row.get("hostname") or "").strip()
    except Exception as e:
        print(f"lease fetch warn: {e}")

    # live aliases
    live: dict[str, dict] = {}
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("WL_CORP_MACS", "WL_CORP_LAPTOPS", "WL_CORP_MOBILES"):
            live[row["name"]] = {
                "uuid": row["uuid"],
                "macs": set(parse_macs(row.get("content"))),
            }

    laptops = set(live["WL_CORP_LAPTOPS"]["macs"])
    mobiles = set(live["WL_CORP_MOBILES"]["macs"])
    covered = laptops | mobiles
    previous = set(prev)
    missing = sorted(previous - covered)

    print(
        f"previous={len(previous)} live_laptops={len(laptops)} "
        f"live_mobiles={len(mobiles)} missing={len(missing)}"
    )
    print()
    print("=== MISSING from laptop/mobile (will classify + add) ===")

    add_laptop: list[dict] = []
    add_mobile: list[dict] = []
    skipped: list[dict] = []

    for mac in missing:
        info = prev[mac]
        host = lease_host.get(mac, "")
        kind = classify(info["user"], info["notes"], host, mac)
        item = {
            "mac": mac,
            "user": info["user"] or "-",
            "notes": info["notes"] or "-",
            "hostname": host or "-",
            "kind": kind,
            "source": info["source"],
        }
        print(
            f"{mac}  {kind:<7}  user={item['user']:<20}  "
            f"host={item['hostname'][:40]}  notes={item['notes'][:40]}"
        )
        if kind == "laptop":
            add_laptop.append(item)
        elif kind == "mobile":
            add_mobile.append(item)
        else:
            skipped.append(item)

    # apply
    new_laptops = sorted(laptops | {i["mac"] for i in add_laptop})
    new_mobiles = sorted(mobiles | {i["mac"] for i in add_mobile})
    new_combined = sorted(set(new_laptops) | set(new_mobiles))

    set_alias(
        live["WL_CORP_LAPTOPS"]["uuid"],
        "WL_CORP_LAPTOPS",
        new_laptops,
        "Corp Wi-Fi laptop MACs (leases + previous allowlist)",
    )
    set_alias(
        live["WL_CORP_MOBILES"]["uuid"],
        "WL_CORP_MOBILES",
        new_mobiles,
        "Corp Wi-Fi mobile MACs (leases + previous allowlist)",
    )
    set_alias(
        live["WL_CORP_MACS"]["uuid"],
        "WL_CORP_MACS",
        new_combined,
        "Corp Wi-Fi MACs (laptops+mobiles union)",
    )
    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))

    # update tracking CSVs
    lap_fields = ["mac", "ip", "hostname", "known_user", "kind", "randomized", "reason"]
    mob_fields = lap_fields
    append_csv(
        LAPTOPS_CSV,
        [
            {
                "mac": i["mac"],
                "ip": "",
                "hostname": i["hostname"],
                "known_user": i["user"],
                "kind": "laptop",
                "randomized": "yes" if is_local_admin(i["mac"]) else "no",
                "reason": "restored-from-previous-allowlist",
            }
            for i in add_laptop
        ],
        lap_fields,
    )
    append_csv(
        MOBILES_CSV,
        [
            {
                "mac": i["mac"],
                "ip": "",
                "hostname": i["hostname"],
                "known_user": i["user"],
                "kind": "mobile",
                "randomized": "yes" if is_local_admin(i["mac"]) else "no",
                "reason": "restored-from-previous-allowlist",
            }
            for i in add_mobile
        ],
        mob_fields,
    )

    print()
    print(f"ADDED to WL_CORP_LAPTOPS ({len(add_laptop)}):")
    for i in add_laptop:
        print(f"  {i['mac']}  {i['user']}")
    print(f"ADDED to WL_CORP_MOBILES ({len(add_mobile)}):")
    for i in add_mobile:
        print(f"  {i['mac']}  {i['user']}")
    if skipped:
        print(f"SKIPPED ({len(skipped)}):")
        for i in skipped:
            print(f"  {i['mac']}  {i['user']}  {i['notes']}")

    print()
    print(
        f"NEW COUNTS: laptops={len(new_laptops)} mobiles={len(new_mobiles)} "
        f"combined={len(new_combined)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
