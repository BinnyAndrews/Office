#!/usr/bin/env python3
"""WG: only binny+admin may reach MGMT (10.80.99.0/24). Others keep CORP .100/.101."""
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
WG_BLOCK = "4fc691f3-ebb4-4b1c-be2f-f40b4abb8272"
WG_CORP = "855bf1aa-21de-463e-8bf9-fbc2542abceb"
MGMT_RULE_DESC = "WG FW admins to MGMT VLAN"
CORP_CONTENT = "10.80.100.0/24\n10.80.101.0/24"

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


def set_rule(uuid, **overrides):
    rule = api("GET", f"/api/firewall/filter/getRule/{uuid}")["rule"]
    return api("POST", f"/api/firewall/filter/setRule/{uuid}", rule_to_set_payload(rule, overrides))


def set_corp_alias():
    rows = api("POST", "/api/firewall/alias/searchItem", {}).get("rows", [])
    corp = next((r for r in rows if r.get("name") == "CORP_INTERNAL"), None)
    if not corp:
        raise SystemExit("CORP_INTERNAL missing")
    uuid = corp["uuid"]
    raw = api("GET", f"/api/firewall/alias/getItem/{uuid}")["alias"]
    alias = {
        "enabled": raw.get("enabled", "1"),
        "name": "CORP_INTERNAL",
        "type": selected_keys(raw.get("type")) or "network",
        "proto": "",
        "interface": "",
        "counters": raw.get("counters", "0"),
        "updatefreq": "",
        "content": CORP_CONTENT,
        "password": "",
        "username": "",
        "authtype": "",
        "categories": "",
        "expire": "",
        "path_expression": "",
        "description": "WIRED_CORP+WL_CORP only (PeakPulse); MGMT via WG admins rule",
    }
    print("CORP_INTERNAL set:", api("POST", f"/api/firewall/alias/setItem/{uuid}", {"alias": alias}))


def ensure_mgmt_rule():
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if row.get("description") == MGMT_RULE_DESC:
            print("update existing MGMT rule", row["uuid"])
            print(
                "set:",
                set_rule(
                    row["uuid"],
                    enabled="1",
                    action="pass",
                    sequence="885",
                    interface="opt6",
                    direction="in",
                    ipprotocol="inet",
                    protocol="any",
                    source_net="WG_FW_ADMINS",
                    source_not="0",
                    destination_net="10.80.99.0/24",
                    destination_not="0",
                    destination_port="",
                    quick="1",
                    description=MGMT_RULE_DESC,
                ),
            )
            return row["uuid"]

    base = api("GET", f"/api/firewall/filter/getRule/{WG_SELF}")["rule"]
    payload = rule_to_set_payload(
        base,
        {
            "enabled": "1",
            "action": "pass",
            "sequence": "885",
            "interface": "opt6",
            "direction": "in",
            "ipprotocol": "inet",
            "protocol": "any",
            "source_net": "WG_FW_ADMINS",
            "source_not": "0",
            "destination_net": "10.80.99.0/24",
            "destination_not": "0",
            "destination_port": "",
            "quick": "1",
            "log": "0",
            "description": MGMT_RULE_DESC,
        },
    )
    res = api("POST", "/api/firewall/filter/addRule", payload)
    print("add MGMT rule:", res)
    return res.get("uuid")


def main() -> int:
    set_corp_alias()
    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))

    ensure_mgmt_rule()

    # Keep order: 880 self admin, 885 MGMT admin, 890 block non-admin self, 901 CORP
    print(
        "self admin:",
        set_rule(
            WG_SELF,
            sequence="880",
            source_net="WG_FW_ADMINS",
            destination_net="(self)",
            action="pass",
            quick="1",
            description="WG FW admins only to firewall (GUI/SSH)",
        ),
    )
    print(
        "block non-admin self:",
        set_rule(
            WG_BLOCK,
            sequence="890",
            source_net="10.80.200.0/28",
            destination_net="(self)",
            action="block",
            quick="1",
            log="1",
            description="Block non-admin WG to firewall (self)",
        ),
    )
    print(
        "CORP peers:",
        set_rule(
            WG_CORP,
            sequence="901",
            source_net="10.80.200.0/28",
            destination_net="CORP_INTERNAL",
            description="WG peers to CORP_INTERNAL (no MGMT)",
        ),
    )

    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    print("\nVERIFY alias CORP_INTERNAL:")
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") in ("CORP_INTERNAL", "WG_FW_ADMINS"):
            print(f"  {row['name']}={row.get('content')!r}")

    print("VERIFY WG rules:")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        desc = str(row.get("description") or "")
        if row.get("uuid") in (WG_SELF, WG_BLOCK, WG_CORP) or desc == MGMT_RULE_DESC:
            print(
                f"  seq={row.get('sequence')} {str(row.get('action')):5} "
                f"src={row.get('source_net')} dst={row.get('destination_net')} | {desc}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
