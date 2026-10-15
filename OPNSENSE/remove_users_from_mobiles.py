#!/usr/bin/env python3
"""Remove selected users' MACs from WL_CORP_MOBILES (and refresh WL_CORP_MACS)."""
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
MOBILES_CSV = ROOT / "wl-corp-leases-mobiles.csv"
CTX = ssl._create_unverified_context()

REMOVE_USERS = {"saurav", "thomas", "mezhil", "harsha"}


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


def user_macs() -> dict[str, str]:
    """mac -> user name from allowlist + mobiles csv."""
    out: dict[str, str] = {}
    if ALLOW_CSV.exists():
        with ALLOW_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                mac = (row.get("mac") or "").strip().lower()
                if mac:
                    out[mac] = (row.get("user") or "").strip()
    if MOBILES_CSV.exists():
        with MOBILES_CSV.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                mac = (row.get("mac") or "").strip().lower()
                user = (row.get("known_user") or "").strip()
                if mac and user and user != "-":
                    out.setdefault(mac, user)
    return out


def main() -> int:
    mac_user = user_macs()
    live: dict[str, dict] = {}
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("WL_CORP_MACS", "WL_CORP_LAPTOPS", "WL_CORP_MOBILES"):
            live[row["name"]] = {
                "uuid": row["uuid"],
                "macs": parse_macs(row.get("content")),
            }

    mobiles = live["WL_CORP_MOBILES"]["macs"]
    laptops = live["WL_CORP_LAPTOPS"]["macs"]

    remove: list[tuple[str, str]] = []
    keep: list[str] = []
    for mac in mobiles:
        user = mac_user.get(mac, "")
        if user.lower() in REMOVE_USERS:
            remove.append((mac, user))
        else:
            keep.append(mac)

    print(f"WL_CORP_MOBILES before={len(mobiles)} remove={len(remove)} after={len(keep)}")
    print("REMOVED:")
    for mac, user in sorted(remove, key=lambda x: (x[1].lower(), x[0])):
        print(f"  {mac}  {user}")

    api(
        "POST",
        f"/api/firewall/alias/setItem/{live['WL_CORP_MOBILES']['uuid']}",
        {
            "alias": mac_alias_payload(
                "WL_CORP_MOBILES",
                keep,
                "Corp Wi-Fi mobile MACs (leases + previous allowlist)",
            )
        },
    )
    combined = sorted(set(laptops) | set(keep))
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

    # rewrite mobiles CSV without removed users
    if MOBILES_CSV.exists():
        rows = []
        with MOBILES_CSV.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            for row in reader:
                mac = (row.get("mac") or "").lower()
                known = (row.get("known_user") or "").strip()
                if known.lower() in REMOVE_USERS:
                    continue
                if mac in {m for m, _ in remove}:
                    continue
                rows.append(row)
        with MOBILES_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"updated {MOBILES_CSV} rows={len(rows)}")

    # verify
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("WL_CORP_MOBILES", "WL_CORP_MACS", "WL_CORP_LAPTOPS"):
            n = len(parse_macs(row.get("content")))
            print(f"VERIFY {row['name']} n={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
