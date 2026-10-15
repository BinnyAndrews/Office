#!/usr/bin/env python3
"""Add named users' laptop + mobile MACs from allowlist into live aliases."""
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
CTX = ssl._create_unverified_context()

USERS = ("sanoj", "sampada", "santhosh")


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


def append_csv(path: Path, rows: list[dict]) -> None:
    fields = ["mac", "ip", "hostname", "known_user", "kind", "randomized", "reason"]
    existing: set[str] = set()
    old: list[dict] = []
    if path.exists() and path.stat().st_size:
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                old.append(row)
                existing.add((row.get("mac") or "").lower())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in old:
            w.writerow({k: row.get(k, "") for k in fields})
        for row in rows:
            if row["mac"].lower() in existing:
                continue
            w.writerow(row)
            existing.add(row["mac"].lower())


def main() -> int:
    entries: list[tuple[str, str]] = []
    with ALLOW_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            user = (row.get("user") or "").strip()
            mac = (row.get("mac") or "").strip().lower()
            if not mac:
                continue
            if any(u in user.lower() for u in USERS):
                entries.append((mac, user))

    add_laptops: list[tuple[str, str]] = []
    add_mobiles: list[tuple[str, str]] = []
    for mac, user in entries:
        if is_local_admin(mac):
            add_mobiles.append((mac, user))
        else:
            add_laptops.append((mac, user))

    live: dict[str, dict] = {}
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("WL_CORP_MACS", "WL_CORP_LAPTOPS", "WL_CORP_MOBILES"):
            live[row["name"]] = {
                "uuid": row["uuid"],
                "macs": parse_macs(row.get("content")),
            }

    new_laptops = sorted(set(live["WL_CORP_LAPTOPS"]["macs"]) | {m for m, _ in add_laptops})
    new_mobiles = sorted(set(live["WL_CORP_MOBILES"]["macs"]) | {m for m, _ in add_mobiles})
    combined = sorted(set(new_laptops) | set(new_mobiles))

    print("TO ADD — laptops:")
    for mac, user in sorted(add_laptops, key=lambda x: (x[1], x[0])):
        already = mac in live["WL_CORP_LAPTOPS"]["macs"]
        print(f"  {mac}  {user}  {'(already)' if already else 'NEW'}")
    print("TO ADD — mobiles:")
    for mac, user in sorted(add_mobiles, key=lambda x: (x[1], x[0])):
        already = mac in live["WL_CORP_MOBILES"]["macs"]
        print(f"  {mac}  {user}  {'(already)' if already else 'NEW'}")

    api(
        "POST",
        f"/api/firewall/alias/setItem/{live['WL_CORP_LAPTOPS']['uuid']}",
        {
            "alias": mac_alias_payload(
                "WL_CORP_LAPTOPS",
                new_laptops,
                "Corp Wi-Fi laptop MACs (leases + named users)",
            )
        },
    )
    api(
        "POST",
        f"/api/firewall/alias/setItem/{live['WL_CORP_MOBILES']['uuid']}",
        {
            "alias": mac_alias_payload(
                "WL_CORP_MOBILES",
                new_mobiles,
                "Corp Wi-Fi mobile MACs (leases + named users)",
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

    append_csv(
        LAPTOPS_CSV,
        [
            {
                "mac": mac,
                "ip": "",
                "hostname": "-",
                "known_user": user,
                "kind": "laptop",
                "randomized": "no",
                "reason": "added-named-user-allowlist",
            }
            for mac, user in add_laptops
            if mac not in live["WL_CORP_LAPTOPS"]["macs"]
        ],
    )
    append_csv(
        MOBILES_CSV,
        [
            {
                "mac": mac,
                "ip": "",
                "hostname": "-",
                "known_user": user,
                "kind": "mobile",
                "randomized": "yes",
                "reason": "added-named-user-allowlist",
            }
            for mac, user in add_mobiles
            if mac not in live["WL_CORP_MOBILES"]["macs"]
        ],
    )

    print()
    print(
        f"COUNTS: laptops={len(new_laptops)} mobiles={len(new_mobiles)} "
        f"combined={len(combined)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
