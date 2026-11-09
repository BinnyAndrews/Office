#!/usr/bin/env python3
"""Dump Monit alert/service schemas and search endpoints."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
OUTDIR = Path(__file__).resolve().parent
CTX = ssl._create_unverified_context()


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
    with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}


def main():
    key, secret = load_creds()
    paths = [
        "/api/monit/settings/searchAlert",
        "/api/monit/settings/searchService",
        "/api/monit/settings/searchTest",
        "/api/monit/settings/getAlert/6ffffdba-4c51-4e6d-86c8-f5a4f720703c",
        "/api/monit/settings/getService/3e9f49f1-a559-40c9-96e5-672d3d8055a9",
        "/api/core/menu/search",
    ]
    for path in paths:
        safe = "probe_" + path.strip("/").replace("/", "_").replace("-", "_") + ".json"
        try:
            data = api("GET", path, key, secret)
            OUTDIR.joinpath(safe).write_text(json.dumps(data, indent=2)[:200000], encoding="utf-8")
            print(f"OK {path}")
        except Exception as e:
            print(f"FAIL {path}: {e}")

    # Also probe possible notification endpoints
    for path in [
        "/api/core/notifications/get",
        "/api/core/settings/get",
        "/api/postfix/general/get",
        "/api/postfix/service/status",
        "/api/diagnostics/interface/getInterfaceNames",
        "/api/interfaces/overview/interfacesInfo",
    ]:
        safe = "probe_" + path.strip("/").replace("/", "_") + ".json"
        try:
            data = api("GET", path, key, secret)
            OUTDIR.joinpath(safe).write_text(json.dumps(data, indent=2)[:200000], encoding="utf-8")
            print(f"OK {path}")
        except Exception as e:
            print(f"FAIL {path}: {e}")


if __name__ == "__main__":
    main()
