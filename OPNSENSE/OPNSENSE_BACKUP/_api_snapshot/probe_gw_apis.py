#!/usr/bin/env python3
"""Find APIs that can update gateway groups / Monit mail."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
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
        "/api/routing/settings/searchGatewayGroup",
        "/api/routing/settings/getGatewayGroup/e67849b4-9bbe-427d-aeb1-31e34a2351b9",
        "/api/routing/settings/get",
        "/api/routes/gateway/status",
        "/api/monit/settings/getService/",
    ]:
        try:
            data = api("GET", path, key, secret)
            print("OK", path, list(data.keys())[:10] if isinstance(data, dict) else type(data))
            if "GatewayGroup" in path or "gateway_group" in json.dumps(data)[:2000].lower() or "WAN_LB" in json.dumps(data):
                Path(__file__).resolve().parent.joinpath(
                    "probe_" + path.strip("/").replace("/", "_") + ".json"
                ).write_text(json.dumps(data, indent=2)[:100000], encoding="utf-8")
        except Exception as e:
            print("FAIL", path, e)

    # Empty getService shows defaults/schema
    blank = api("GET", "/api/monit/settings/getService/", key, secret)
    Path(__file__).resolve().parent.joinpath("probe_monit_getService_blank.json").write_text(
        json.dumps(blank, indent=2), encoding="utf-8"
    )
    print("blank service type keys:", list(blank.get("service", {}).get("type", {}).keys()))
    print("blank interface keys:", list(blank.get("service", {}).get("interface", {}).keys())[:20])


if __name__ == "__main__":
    main()
