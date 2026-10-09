#!/usr/bin/env python3
"""Restore MGMT in CORP_INTERNAL with a minimal alias payload."""
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
CORP_CONTENT = "10.80.99.0/24\n10.80.100.0/24\n10.80.101.0/24"


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
    if not isinstance(field, dict):
        return str(field or "")
    sel = [k for k, v in field.items() if isinstance(v, dict) and v.get("selected") in (1, "1", True)]
    return sel[0] if len(sel) == 1 else ",".join(sel)


def main() -> int:
    rows = api("POST", "/api/firewall/alias/searchItem", {}).get("rows", [])
    corp = next((r for r in rows if r.get("name") == "CORP_INTERNAL"), None)
    print("before:", corp)
    if not corp:
        raise SystemExit("missing CORP_INTERNAL")
    uuid = corp["uuid"]
    raw = api("GET", f"/api/firewall/alias/getItem/{uuid}")["alias"]
    # Build minimal set payload from scalars + type select
    alias = {
        "enabled": raw.get("enabled", "1"),
        "name": "CORP_INTERNAL",
        "type": selected_keys(raw.get("type")) or "network",
        "proto": selected_keys(raw.get("proto")) if isinstance(raw.get("proto"), dict) else (raw.get("proto") or ""),
        "interface": selected_keys(raw.get("interface")) if isinstance(raw.get("interface"), dict) else "",
        "counters": raw.get("counters", "0"),
        "updatefreq": raw.get("updatefreq") or "",
        "content": CORP_CONTENT,
        "password": "",
        "username": "",
        "authtype": selected_keys(raw.get("authtype")) if isinstance(raw.get("authtype"), dict) else "",
        "categories": "",
        "expire": raw.get("expire") or "",
        "path_expression": raw.get("path_expression") or "",
        "description": "MGMT+WIRED+WL_CORP; FW GUI gated by WG self rules",
    }
    # omit empty optional selects that break set
    for k in ("proto", "interface", "authtype", "categories", "password", "username", "expire", "path_expression", "updatefreq"):
        if alias.get(k) in ("", None, []):
            # keep empty string for some; OPNsense often wants them present
            pass
    print("payload:", alias)
    print("set:", api("POST", f"/api/firewall/alias/setItem/{uuid}", {"alias": alias}))
    print("reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))
    print("filter apply:", api("POST", "/api/firewall/filter/apply", {}))

    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") == "CORP_INTERNAL":
            print("after:", row.get("content"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
