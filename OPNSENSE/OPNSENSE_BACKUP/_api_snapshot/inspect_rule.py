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
uuid = "a8645db6-7a3e-4de6-a2d7-be6f6c291693"
req = urllib.request.Request(
    f"{BASE}/api/firewall/filter/getRule/{uuid}",
    headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
)
with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
    data = json.loads(r.read().decode())
Path(__file__).with_name("getRule_admin_block.json").write_text(
    json.dumps(data, indent=2), encoding="utf-8"
)
rule = data["rule"]
for k in [
    "interface",
    "action",
    "protocol",
    "categories",
    "gateway",
    "sched",
    "direction",
    "ipprotocol",
    "statetype",
    "destination_port",
    "source_net",
    "destination_net",
    "enabled",
    "log",
    "quick",
]:
    print(k, "=", json.dumps(rule.get(k))[:400])
