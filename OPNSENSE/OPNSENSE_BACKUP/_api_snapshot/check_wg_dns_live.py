#!/usr/bin/env python3
"""Dump WG-related filter rules and Unbound listen state."""
from __future__ import annotations

import base64
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()
DNS_UUID = "f92750e0-04a2-4995-837b-e73cc4e8e336"


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
    with urllib.request.urlopen(req, context=CTX, timeout=120) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def sel(field):
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return ",".join(
            k
            for k, v in field.items()
            if isinstance(v, dict) and str(v.get("selected")) in ("1", "True", "true")
        )
    return str(field)


def main():
    print("=== opt6 / WG filter rules ===")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        iface = str(row.get("interface") or "")
        desc = str(row.get("description") or "")
        if "opt6" in iface.lower() or "wire" in iface.lower() or "WG" in desc:
            print(
                f"seq={row.get('sequence')} en={row.get('enabled')} "
                f"{row.get('action')} if={iface} proto={row.get('protocol')} "
                f"src={row.get('source_net')} dst={row.get('destination_net')} "
                f"dport={row.get('destination_port')} | {desc}"
            )

    ru = api("GET", f"/api/firewall/filter/getRule/{DNS_UUID}").get("rule") or {}
    print("\n=== DNS rule detail ===")
    for k in (
        "enabled",
        "action",
        "sequence",
        "interface",
        "protocol",
        "source_net",
        "destination_net",
        "destination_port",
        "quick",
        "direction",
    ):
        v = ru.get(k)
        print(f"  {k}={sel(v) if isinstance(v, dict) else v}")

    gen = ((api("GET", "/api/unbound/settings/get").get("unbound") or {}).get("general") or {})
    print("\n=== Unbound active_interface ===", sel(gen.get("active_interface")))

    # Recent firewall log lines mentioning DNS / 53 / 200.5
    try:
        log = api("POST", "/api/diagnostics/firewall/log", {"digest": ""})
        rows = log.get("rows") or log.get("response") or []
        if isinstance(rows, list):
            hits = [
                r
                for r in rows[-200:]
                if "53" in str(r) or "domain" in str(r).lower() or "200.5" in str(r) or "10.80.200" in str(r)
            ]
            print(f"\n=== firewall log hits ({len(hits)}) ===")
            for r in hits[-15:]:
                print(r)
        else:
            print("\nlog type", type(log), str(log)[:400])
    except Exception as e:
        print("log ERR", e)


if __name__ == "__main__":
    raise SystemExit(main())
