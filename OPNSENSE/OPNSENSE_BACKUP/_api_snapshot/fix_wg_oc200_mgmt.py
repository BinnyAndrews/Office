#!/usr/bin/env python3
"""Restore WG access to MGMT VLAN (OC200 etc.) while keeping FW self locked down.

CORP_INTERNAL = MGMT + WIRED_CORP + WL_CORP.
Non-admin WG still blocked to (self) at seq 890 before CORP pass at 901.
"""
from __future__ import annotations

import base64
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()
CORP_UUID = "36bcab3f-cfbc-40e4-b195-098614cd1715"
CORP_CONTENT = "10.80.99.0/24\n10.80.100.0/24\n10.80.101.0/24"
WG_SELF = "aadf170f-d2a7-4de0-8f37-bc85fd571ec7"
WG_BLOCK = "4fc691f3-ebb4-4b1c-be2f-f40b4abb8272"
WG_CORP = "855bf1aa-21de-463e-8bf9-fbc2542abceb"


def load_creds():
    key = secret = ""
    for line in CRED.read_text(encoding="utf-8").splitlines():
        if line.startswith("key="):
            key = line[4:]
        elif line.startswith("secret="):
            secret = line[7:]
    return key, secret


def api(method, path, payload=None):
    key, secret = load_creds()
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def flatten_alias(node):
    if not isinstance(node, dict):
        return node
    if node and all(isinstance(v, dict) and "selected" in v for v in node.values()):
        sel = [k for k, v in node.items() if v.get("selected") in (1, "1", True)]
        return sel[0] if len(sel) == 1 else ",".join(sel) if sel else ""
    out = {}
    for k, v in node.items():
        if isinstance(v, dict):
            out[k] = flatten_alias(v)
        elif isinstance(v, list):
            out[k] = [flatten_alias(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


def main() -> int:
    # Find CORP_INTERNAL by name in case UUID differs
    rows = api("POST", "/api/firewall/alias/searchItem", {}).get("rows", [])
    corp = next((r for r in rows if r.get("name") == "CORP_INTERNAL"), None)
    if not corp:
        raise SystemExit("CORP_INTERNAL alias missing")
    uuid = corp["uuid"]
    form = flatten_alias(api("GET", f"/api/firewall/alias/getItem/{uuid}")["alias"])
    form["content"] = CORP_CONTENT
    form["description"] = "MGMT+WIRED+WL_CORP; FW GUI still gated by WG self rules"
    form["type"] = "network"
    for k in list(form.keys()):
        if k.startswith("in_") or k.startswith("out_") or k in (
            "current_items", "last_updated", "eval_nomatch", "eval_match",
        ):
            form.pop(k, None)
    print("set CORP_INTERNAL:", api("POST", f"/api/firewall/alias/setItem/{uuid}", {"alias": form}))
    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))
    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    print("\nVERIFY alias:")
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("CORP_INTERNAL", "WG_FW_ADMINS"):
            print(f"  {row['name']}={row.get('content')!r}")

    print("VERIFY rule order:")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if row.get("uuid") in (WG_SELF, WG_BLOCK, WG_CORP):
            print(
                f"  seq={row.get('sequence')} {row.get('action'):5} "
                f"src={row.get('source_net')} dst={row.get('destination_net')} "
                f"| {row.get('description')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
