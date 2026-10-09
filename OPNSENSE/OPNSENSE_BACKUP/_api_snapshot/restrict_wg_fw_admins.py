#!/usr/bin/env python3
"""Only binny.andrews + admin may reach firewall GUI/SSH over WireGuard.

AMC peers stay on 10.80.200.0/28 for CORP_INTERNAL (PeakPulse) only.
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
LOG: list[str] = []

WG_SELF_UUID = "aadf170f-d2a7-4de0-8f37-bc85fd571ec7"
WG_CORP_UUID = "855bf1aa-21de-463e-8bf9-fbc2542abceb"
ALIAS_NAME = "WG_FW_ADMINS"
ALIAS_CONTENT = "10.80.200.2/32\n10.80.200.3/32"  # binny.andrews, admin


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
    key, secret = load_creds()
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} HTTP {e.code}: {err[:800]}") from e


def selected_keys(node: dict) -> list[str]:
    out = []
    for k, v in node.items():
        if isinstance(v, dict) and "selected" in v and v.get("selected") in (1, "1", True):
            out.append(k)
    return out


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


def ensure_alias() -> str:
    rows = api("POST", "/api/firewall/alias/searchItem", {}).get("rows", [])
    existing = next((r for r in rows if r.get("name") == ALIAS_NAME), None)
    if existing:
        uuid = existing["uuid"]
        form = flatten(api("GET", f"/api/firewall/alias/getItem/{uuid}")["alias"])
        form["content"] = ALIAS_CONTENT
        form["description"] = "WireGuard peers allowed to firewall GUI/SSH (binny + admin)"
        form["type"] = "network"
        for k in list(form.keys()):
            if k.startswith("in_") or k.startswith("out_") or k in (
                "current_items",
                "last_updated",
                "eval_nomatch",
                "eval_match",
            ):
                form.pop(k, None)
        res = api("POST", f"/api/firewall/alias/setItem/{uuid}", {"alias": form})
        log(f"alias update {ALIAS_NAME} {uuid}: {res}")
        return uuid

    form = flatten(api("GET", "/api/firewall/alias/getItem")["alias"])
    form.update(
        {
            "enabled": "1",
            "name": ALIAS_NAME,
            "type": "network",
            "content": ALIAS_CONTENT,
            "description": "WireGuard peers allowed to firewall GUI/SSH (binny + admin)",
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
    log(f"alias add {ALIAS_NAME}: {res}")
    uuid = res.get("uuid")
    if not uuid:
        raise SystemExit(f"failed to create alias: {res}")
    return uuid


def set_rule(uuid: str, **updates):
    rule = flatten(api("GET", f"/api/firewall/filter/getRule/{uuid}")["rule"])
    if isinstance(rule.get("audit"), dict):
        rule.pop("audit", None)
    rule.update(updates)
    return api("POST", f"/api/firewall/filter/setRule/{uuid}", {"rule": rule})


def main() -> int:
    ensure_alias()

    # Firewall GUI/SSH: only WG_FW_ADMINS, ports 22+4444
    res = set_rule(
        WG_SELF_UUID,
        source_net=ALIAS_NAME,
        destination_net="(self)",
        destination_port="ADMIN_PORTS",
        protocol="tcp",
        description="WG FW admins only to firewall (GUI/SSH)",
    )
    log(f"WG self rule: {res}")

    # CORP access stays full /28 (PeakPulse for AMC peers)
    res = set_rule(
        WG_CORP_UUID,
        source_net="10.80.200.0/28",
        destination_net="CORP_INTERNAL",
        description="WG peers to CORP_INTERNAL (no guest; no FW)",
    )
    log(f"WG CORP rule: {res}")

    for path in (
        "/api/firewall/alias/reconfigure",
        "/api/firewall/filter/apply",
    ):
        try:
            log(f"apply {path}: {api('POST', path, {})}")
        except Exception as e:
            log(f"apply {path} FAIL: {e}")

    log("\nVERIFY:")
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") == ALIAS_NAME:
            log(f"  alias {row['name']} content={row.get('content')!r}")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if row.get("uuid") in (WG_SELF_UUID, WG_CORP_UUID):
            log(
                f"  {row.get('uuid')} enabled={row.get('enabled')} "
                f"src={row.get('source_net')} dst={row.get('destination_net')} "
                f"dport={row.get('destination_port')} proto={row.get('protocol')} "
                f"| {row.get('description')}"
            )

    out = Path(__file__).with_name("restrict_wg_fw_admins_log.txt")
    out.write_text("\n".join(LOG), encoding="utf-8")
    log(f"LOG={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
