#!/usr/bin/env python3
"""Merge duplicate per-WAN rules into multi-interface (floating-style) rules."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()

# Keep these; expand interface to wan+opt1; delete the duplicate partner.
MERGES = [
    {
        "keep": "a8645db6-7a3e-4de6-a2d7-be6f6c291693",  # Block WAN GUI/SSH (wan)
        "delete": "d407802e-cd95-4d91-beee-778924ad7a41",  # Block Jio WAN GUI/SSH
        "description": "Block WAN to firewall GUI/SSH",
        "interface": "wan,opt1",
    },
    {
        "keep": "d3afe269-6a1b-45d8-963c-5b1c08249b1a",  # WG Airtel
        "delete": "6a5ce743-d1c7-4cdd-aa5c-d6f8f088b80f",  # WG Jio
        "description": "Allow WireGuard UDP 51820 on WAN",
        "interface": "wan,opt1",
    },
]


def load_creds():
    creds = {}
    for line in KEYFILE.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
    return creds["key"], creds["secret"]


def api(method: str, path: str, key: str, secret: str, data=None):
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {path}: {e.read().decode()[:800]}") from e
    if raw.lstrip().startswith("<!"):
        raise SystemExit(f"Auth failed {path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def selected_keys(field) -> str:
    """Convert getRule option maps into comma-separated selected keys for setRule."""
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, (list, tuple)):
        return ",".join(str(x) for x in field if x not in ("", None))
    if isinstance(field, dict):
        selected = []
        for name, meta in field.items():
            if name == "" and isinstance(meta, dict) and str(meta.get("selected")) in (
                "1",
                "true",
                "True",
            ):
                # "None" option selected
                return ""
            if isinstance(meta, dict) and str(meta.get("selected")) in ("1", "true", "True"):
                selected.append(name)
            elif meta in (1, "1", True):
                selected.append(name)
        return ",".join(selected)
    return str(field)


def rule_to_set_payload(rule: dict, overrides: dict) -> dict:
    """Build a setRule payload from getRule output + overrides."""
    # Fields that are option maps in get responses
    option_fields = (
        "statetype",
        "state-policy",
        "action",
        "interface",
        "direction",
        "ipprotocol",
        "protocol",
        "gateway",
        "replyto",
        "categories",
        "sched",
        "icmptype",
        "icmp6type",
        "shaper1",
        "shaper2",
        "prio",
        "set-prio",
        "set-prio-low",
        "tos",
        "overload",
        "received-on",
    )
    # Empty values for these often fail validation; omit unless selected
    omit_if_empty = {
        "categories",
        "sched",
        "gateway",
        "replyto",
        "shaper1",
        "shaper2",
        "prio",
        "set-prio",
        "set-prio-low",
        "tos",
        "overload",
        "received-on",
        "icmptype",
        "icmp6type",
        "state-policy",
    }
    out = {}
    for k, v in rule.items():
        if k in ("audit",):
            continue
        if k in option_fields:
            sel = selected_keys(v)
            if not sel and k in omit_if_empty:
                continue
            out[k] = sel
        elif isinstance(v, dict):
            continue
        else:
            out[k] = v if v is not None else ""
    out.update(overrides)
    # Ensure overrides don't reintroduce empty optional fields
    for k in list(out.keys()):
        if k in omit_if_empty and out[k] in ("", None, []):
            del out[k]
    return {"rule": out}


def main():
    key, secret = load_creds()
    print(f"Host {BASE}")

    for m in MERGES:
        keep = m["keep"]
        delete = m["delete"]
        got = api("GET", f"/api/firewall/filter/getRule/{keep}", key, secret)
        rule = got.get("rule") if isinstance(got, dict) else None
        if not rule:
            raise SystemExit(f"Missing keep rule {keep}")

        payload = rule_to_set_payload(
            rule,
            {
                "interface": m["interface"],
                "description": m["description"],
            },
        )
        print(f"\nSET {keep}")
        print(f"  interface -> {m['interface']}")
        print(f"  description -> {m['description']}")
        result = api("POST", f"/api/firewall/filter/setRule/{keep}", key, secret, payload)
        print(f"  result: {result}")
        if isinstance(result, dict) and result.get("result") not in ("saved", "ok", "OK"):
            # still try if validations empty
            if result.get("validations"):
                raise SystemExit(f"setRule failed: {result}")

        del_result = api("POST", f"/api/firewall/filter/delRule/{delete}", key, secret, {})
        print(f"DEL {delete} -> {del_result}")

    apply = api("POST", "/api/firewall/filter/apply", key, secret, {})
    print(f"\nAPPLY -> {apply}")

    # Verify
    import urllib.parse

    q = urllib.parse.urlencode({"current": 1, "rowCount": 200, "searchPhrase": ""})
    page = api("GET", f"/api/firewall/filter/searchRule?{q}", key, secret)
    rows = page.get("rows") or []
    print("\nVerification (matching merged rules):")
    for r in rows:
        desc = r.get("description") or r.get("descr") or ""
        if "GUI/SSH" in desc or "WireGuard" in desc or "51820" in desc:
            print(
                f"  {r.get('uuid')} | if={r.get('interface')} | "
                f"action={r.get('action')} | {desc}"
            )


if __name__ == "__main__":
    main()
