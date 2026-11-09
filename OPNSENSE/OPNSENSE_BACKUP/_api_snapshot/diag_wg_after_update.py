#!/usr/bin/env python3
"""Diagnose WireGuard after OPNsense update."""
from __future__ import annotations

import base64
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()


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
    with urllib.request.urlopen(req, context=CTX, timeout=60) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def main():
    print("=== WG filter / WAN 51820 rules ===")
    for row in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        blob = json.dumps(row)
        iface = str(row.get("interface") or "")
        desc = str(row.get("description") or "")
        dport = str(row.get("destination_port") or "")
        if (
            "51820" in blob
            or "opt6" in iface.lower()
            or "wire" in desc.lower()
            or "wg" in desc.lower()
            or "WG" in desc
        ):
            print(
                "seq=%s en=%s %s if=%s proto=%s src=%s dst=%s dport=%s | %s"
                % (
                    row.get("sequence"),
                    row.get("enabled"),
                    row.get("action"),
                    iface,
                    row.get("protocol"),
                    row.get("source_net"),
                    row.get("destination_net"),
                    dport,
                    desc,
                )
            )

    print("\n=== interface assignment / overview (wg bits) ===")
    for path in (
        "/api/interfaces/overview/interfacesInfo",
        "/api/diagnostics/interface/getInterfaceNames",
        "/api/diagnostics/interface/getInterfaceConfig",
    ):
        print("---", path)
        try:
            r = api("GET", path)
            s = json.dumps(r, indent=2)
            for needle in ("wg0", "opt6", "WIREGUARD", "10.80.200"):
                idx = 0
                found = False
                while True:
                    i = s.find(needle, idx)
                    if i < 0:
                        break
                    found = True
                    print(s[max(0, i - 180) : i + 220])
                    print("---snip---")
                    idx = i + len(needle)
                    if idx > 5000:
                        break
                if found:
                    break
            else:
                print(s[:400])
        except Exception as e:
            print("ERR", e)

    print("\n=== netstat / sockets looking for 51820 ===")
    for path in (
        "/api/diagnostics/system/systemActivity",
        "/api/diagnostics/interface/getMemoryStatistics",
    ):
        pass

    # pf states / listeners via activity or shell-less endpoints
    try:
        # OPNsense often exposes netstat under diagnostics
        r = api("POST", "/api/diagnostics/interface/getInterfaceStatistics", {})
        print("stats keys sample ok", list((r.get("statistics") or {}).keys())[:5])
    except Exception as e:
        print(e)

    print("\n=== listen addresses / pf info via config dump of opt6 ===")
    try:
        # get assigned interfaces
        r = api("GET", "/api/interfaces/overview/export")
        Path(__file__).with_name("diag_if_export.json").write_text(
            json.dumps(r, indent=2), encoding="utf-8"
        )
        s = json.dumps(r)
        for needle in ("wg0", "opt6", "WIREGUARD", "10.80.200", "51820"):
            i = s.find(needle)
            if i >= 0:
                print(needle, "->", s[max(0, i - 120) : i + 200])
    except Exception as e:
        print("export ERR", e)

    print("\n=== recent firewall log UDP 51820 / wg ===")
    try:
        log = api("POST", "/api/diagnostics/firewall/log", {"digest": ""})
        rows = log.get("rows") or []
        hits = [
            r
            for r in rows[-400:]
            if "51820" in str(r) or "wg0" in str(r).lower() or "10.80.200" in str(r)
        ]
        print("hits", len(hits))
        for r in hits[-25:]:
            print(r)
    except Exception as e:
        print("log ERR", e)

    print("\n=== system version / uptime ===")
    for path in (
        "/api/diagnostics/system/systemTime",
        "/api/core/system/status",
        "/api/diagnostics/cpu_usage/getCPUType",
    ):
        try:
            print(path, json.dumps(api("GET", path))[:300])
        except Exception as e:
            print(path, "ERR", e)


if __name__ == "__main__":
    raise SystemExit(main())
