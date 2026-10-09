#!/usr/bin/env python3
"""Retry: set WG firewall rule source to WG_FW_ADMINS with minimal payload."""
from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()
WG_SELF = "aadf170f-d2a7-4de0-8f37-bc85fd571ec7"
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
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} HTTP {e.code}: {err[:1500]}") from e


def selected_keys(node):
    return [k for k, v in node.items() if isinstance(v, dict) and v.get("selected") in (1, "1", True)]


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


def clean_rule(rule: dict) -> dict:
    drop = {
        "audit",
        "sort_order",
        "prio_group",
        "category_colors",
        "alias_meta_source_net",
        "alias_meta_destination_net",
        "%interface",
        "%action",
        "%direction",
        "%ipprotocol",
        "%destination_net",
    }
    for k in list(rule.keys()):
        if k in drop or k.startswith("%") or k.startswith("alias_meta"):
            rule.pop(k, None)
    return rule


def main():
    raw = api("GET", f"/api/firewall/filter/getRule/{WG_SELF}")
    rule = clean_rule(flatten(raw["rule"]))
    print("flattened keys sample:", sorted(rule.keys())[:40])
    print(
        "before:",
        {
            k: rule.get(k)
            for k in (
                "source_net",
                "destination_net",
                "destination_port",
                "protocol",
                "interface",
                "description",
                "enabled",
            )
        },
    )

    # Minimal change first: source only
    rule["source_net"] = "WG_FW_ADMINS"
    rule["description"] = "WG FW admins only to firewall (GUI/SSH)"
    # Keep destination_port empty (any) for now if ADMIN_PORTS causes 500;
    # try ADMIN_PORTS after source works.
    try:
        rule2 = dict(rule)
        rule2["protocol"] = "tcp"
        rule2["destination_port"] = "ADMIN_PORTS"
        print("try with ADMIN_PORTS:", api("POST", f"/api/firewall/filter/setRule/{WG_SELF}", {"rule": rule2}))
    except Exception as e:
        print("ADMIN_PORTS failed:", e)
        print("retry source-only:", api("POST", f"/api/firewall/filter/setRule/{WG_SELF}", {"rule": rule}))

    # CORP description tweak optional
    corp = clean_rule(flatten(api("GET", f"/api/firewall/filter/getRule/{WG_CORP}")["rule"]))
    corp["source_net"] = "10.80.200.0/28"
    corp["destination_net"] = "CORP_INTERNAL"
    corp["description"] = "WG peers to CORP_INTERNAL (no guest; no FW)"
    print("CORP:", api("POST", f"/api/firewall/filter/setRule/{WG_CORP}", {"rule": corp}))

    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))
    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if row.get("uuid") in (WG_SELF, WG_CORP):
            print(
                f"VERIFY {row['uuid']} src={row.get('source_net')} dst={row.get('destination_net')} "
                f"dport={row.get('destination_port')} | {row.get('description')}"
            )
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") == "WG_FW_ADMINS":
            print(f"VERIFY alias content={row.get('content')!r}")


if __name__ == "__main__":
    main()
