#!/usr/bin/env python3
"""Finish WG FW lockdown: CORP without firewall IPs + explicit non-admin block to (self)."""
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

# PeakPulse / corp app nets only — exclude MGMT 10.80.99.0/24 (firewall GUI lives there)
CORP_CONTENT = "10.80.100.0/24\n10.80.101.0/24"
CORP_NAME = "CORP_INTERNAL"

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


def ensure_corp_alias():
    rows = api("POST", "/api/firewall/alias/searchItem", {}).get("rows", [])
    existing = next((r for r in rows if r.get("name") == CORP_NAME), None)
    if existing:
        uuid = existing["uuid"]
        form = flatten_alias(api("GET", f"/api/firewall/alias/getItem/{uuid}")["alias"])
        form["content"] = CORP_CONTENT
        form["description"] = "WIRED_CORP+WL_CORP only (no MGMT/firewall)"
        form["type"] = "network"
        for k in list(form.keys()):
            if k.startswith("in_") or k.startswith("out_") or k in (
                "current_items", "last_updated", "eval_nomatch", "eval_match",
            ):
                form.pop(k, None)
        print("CORP_INTERNAL update:", api("POST", f"/api/firewall/alias/setItem/{uuid}", {"alias": form}))
        return uuid

    form = flatten_alias(api("GET", "/api/firewall/alias/getItem")["alias"])
    form.update(
        {
            "enabled": "1",
            "name": CORP_NAME,
            "type": "network",
            "content": CORP_CONTENT,
            "description": "WIRED_CORP+WL_CORP only (no MGMT/firewall)",
            "counters": "0",
            "path_expression": "",
            "updatefreq": "",
            "password": "",
            "username": "",
            "expire": "",
            "proto": "",
            "interface": "",
            "authtype": "",
            "categories": "",
        }
    )
    for k in list(form.keys()):
        if k.startswith("in_") or k.startswith("out_") or k in (
            "current_items", "last_updated", "eval_nomatch", "eval_match",
        ):
            form.pop(k, None)
    res = api("POST", "/api/firewall/alias/addItem", {"alias": form})
    print("CORP_INTERNAL add:", res)
    return res.get("uuid")


def set_rule(uuid, **overrides):
    rule = api("GET", f"/api/firewall/filter/getRule/{uuid}")["rule"]
    payload = rule_to_set_payload(rule, overrides)
    return api("POST", f"/api/firewall/filter/setRule/{uuid}", payload)


def ensure_block_non_admin_to_self():
    """Block WG peers not in WG_FW_ADMINS from reaching This Firewall."""
    desc = "Block non-admin WG to firewall (self)"
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if row.get("description") == desc:
            print(f"block rule exists {row['uuid']}")
            return row["uuid"]

    # Clone shape from WG_SELF pass rule, flip to block + invert source
    base = api("GET", f"/api/firewall/filter/getRule/{WG_SELF}")["rule"]
    payload = rule_to_set_payload(
        base,
        {
            "enabled": "1",
            "action": "block",
            "sequence": "940",  # before admin pass (951); after CORP (901)
            "interface": "opt6",
            "direction": "in",
            "ipprotocol": "inet",
            "protocol": "any",
            "source_net": "WG_FW_ADMINS",
            "source_not": "1",  # everyone except FW admins
            "destination_net": "(self)",
            "destination_not": "0",
            "destination_port": "",
            "description": desc,
            "log": "1",
            "quick": "1",
        },
    )
    # addRule instead of setRule
    res = api("POST", "/api/firewall/filter/addRule", payload)
    print("add block rule:", res)
    return res.get("uuid")


def main() -> int:
    ensure_corp_alias()
    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))

    print(
        "set WG_CORP:",
        set_rule(
            WG_CORP,
            source_net="10.80.200.0/28",
            destination_net=CORP_NAME,
            destination_not="0",
            description="WG peers to CORP_INTERNAL (no MGMT/FW)",
        ),
    )
    print(
        "set WG_SELF:",
        set_rule(
            WG_SELF,
            source_net="WG_FW_ADMINS",
            destination_net="(self)",
            description="WG FW admins only to firewall (GUI/SSH)",
        ),
    )
    ensure_block_non_admin_to_self()
    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    print("\nVERIFY aliases:")
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("WG_FW_ADMINS", "CORP_INTERNAL"):
            print(f"  {row['name']}={row.get('content')!r}")

    print("VERIFY rules:")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        desc = str(row.get("description") or "")
        if row.get("uuid") in (WG_SELF, WG_CORP) or "WG" in desc or "firewall" in desc.lower():
            if "WireGuard UDP" in desc:
                continue
            print(
                f"  seq={row.get('sequence')} act={row.get('action')} "
                f"src={row.get('source_net')} src_not={row.get('source_not')} "
                f"dst={row.get('destination_net')} | {desc}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
