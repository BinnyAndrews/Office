#!/usr/bin/env python3
import base64
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CTX = ssl._create_unverified_context()
creds = {}
for line in Path(__file__).resolve().parents[1].joinpath(
    "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
).read_text().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip()
token = base64.b64encode(f"{creds['key']}:{creds['secret']}".encode()).decode()

# Disabled open WL_CORP passes superseded by MAC rules
DELETE = [
    ("0ece8789-12d7-4651-8f87-ce2cb91a8095", "Allow WL_CORP to WIRED_CORP"),
    ("05a6e3db-16f6-47b4-af7a-596edbdc9fbd", "Allow WL_CORP to MGMT"),
    ("4e991f78-76e2-4986-a64f-984965cde410", "Allow WL_CORP to Internet via WAN_LB"),
]


def api(method, path, data=None):
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
        return json.loads(r.read().decode())


for uuid, desc in DELETE:
    res = api("POST", f"/api/firewall/filter/delRule/{uuid}", {})
    print(desc, res)

print("APPLY", api("POST", "/api/firewall/filter/apply", {}))
