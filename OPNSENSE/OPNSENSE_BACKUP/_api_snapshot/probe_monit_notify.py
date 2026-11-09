#!/usr/bin/env python3
"""Probe live Monit / notifications / gateway APIs on PEAK-CORP-FW."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
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
        "/api/monit/settings/get",
        "/api/monit/status/get/xml",
        "/api/monit/service/status",
        "/api/core/firmware/info",
        "/api/routes/gateway/status",
        "/api/routing/settings/get",
        "/api/core/system/status",
    ]
    for path in paths:
        safe = "probe_" + path.strip("/").replace("/", "_") + ".json"
        try:
            data = api("GET", path, key, secret)
            OUTDIR.joinpath(safe).write_text(json.dumps(data, indent=2)[:300000], encoding="utf-8")
            keys = list(data.keys())[:25] if isinstance(data, dict) else type(data).__name__
            print(f"OK {path} -> {safe} keys={keys}")
        except Exception as e:
            print(f"FAIL {path}: {e}")


if __name__ == "__main__":
    main()
