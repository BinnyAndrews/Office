#!/usr/bin/env python3
"""Harden WG DNS allow: port 53 (not only alias), quick pass before self-block."""
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

RULE_DESC = "Allow WG DNS to Unbound"
DNS_UUID = "f92750e0-04a2-4995-837b-e73cc4e8e336"
WG_SELF = "aadf170f-d2a7-4de0-8f37-bc85fd571ec7"

OMIT_IF_EMPTY = {
    "categories", "sched", "gateway", "replyto", "shaper1", "shaper2", "prio",
    "set-prio", "set-prio-low", "tos", "overload", "received-on", "icmptype",
    "icmp6type", "state-policy",
}
OPTION_FIELDS = (
    "statetype", "state-policy", "action", "interface", "direction", "ipprotocol",
    "protocol", "gateway", "replyto", "categories", "sched", "icmptype", "icmp6type",
    "shaper1", "shaper2", "prio", "set-prio", "set-prio-low", "tos", "overload",
    "received-on",
)


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


def selected_keys(field) -> str:
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, (list, tuple)):
        return ",".join(str(x) for x in field if x not in ("", None))
    if isinstance(field, dict):
        selected = []
        for name, meta in field.items():
            if isinstance(meta, dict) and str(meta.get("selected")) in ("1", "true", "True"):
                selected.append(name)
            elif meta in (1, "1", True):
                selected.append(name)
        return ",".join(selected)
    return str(field)


def rule_to_set_payload(rule: dict, overrides: dict) -> dict:
    out = {}
    for k, v in rule.items():
        if k in ("audit", "sort_order", "prio_group", "category_colors"):
            continue
        if k.startswith("%") or k.startswith("alias_meta"):
            continue
        if k in OPTION_FIELDS:
            sel = selected_keys(v)
            if not sel and k in OMIT_IF_EMPTY:
                continue
            out[k] = sel
        elif isinstance(v, dict):
            continue
        else:
            out[k] = v if v is not None else ""
    out.update(overrides)
    for k in list(out.keys()):
        if k in OMIT_IF_EMPTY and out[k] in ("", None, []):
            del out[k]
    return {"rule": out}


def main() -> int:
    base = api("GET", f"/api/firewall/filter/getRule/{DNS_UUID}")["rule"]
    print(
        "update DNS rule:",
        api(
            "POST",
            f"/api/firewall/filter/setRule/{DNS_UUID}",
            rule_to_set_payload(
                base,
                {
                    "enabled": "1",
                    "action": "pass",
                    "sequence": "881",
                    "interface": "opt6",
                    "direction": "in",
                    "ipprotocol": "inet",
                    "protocol": "TCP/UDP",
                    "source_net": "10.80.200.0/28",
                    "source_not": "0",
                    "destination_net": "(self)",
                    "destination_not": "0",
                    "destination_port": "53",
                    "quick": "1",
                    "log": "1",
                    "description": RULE_DESC,
                },
            ),
        ),
    )

    # Second pass: Unbound on WG tunnel IP (same-interface path)
    desc2 = "Allow WG DNS to Unbound (10.80.200.1)"
    existing = None
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if str(row.get("description") or "") == desc2:
            existing = row["uuid"]
            break

    overrides = {
        "enabled": "1",
        "action": "pass",
        "sequence": "882",
        "interface": "opt6",
        "direction": "in",
        "ipprotocol": "inet",
        "protocol": "TCP/UDP",
        "source_net": "10.80.200.0/28",
        "source_not": "0",
        "destination_net": "10.80.200.1",
        "destination_not": "0",
        "destination_port": "53",
        "quick": "1",
        "log": "1",
        "description": desc2,
    }
    if existing:
        b2 = api("GET", f"/api/firewall/filter/getRule/{existing}")["rule"]
        print("update DNS-200.1:", api("POST", f"/api/firewall/filter/setRule/{existing}", rule_to_set_payload(b2, overrides)))
    else:
        b2 = api("GET", f"/api/firewall/filter/getRule/{WG_SELF}")["rule"]
        print("add DNS-200.1:", api("POST", "/api/firewall/filter/addRule", rule_to_set_payload(b2, overrides)))

    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    print("\nVERIFY:")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        desc = str(row.get("description") or "")
        if "WG DNS" in desc or "firewall (self)" in desc or "FW admins only" in desc:
            print(
                f"  seq={row.get('sequence')} {row.get('action')} "
                f"src={row.get('source_net')} dst={row.get('destination_net')} "
                f"dport={row.get('destination_port')} log={row.get('log')} | {desc}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
