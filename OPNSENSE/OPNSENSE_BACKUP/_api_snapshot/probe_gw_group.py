#!/usr/bin/env python3
"""Inspect gateway groups and Monit set schemas."""

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
    for path in [
        "/api/routes/gateway/get",
        "/api/routing/settings/searchGateway",
        "/api/routes/gatewaygroup/searchItem",
        "/api/routes/gatewaygroup/get",
        "/api/routing/settings/getGateway/661fa084-7e66-4687-a09b-7b3aa650c307",
        "/api/monit/settings/getService/",
        "/api/monit/settings/getAlert/",
    ]:
        safe = "probe_" + path.strip("/").replace("/", "_") + ".json"
        try:
            data = api("GET", path, key, secret)
            OUTDIR.joinpath(safe).write_text(json.dumps(data, indent=2)[:250000], encoding="utf-8")
            print("OK", path)
        except Exception as e:
            print("FAIL", path, e)


if __name__ == "__main__":
    main()
