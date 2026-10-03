#!/usr/bin/env python3
import base64
import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()

creds = {}
for line in KEYFILE.read_text(encoding="utf-8").splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip()
token = base64.b64encode(f"{creds['key']}:{creds['secret']}".encode()).decode()


def api(method, path, data=None):
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
        return json.loads(resp.read().decode())


q = urllib.parse.urlencode({"current": 1, "rowCount": 200, "searchPhrase": ""})
page = api("GET", f"/api/firewall/filter/searchRule?{q}")
rows = page.get("rows") or []

pass_log = [r for r in rows if r.get("action") == "pass" and r.get("log") in (True, "1", 1)]
block_nolog = [
    r
    for r in rows
    if r.get("action") in ("block", "reject") and r.get("log") in (False, "0", 0, None)
]
block_log = [
    r for r in rows if r.get("action") in ("block", "reject") and r.get("log") in (True, "1", 1)
]
pass_nolog = [r for r in rows if r.get("action") == "pass" and r.get("log") in (False, "0", 0)]

print(f"total={len(rows)}")
print(f"pass log ON={len(pass_log)}  pass log OFF={len(pass_nolog)}")
print(f"block log ON={len(block_log)}  block log OFF={len(block_nolog)}")
print("--- pass still logging ---")
for r in pass_log:
    print(r.get("uuid"), r.get("description") or r.get("descr"))
print("--- block not logging ---")
for r in block_nolog:
    print(r.get("uuid"), r.get("description") or r.get("descr"))
