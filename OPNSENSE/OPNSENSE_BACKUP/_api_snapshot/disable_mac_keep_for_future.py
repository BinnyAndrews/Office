#!/usr/bin/env python3
"""Disable MAC policy now; keep MAC rules for future enable. Restore open WL_CORP access."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()

MAC_RULES = [
    ("ec42364f-09b4-4133-bdd7-eb03dfd3a2f2", "Allow WL_CORP_MACS to Internet via WAN_LB"),
    ("8af6f814-5b8a-4f93-8db3-eb3f4248c1fc", "Allow WL_CORP_MACS to WIRED_CORP"),
    ("a30a91bf-3393-4e49-85f2-77143cde5311", "Allow WL_CORP_MACS to MGMT"),
    ("4bd7e3ec-20e9-4c0c-8262-006f294131c8", "Block unknown WL_CORP MACs"),
]

# Recreate open WL_CORP passes (deleted earlier)
OPEN_RULES = [
    {
        "enabled": "1",
        "action": "pass",
        "quick": "1",
        "interface": "opt3",
        "direction": "in",
        "ipprotocol": "inet",
        "protocol": "any",
        "source_net": "WL_CORP",
        "destination_net": "WIRED_CORP",
        "destination_not": "0",
        "log": "0",
        "statetype": "keep",
        "description": "Allow WL_CORP to WIRED_CORP",
        "sequence": "291",
    },
    {
        "enabled": "1",
        "action": "pass",
        "quick": "1",
        "interface": "opt3",
        "direction": "in",
        "ipprotocol": "inet",
        "protocol": "any",
        "source_net": "WL_CORP",
        "destination_net": "MGMT",
        "destination_not": "0",
        "log": "0",
        "statetype": "keep",
        "description": "Allow WL_CORP to MGMT",
        "sequence": "292",
    },
    {
        "enabled": "1",
        "action": "pass",
        "quick": "1",
        "interface": "opt3",
        "direction": "in",
        "ipprotocol": "inet",
        "protocol": "any",
        "source_net": "WL_CORP",
        "destination_net": "LAN_RFC1918",
        "destination_not": "1",
        "gateway": "WAN_LB",
        "log": "0",
        "statetype": "keep",
        "description": "Allow WL_CORP to Internet via WAN_LB",
        "sequence": "295",
    },
]


def load_creds():
    creds = {}
    for line in KEYFILE.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
    return creds["key"], creds["secret"]


def api(method, path, key, secret, data=None):
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
        return json.loads(resp.read().decode())


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
            if name == "" and isinstance(meta, dict) and str(meta.get("selected")) in (
                "1",
                "true",
                "True",
            ):
                return ""
            if isinstance(meta, dict) and str(meta.get("selected")) in ("1", "true", "True"):
                selected.append(name)
        return ",".join(selected)
    return str(field)


OMIT = {
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
OPTIONS = (
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
)


def set_enabled(key, secret, uuid, enabled, label):
    got = api("GET", f"/api/firewall/filter/getRule/{uuid}", key, secret)
    rule = got.get("rule")
    if not isinstance(rule, dict) or not rule:
        print(f"MISSING {label} {uuid}")
        return
    out = {}
    for k, v in rule.items():
        if k == "audit":
            continue
        if k in OPTIONS:
            sel = selected_keys(v)
            if not sel and k in OMIT:
                continue
            out[k] = sel
        elif isinstance(v, dict):
            continue
        else:
            out[k] = v if v is not None else ""
    out["enabled"] = str(enabled)
    # Keep descriptions clear for future
    if enabled == 0 and "MAC" in label:
        if "Block unknown" in (out.get("description") or ""):
            out["description"] = "Block unknown WL_CORP MACs (DISABLED - enable with MAC policy)"
        elif "WL_CORP_MACS" in (out.get("description") or ""):
            if "(DISABLED" not in out["description"]:
                out["description"] = out["description"] + " (DISABLED - future MAC policy)"
    res = api("POST", f"/api/firewall/filter/setRule/{uuid}", key, secret, {"rule": out})
    print(f"SET enabled={enabled} {label}: {res}")


def open_rule_exists(rows, description):
    for r in rows:
        if (r.get("description") or r.get("descr")) == description and str(
            r.get("enabled")
        ) in ("1", "true", "True"):
            return True
    return False


def main():
    key, secret = load_creds()

    # 1) Disable MAC allow + block (keep for future)
    for uuid, label in MAC_RULES:
        set_enabled(key, secret, uuid, 0, label)

    # 2) Ensure open WL_CORP access exists
    q = urllib.parse.urlencode({"current": 1, "rowCount": 200, "searchPhrase": ""})
    page = api("GET", f"/api/firewall/filter/searchRule?{q}", key, secret)
    rows = page.get("rows") or []

    # Try get CORP category uuid
    cats = api(
        "GET",
        "/api/firewall/category/searchItem?"
        + urllib.parse.urlencode({"current": 1, "rowCount": 50, "searchPhrase": ""}),
        key,
        secret,
    )
    corp = ""
    for c in cats.get("rows") or []:
        if c.get("name") == "CORP":
            corp = c["uuid"]
            break

    for rule in OPEN_RULES:
        desc = rule["description"]
        # If a disabled leftover exists with same desc, re-enable instead
        existing = None
        for r in rows:
            if (r.get("description") or r.get("descr")) == desc:
                existing = r.get("uuid")
                break
        if existing and "-" in str(existing):
            set_enabled(key, secret, existing, 1, f"re-enable open {desc}")
            continue
        if open_rule_exists(rows, desc):
            print(f"ALREADY ON {desc}")
            continue
        payload = dict(rule)
        if corp:
            payload["categories"] = corp
        res = api(
            "POST",
            "/api/firewall/filter/addRule",
            key,
            secret,
            {"rule": payload},
        )
        print(f"ADD {desc}: {res}")

    apply = api("POST", "/api/firewall/filter/apply", key, secret, {})
    print(f"APPLY: {apply}")

    page = api("GET", f"/api/firewall/filter/searchRule?{q}", key, secret)
    print("\n=== opt3 / MAC related ===")
    for r in page.get("rows") or []:
        desc = r.get("description") or r.get("descr") or ""
        iface = str(r.get("interface") or "")
        if "opt3" in iface or "WL_CORP" in desc or "MAC" in desc:
            if "-" not in str(r.get("uuid", "")):
                continue
            print(
                f"  en={r.get('enabled')} {r.get('action')} src={r.get('source_net')} "
                f"dst={r.get('destination_net')} | {desc}"
            )


if __name__ == "__main__":
    main()
