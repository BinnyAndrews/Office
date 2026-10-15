#!/usr/bin/env python3
"""Rebuild WL_CORP_LAPTOPS from current WL_CORP leases that look like laptops.

Drops the inflated previous-allowlist dump (many MACs per person).
Keeps WL_CORP_MOBILES as-is; refreshes WL_CORP_MACS = laptops + mobiles.
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
OUT_LAPTOPS = ROOT / "wl-corp-leases-laptops.csv"
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


def is_laptop_lease(hostname: str, mac: str) -> bool:
    host = (hostname or "").strip()
    if not host or SKIP_RE.search(host) or MOBILE_RE.search(host):
        return False
    if LAPTOP_RE.search(host):
        return True
    # Universal MAC + PC-like hostname (Windows name) on WL_CORP
    if PC_HOST_RE.match(host.rstrip(".")) and not is_local_admin(mac):
        return True
    return False


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


def main() -> int:
    allow: dict[str, str] = {}
    if ALLOW_CSV.exists():
        with ALLOW_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                allow[(row.get("mac") or "").lower()] = row.get("user") or ""

    rows = api("GET", "/api/kea/leases4/search").get("rows", [])
    wl = [
        r
        for r in rows
        if r.get("if_descr") == "WL_CORP"
        or str(r.get("address", "")).startswith("10.80.101.")
    ]

    laptops: list[dict] = []
    seen: set[str] = set()
    for r in wl:
        mac = (r.get("hwaddr") or "").lower()
        host = (r.get("hostname") or "").strip()
        if not mac or mac in seen:
            continue
        if not is_laptop_lease(host, mac):
            continue
        seen.add(mac)
        laptops.append(
            {
                "mac": mac,
                "ip": r.get("address") or "",
                "hostname": host or "-",
                "known_user": allow.get(mac, "-") or "-",
                "kind": "laptop",
                "randomized": "yes" if is_local_admin(mac) else "no",
                "reason": "live-lease-laptop",
            }
        )

    live: dict[str, dict] = {}
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("WL_CORP_MACS", "WL_CORP_LAPTOPS", "WL_CORP_MOBILES"):
            live[row["name"]] = {
                "uuid": row["uuid"],
                "macs": parse_macs(row.get("content")),
            }

    old_n = len(live["WL_CORP_LAPTOPS"]["macs"])
    macs = [x["mac"] for x in laptops]
    mobiles = live["WL_CORP_MOBILES"]["macs"]
    combined = sorted(set(macs) | set(mobiles))

    print(f"WL_CORP leases={len(wl)}")
    print(f"LAPTOPS old={old_n} new={len(macs)} (lease-confirmed only)")
    print()
    for x in sorted(laptops, key=lambda i: i["hostname"]):
        print(
            f"{x['mac']}  {x['ip']:<15}  {x['hostname'][:40]:<40}  {x['known_user']}"
        )

    api(
        "POST",
        f"/api/firewall/alias/setItem/{live['WL_CORP_LAPTOPS']['uuid']}",
        {
            "alias": mac_alias_payload(
                "WL_CORP_LAPTOPS",
                macs,
                "Corp Wi-Fi laptop MACs from current leases only",
            )
        },
    )
    api(
        "POST",
        f"/api/firewall/alias/setItem/{live['WL_CORP_MACS']['uuid']}",
        {
            "alias": mac_alias_payload(
                "WL_CORP_MACS",
                combined,
                "Corp Wi-Fi MACs (laptops+mobiles union)",
            )
        },
    )
    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))

    fields = ["mac", "ip", "hostname", "known_user", "kind", "randomized", "reason"]
    with OUT_LAPTOPS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for x in sorted(laptops, key=lambda i: i["hostname"]):
            w.writerow(x)

    print()
    print(
        f"UPDATED: WL_CORP_LAPTOPS={len(macs)} WL_CORP_MOBILES={len(mobiles)} "
        f"WL_CORP_MACS={len(combined)}"
    )
    print(f"Wrote {OUT_LAPTOPS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
