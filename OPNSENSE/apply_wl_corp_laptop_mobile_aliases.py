#!/usr/bin/env python3
"""Create WL_CORP_LAPTOPS / WL_CORP_MOBILES aliases, refresh WL_CORP_MACS,
and add DISABLED Pass rules for each device class on opt3.
"""
from __future__ import annotations

import base64
import csv
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
ROOT = Path(__file__).resolve().parent
CRED = ROOT / "OPNSENSE_BACKUP" / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
LAPTOPS_CSV = ROOT / "wl-corp-leases-laptops.csv"
MOBILES_CSV = ROOT / "wl-corp-leases-mobiles.csv"
CTX = ssl._create_unverified_context()

# Existing MAC internet rule used as addRule template
TEMPLATE_UUID = "ec42364f-09b4-4133-bdd7-eb03dfd3a2f2"

RULE_SPECS = [
    # laptops
    {
        "source_net": "WL_CORP_LAPTOPS",
        "destination_net": "LAN_RFC1918",
        "destination_not": "1",
        "gateway": "WAN_LB",
        "description": "Allow WL_CORP_LAPTOPS to Internet via WAN_LB (DISABLED)",
    },
    {
        "source_net": "WL_CORP_LAPTOPS",
        "destination_net": "WIRED_CORP",
        "destination_not": "0",
        "gateway": "",
        "description": "Allow WL_CORP_LAPTOPS to WIRED_CORP (DISABLED)",
    },
    {
        "source_net": "WL_CORP_LAPTOPS",
        "destination_net": "MGMT",
        "destination_not": "0",
        "gateway": "",
        "description": "Allow WL_CORP_LAPTOPS to MGMT (DISABLED)",
    },
    # mobiles
    {
        "source_net": "WL_CORP_MOBILES",
        "destination_net": "LAN_RFC1918",
        "destination_not": "1",
        "gateway": "WAN_LB",
        "description": "Allow WL_CORP_MOBILES to Internet via WAN_LB (DISABLED)",
    },
    {
        "source_net": "WL_CORP_MOBILES",
        "destination_net": "WIRED_CORP",
        "destination_not": "0",
        "gateway": "",
        "description": "Allow WL_CORP_MOBILES to WIRED_CORP (DISABLED)",
    },
    {
        "source_net": "WL_CORP_MOBILES",
        "destination_net": "MGMT",
        "destination_not": "0",
        "gateway": "",
        "description": "Allow WL_CORP_MOBILES to MGMT (DISABLED)",
    },
]


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


def selected_keys(node: dict) -> list[str]:
    out = []
    for k, v in node.items():
        if isinstance(v, dict) and v.get("selected") in (1, "1", True):
            out.append(k)
    return out


def flatten(node):
    if not isinstance(node, dict):
        return node
    if node and all(isinstance(v, dict) and "selected" in v for v in node.values()):
        sel = selected_keys(node)
        if not sel:
            return ""
        return sel[0] if len(sel) == 1 else ",".join(sel)
    out = {}
    for k, v in node.items():
        if isinstance(v, dict):
            out[k] = flatten(v)
        elif isinstance(v, list):
            out[k] = [flatten(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


def read_macs(path: Path) -> list[str]:
    macs = []
    seen = set()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mac = (row.get("mac") or "").strip().lower()
            if mac and mac not in seen:
                seen.add(mac)
                macs.append(mac)
    return sorted(macs)


def clean_alias_form(form: dict) -> dict:
    for k in list(form.keys()):
        if k.startswith("in_") or k.startswith("out_") or k in (
            "current_items",
            "last_updated",
            "eval_nomatch",
            "eval_match",
        ):
            form.pop(k, None)
    return form


def mac_alias_payload(name: str, macs: list[str], description: str) -> dict:
    return {
        "enabled": "1",
        "name": name,
        "type": "mac",
        "proto": "",
        "interface": "",
        "counters": "0",
        "updatefreq": "",
        "content": "\n".join(macs),
        "password": "",
        "username": "",
        "authtype": "",
        "expire": "",
        "categories": "",
        "description": description,
        "path_expression": "",
    }


def ensure_mac_alias(name: str, macs: list[str], description: str) -> str:
    payload = {"alias": mac_alias_payload(name, macs, description)}
    rows = api("POST", "/api/firewall/alias/searchItem", {}).get("rows", [])
    existing = next((r for r in rows if r.get("name") == name), None)
    if existing:
        uuid = existing["uuid"]
        res = api("POST", f"/api/firewall/alias/setItem/{uuid}", payload)
        print(f"alias UPDATE {name} ({len(macs)} macs): {res}")
        return uuid

    res = api("POST", "/api/firewall/alias/addItem", payload)
    print(f"alias ADD {name} ({len(macs)} macs): {res}")
    uuid = res.get("uuid")
    if not uuid:
        raise SystemExit(f"failed to create alias {name}: {res}")
    return uuid


def rule_body(spec: dict) -> dict:
    body = {
        "enabled": "0",
        "action": "pass",
        "quick": "1",
        "interface": "opt3",
        "direction": "in",
        "ipprotocol": "inet",
        "protocol": "any",
        "source_net": spec["source_net"],
        "source_not": "0",
        "destination_net": spec["destination_net"],
        "destination_not": spec["destination_not"],
        "log": "0",
        "statetype": "keep",
        "description": spec["description"],
    }
    if spec.get("gateway"):
        body["gateway"] = spec["gateway"]
    return body


def ensure_disabled_rule(spec: dict) -> str:
    desc = spec["description"]
    payload = {"rule": rule_body(spec)}
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if (row.get("description") or "") == desc:
            uuid = row["uuid"]
            res = api("POST", f"/api/firewall/filter/setRule/{uuid}", payload)
            print(f"rule UPDATE enabled=0 | {desc}: {res}")
            return uuid

    res = api("POST", "/api/firewall/filter/addRule", payload)
    print(f"rule ADD enabled=0 | {desc}: {res}")
    uuid = res.get("uuid")
    if not uuid:
        raise SystemExit(f"failed to add rule {desc}: {res}")
    return uuid


def main() -> int:
    laptops = read_macs(LAPTOPS_CSV)
    mobiles = read_macs(MOBILES_CSV)
    combined = sorted(set(laptops) | set(mobiles))

    print(f"laptops={len(laptops)} mobiles={len(mobiles)} combined={len(combined)}")

    ensure_mac_alias(
        "WL_CORP_LAPTOPS",
        laptops,
        "Corp Wi-Fi laptop MACs from current leases",
    )
    ensure_mac_alias(
        "WL_CORP_MOBILES",
        mobiles,
        "Corp Wi-Fi mobile MACs from current leases",
    )
    ensure_mac_alias(
        "WL_CORP_MACS",
        combined,
        "Corp Wi-Fi MACs (laptops+mobiles union from leases)",
    )

    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))

    for spec in RULE_SPECS:
        ensure_disabled_rule(spec)

    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    print("\nVERIFY aliases:")
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("WL_CORP_MACS", "WL_CORP_LAPTOPS", "WL_CORP_MOBILES"):
            content = str(row.get("content") or "")
            n = len([x for x in content.replace(",", "\n").splitlines() if x.strip()])
            print(f"  {row['name']}: type={row.get('type')} macs~{n}")

    print("\nVERIFY new/disabled rules:")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        desc = row.get("description") or ""
        if "WL_CORP_LAPTOPS" in desc or "WL_CORP_MOBILES" in desc:
            print(
                f"  en={row.get('enabled')} {row.get('action')} "
                f"src={row.get('source_net')} dst={row.get('destination_net')} | {desc}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
