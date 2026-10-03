#!/usr/bin/env python3
"""Apply PEAK-CORP-FW optimizations 2,3,4,5,6,8 via API. #9 partially done."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(r"c:\DEV\OFFICE\OPNSENSE\OPNSENSE_BACKUP\PEAK-CORP-FW.peakenergy.asia_root_apikey.txt")
CTX = ssl._create_unverified_context()
LOG: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(msg)


def load_creds() -> tuple[str, str]:
    key = secret = ""
    for line in CRED.read_text(encoding="utf-8").splitlines():
        if line.startswith("key="):
            key = line[4:]
        elif line.startswith("secret="):
            secret = line[7:]
    return key, secret


def api(method: str, path: str, payload=None):
    import base64

    key, secret = load_creds()
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    data = None
    headers = {
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if not body:
                return {}
            return json.loads(body)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} HTTP {e.code}: {err[:500]}") from e


def selected_keys(node: dict) -> list[str]:
    out = []
    for k, v in node.items():
        if isinstance(v, dict) and "selected" in v:
            if v.get("selected") in (1, "1", True):
                out.append(k)
    return out


def flatten(node):
    """Convert OPNsense get-* option trees into set-* scalars."""
    if not isinstance(node, dict):
        return node
    # selection map?
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


def get_rule(uuid: str) -> dict:
    return flatten(api("GET", f"/api/firewall/filter/getRule/{uuid}")["rule"])


def set_rule(uuid: str, **updates):
    rule = get_rule(uuid)
    rule.update(updates)
    # drop non-settable audit blob noise if present as nested leftover
    if isinstance(rule.get("audit"), dict):
        rule.pop("audit", None)
    res = api("POST", f"/api/firewall/filter/setRule/{uuid}", {"rule": rule})
    return res


def main() -> int:
    # --- 2 gateway interval ---
    try:
        gw = api("GET", "/api/routing/settings/get")
        flat = flatten(gw)
        for gid, item in flat["gateways"]["gateway_item"].items():
            item["interval"] = "5"
            log(f"2 set {item.get('name')} interval=5 iface={item.get('interface')} proto={item.get('ipprotocol')}")
        res = api("POST", "/api/routing/settings/set", flat)
        log(f"2 routing set: {res}")
    except Exception as e:
        log(f"2 FAIL {e}")

    # --- 6 expand LAN_RFC1918 ---
    try:
        raw = api("GET", "/api/firewall/alias/getItem/c11d528e-a563-4f9b-8a23-f168f13e44f7")
        alias = flatten(raw["alias"])
        alias["content"] = "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16"
        alias["description"] = "Private RFC1918 networks"
        # remove stats-only fields if present
        for k in list(alias.keys()):
            if k.startswith("in_") or k.startswith("out_") or k in (
                "current_items",
                "last_updated",
                "eval_nomatch",
                "eval_match",
            ):
                alias.pop(k, None)
        res = api(
            "POST",
            "/api/firewall/alias/setItem/c11d528e-a563-4f9b-8a23-f168f13e44f7",
            {"alias": alias},
        )
        log(f"6 LAN_RFC1918: {res}")
    except Exception as e:
        log(f"6 FAIL {e}")

    # --- 3 delete disabled MAC rules (if still present) ---
    for uuid in (
        "ec42364f-09b4-4133-bdd7-eb03dfd3a2f2",
        "8af6f814-5b8a-4f93-8db3-eb3f4248c1fc",
        "a30a91bf-3393-4e49-85f2-77143cde5311",
    ):
        try:
            res = api("POST", f"/api/firewall/filter/delRule/{uuid}", {})
            log(f"3 del {uuid}: {res}")
        except Exception as e:
            log(f"3 del {uuid}: {e}")

    # --- 4 MGMT / Guest internet invert ---
    try:
        res = set_rule(
            "abf92213-2f30-496f-af4a-f57fd51fae8b",
            destination_net="LAN_RFC1918",
            destination_not="1",
            description="MGMT to Internet via WAN_LB",
        )
        log(f"4 MGMT: {res}")
    except Exception as e:
        log(f"4 MGMT FAIL {e}")

    try:
        res = set_rule(
            "04d2ba2b-490f-4707-98a9-e317371ca83d",
            destination_net="LAN_RFC1918",
            destination_not="1",
            description="WL_GUEST to Internet (scheduled)",
        )
        log(f"4 Guest: {res}")
    except Exception as e:
        log(f"4 Guest FAIL {e}")

    # --- 5 reduce logging ---
    for uuid in (
        "8775d0bb-edc7-4736-b7a4-98752dd86206",
        "9cdb9a90-6e4e-440a-bc3a-14cedf3e9ab9",
        "a7c3e91f-2b84-4d6e-9f1a-5e8d0c4b7a12",
        "69c0df77-61f5-4e9b-8c87-2b6c7bd35dbc",
        "0ece8789-12d7-4651-8f87-ce2cb91a8095",
        "05a6e3db-16f6-47b4-af7a-596edbdc9fbd",
        "204b9f91-cdaa-4077-ac22-8c73c1f4db88",
        "49cd1036-18a0-406e-bebb-e71c7735e47b",
    ):
        try:
            res = set_rule(uuid, log="0")
            log(f"5 log-off {uuid}: {res}")
        except Exception as e:
            log(f"5 FAIL {uuid}: {e}")

    # --- 8 CORP_INTERNAL + WG rule ---
    try:
        aliases = api("POST", "/api/firewall/alias/searchItem", {})
        corp = next((r for r in aliases.get("rows", []) if r.get("name") == "CORP_INTERNAL"), None)
        if not corp:
            form = flatten(api("GET", "/api/firewall/alias/getItem")["alias"])
            form.update(
                {
                    "enabled": "1",
                    "name": "CORP_INTERNAL",
                    "type": "network",
                    "content": "10.80.99.0/24\n10.80.100.0/24\n10.80.101.0/24",
                    "description": "MGMT+WIRED+WL_CORP (no guest)",
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
                    "current_items",
                    "last_updated",
                    "eval_nomatch",
                    "eval_match",
                ):
                    form.pop(k, None)
            res = api("POST", "/api/firewall/alias/addItem", {"alias": form})
            log(f"8 add CORP_INTERNAL: {res}")
        else:
            log(f"8 CORP_INTERNAL exists {corp.get('uuid')}")

        res = set_rule(
            "855bf1aa-21de-463e-8bf9-fbc2542abceb",
            destination_net="CORP_INTERNAL",
            destination_not="0",
            description="WG admin to CORP_INTERNAL (no guest)",
        )
        log(f"8 WG: {res}")
    except Exception as e:
        log(f"8 FAIL {e}")

    # --- 9 dedupe unbound hosts (keep one each) ---
    try:
        hosts = api("POST", "/api/unbound/settings/searchHostOverride", {})
        seen = {}
        for row in hosts.get("rows", []):
            name = row.get("hostname")
            if name in ("peakpulse-dev", "app"):
                seen.setdefault(name, []).append(row)
        for name, rows in seen.items():
            # keep first, delete extras
            for extra in rows[1:]:
                res = api("POST", f"/api/unbound/settings/delHostOverride/{extra['uuid']}", {})
                log(f"9 dedupe del {name} {extra['uuid']}: {res}")
            keep = rows[0]
            res = api(
                "POST",
                f"/api/unbound/settings/setHostOverride/{keep['uuid']}",
                {
                    "host": {
                        "enabled": "1",
                        "hostname": name,
                        "domain": "peakenergy.asia",
                        "rr": "A",
                        "mxprio": "",
                        "mx": "",
                        "ttl": "",
                        "server": "10.80.100.54",
                        "txtdata": "",
                        "addptr": "1",
                        "description": "PeakPulse app host",
                    }
                },
            )
            log(f"9 ensure {name}: {res}")
    except Exception as e:
        log(f"9 FAIL {e}")

    # apply
    for path in (
        "/api/firewall/alias/reconfigure",
        "/api/firewall/filter/apply",
        "/api/routing/settings/reconfigure",
        "/api/unbound/service/reconfigure",
    ):
        try:
            res = api("POST", path, {})
            log(f"apply {path}: {res}")
        except Exception as e:
            log(f"apply {path} FAIL {e}")

    # verify
    gw = api("GET", "/api/routing/settings/get")
    for gid, item in gw["gateways"]["gateway_item"].items():
        log(f"VERIFY gw {item['name']} interval={item['interval']}")
    aliases = api("POST", "/api/firewall/alias/searchItem", {})
    for row in aliases.get("rows", []):
        if row.get("name") in ("LAN_RFC1918", "CORP_INTERNAL"):
            log(f"VERIFY alias {row['name']}={row.get('content')!r}")
    rules = api("POST", "/api/firewall/filter/searchRule", {})
    want = {
        "abf92213-2f30-496f-af4a-f57fd51fae8b": "MGMT",
        "04d2ba2b-490f-4707-98a9-e317371ca83d": "Guest",
        "855bf1aa-21de-463e-8bf9-fbc2542abceb": "WG",
        "0ece8789-12d7-4651-8f87-ce2cb91a8095": "WLtoWIRED",
    }
    for row in rules.get("rows", []):
        u = row.get("uuid")
        if u in want:
            log(
                f"VERIFY {want[u]} dst={row.get('destination_net')} dnot={row.get('destination_not')} log={row.get('log')} desc={row.get('description')}"
            )
    hosts = api("POST", "/api/unbound/settings/searchHostOverride", {})
    for row in hosts.get("rows", []):
        if row.get("hostname") in ("peakpulse-dev", "app"):
            log(f"VERIFY host {row['hostname']}->{row.get('server')}")

    out = Path(r"c:\DEV\OFFICE\OPNSENSE\OPNSENSE_BACKUP\_api_snapshot\apply_opts_py_log.txt")
    out.write_text("\n".join(LOG), encoding="utf-8")
    log(f"LOG={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
