#!/usr/bin/env python3
import base64
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(r"c:\DEV\OFFICE\OPNSENSE\OPNSENSE_BACKUP\PEAK-CORP-FW.peakenergy.asia_root_apikey.txt")
CTX = ssl._create_unverified_context()


def api(method, path, payload=None):
    key = secret = ""
    for line in CRED.read_text(encoding="utf-8").splitlines():
        if line.startswith("key="):
            key = line[4:]
        elif line.startswith("secret="):
            secret = line[7:]
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, context=CTX, timeout=120) as r:
        return json.loads(r.read().decode())


rows = api("POST", "/api/firewall/d_nat/searchRule", {}).get("rows", [])
print("Enabled DNAT (disabled=0):")
for r in rows:
    if str(r.get("disabled")) == "0":
        print(
            f"  {r.get('%interface')} :{r.get('destination.port')} -> {r.get('target')} | {r.get('description')}"
        )

print("\nPEAK-APP / 80 / 443 DNAT:")
for r in rows:
    p = str(r.get("destination.port") or "")
    d = str(r.get("description") or "")
    if p in ("80", "443") or "PEAK-APP" in d:
        print(
            f"  disabled={r.get('disabled')} {r.get('%interface')} :{p} -> {r.get('target')} | {d}"
        )

for r in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
    if "PEAK-APP" in str(r.get("description") or ""):
        print(
            f"\nFW PEAK-APP enabled={r.get('enabled')} {r.get('description')}"
        )
