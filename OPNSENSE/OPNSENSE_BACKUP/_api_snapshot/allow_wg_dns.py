#!/usr/bin/env python3
"""Allow WireGuard peers (10.80.200.0/28) DNS to Unbound on This Firewall.

Must sit before "Block non-admin WG to firewall (self)" (seq 890).
"""
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
WG_SELF = "aadf170f-d2a7-4de0-8f37-bc85fd571ec7"
WG_BLOCK = "4fc691f3-ebb4-4b1c-be2f-f40b4abb8272"
SEQUENCE = "882"  # after admin self (880), before block (890)

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


def find_existing():
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if str(row.get("description") or "") == RULE_DESC:
            return row
    return None


def ensure_dns_rule():
    existing = find_existing()
    if existing:
        uuid = existing["uuid"]
        base = api("GET", f"/api/firewall/filter/getRule/{uuid}")["rule"]
        res = api(
            "POST",
            f"/api/firewall/filter/setRule/{uuid}",
            rule_to_set_payload(
                base,
                {
                    "enabled": "1",
                    "action": "pass",
                    "sequence": SEQUENCE,
                    "interface": "opt6",
                    "direction": "in",
                    "ipprotocol": "inet",
                    "protocol": "TCP/UDP",
                    "source_net": "10.80.200.0/28",
                    "source_not": "0",
                    "destination_net": "(self)",
                    "destination_not": "0",
                    "destination_port": "domain",
                    "quick": "1",
                    "log": "0",
                    "description": RULE_DESC,
                },
            ),
        )
        print("update DNS rule:", res)
        return uuid

    base = api("GET", f"/api/firewall/filter/getRule/{WG_SELF}")["rule"]
    payload = rule_to_set_payload(
        base,
        {
            "enabled": "1",
            "action": "pass",
            "sequence": SEQUENCE,
            "interface": "opt6",
            "direction": "in",
            "ipprotocol": "inet",
            "protocol": "TCP/UDP",
            "source_net": "10.80.200.0/28",
            "source_not": "0",
            "destination_net": "(self)",
            "destination_not": "0",
            "destination_port": "domain",
            "quick": "1",
            "log": "0",
            "description": RULE_DESC,
        },
    )
    res = api("POST", "/api/firewall/filter/addRule", payload)
    print("add DNS rule:", res)
    return res.get("uuid")


def main() -> int:
    uuid = ensure_dns_rule()
    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    print("\nVERIFY WG DNS / self rules:")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        desc = str(row.get("description") or "")
        if row.get("uuid") in (WG_SELF, WG_BLOCK, uuid) or "DNS" in desc or "firewall" in desc.lower():
            if "WG" in desc or desc == RULE_DESC or row.get("uuid") in (WG_SELF, WG_BLOCK, uuid):
                print(
                    f"  seq={row.get('sequence')} {str(row.get('action')):5} "
                    f"src={row.get('source_net')} dst={row.get('destination_net')} "
                    f"dport={row.get('destination_port')} | {desc}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
