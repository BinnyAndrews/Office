#!/usr/bin/env python3
"""Block RDP (TCP 3389) for Venu, Poovarasu, Sanoj over WireGuard.

Jagadeshwar (.4) and admins (.2/.3) keep RDP to CORP.
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

ALIAS = "WG_NO_RDP"
ALIAS_CONTENT = "10.80.200.5/32\n10.80.200.6/32\n10.80.200.7/32"  # venu, poovarasu, sanoj
RULE_DESC = "Block RDP for AMC WG peers (Venu/Poovarasu/Sanoj)"
WG_CORP = "855bf1aa-21de-463e-8bf9-fbc2542abceb"
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


def ensure_alias():
    rows = api("POST", "/api/firewall/alias/searchItem", {}).get("rows", [])
    existing = next((r for r in rows if r.get("name") == ALIAS), None)
    if existing:
        uuid = existing["uuid"]
        raw = api("GET", f"/api/firewall/alias/getItem/{uuid}")["alias"]
        alias = {
            "enabled": "1",
            "name": ALIAS,
            "type": selected_keys(raw.get("type")) or "network",
            "proto": "",
            "interface": "",
            "counters": raw.get("counters", "0"),
            "updatefreq": "",
            "content": ALIAS_CONTENT,
            "password": "",
            "username": "",
            "authtype": "",
            "categories": "",
            "expire": "",
            "path_expression": "",
            "description": "WG peers blocked from RDP (Venu/Poovarasu/Sanoj)",
        }
        print("alias update:", api("POST", f"/api/firewall/alias/setItem/{uuid}", {"alias": alias}))
        return uuid

    alias = {
        "enabled": "1",
        "name": ALIAS,
        "type": "network",
        "proto": "",
        "interface": "",
        "counters": "0",
        "updatefreq": "",
        "content": ALIAS_CONTENT,
        "password": "",
        "username": "",
        "authtype": "",
        "categories": "",
        "expire": "",
        "path_expression": "",
        "description": "WG peers blocked from RDP (Venu/Poovarasu/Sanoj)",
    }
    res = api("POST", "/api/firewall/alias/addItem", {"alias": alias})
    print("alias add:", res)
    return res.get("uuid")


def ensure_block_rule():
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if row.get("description") == RULE_DESC:
            print("update existing", row["uuid"])
            base = api("GET", f"/api/firewall/filter/getRule/{row['uuid']}")["rule"]
            print(
                "set:",
                api(
                    "POST",
                    f"/api/firewall/filter/setRule/{row['uuid']}",
                    rule_to_set_payload(
                        base,
                        {
                            "enabled": "1",
                            "action": "block",
                            "sequence": "895",
                            "interface": "opt6",
                            "direction": "in",
                            "ipprotocol": "inet",
                            "protocol": "tcp",
                            "source_net": ALIAS,
                            "source_not": "0",
                            "destination_net": "CORP_INTERNAL",
                            "destination_not": "0",
                            "destination_port": "3389",
                            "quick": "1",
                            "log": "1",
                            "description": RULE_DESC,
                        },
                    ),
                ),
            )
            return row["uuid"]

    base = api("GET", f"/api/firewall/filter/getRule/{WG_SELF}")["rule"]
    payload = rule_to_set_payload(
        base,
        {
            "enabled": "1",
            "action": "block",
            "sequence": "895",
            "interface": "opt6",
            "direction": "in",
            "ipprotocol": "inet",
            "protocol": "tcp",
            "source_net": ALIAS,
            "source_not": "0",
            "destination_net": "CORP_INTERNAL",
            "destination_not": "0",
            "destination_port": "3389",
            "quick": "1",
            "log": "1",
            "description": RULE_DESC,
        },
    )
    res = api("POST", "/api/firewall/filter/addRule", payload)
    print("add block:", res)
    return res.get("uuid")


def main() -> int:
    ensure_alias()
    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))
    ensure_block_rule()

    # Keep CORP pass after the RDP block
    corp = api("GET", f"/api/firewall/filter/getRule/{WG_CORP}")["rule"]
    print(
        "CORP seq 901:",
        api(
            "POST",
            f"/api/firewall/filter/setRule/{WG_CORP}",
            rule_to_set_payload(
                corp,
                {
                    "sequence": "901",
                    "source_net": "10.80.200.0/28",
                    "destination_net": "CORP_INTERNAL",
                    "description": "WG peers to CORP_INTERNAL (no MGMT)",
                },
            ),
        ),
    )

    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    print("\nVERIFY:")
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") == ALIAS:
            print(f"  alias {ALIAS}={row.get('content')!r}")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        desc = str(row.get("description") or "")
        if row.get("uuid") == WG_CORP or desc == RULE_DESC or "RDP" in desc:
            print(
                f"  seq={row.get('sequence')} {row.get('action')} "
                f"src={row.get('source_net')} dst={row.get('destination_net')} "
                f"dport={row.get('destination_port')} | {desc}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
