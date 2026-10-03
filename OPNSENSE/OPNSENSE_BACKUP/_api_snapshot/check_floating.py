#!/usr/bin/env python3
import base64
import json
import ssl
import urllib.parse
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


def api(path):
    req = urllib.request.Request(
        BASE + path,
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
        return json.loads(r.read().decode())


q = urllib.parse.urlencode({"current": 1, "rowCount": 200, "searchPhrase": ""})
rows = api(f"/api/firewall/filter/searchRule?{q}").get("rows") or []
print("Multi-interface / group rules (floating-style):")
for r in rows:
    iface = str(r.get("interface") or "")
    uuid = str(r.get("uuid") or "")
    if "-" not in uuid:
        continue
    # multi or group
    if "," in iface or iface.upper() == "WAN" or iface == "":
        print(
            f"  if={iface!r} action={r.get('action')} "
            f"src={r.get('source_net')} dst={r.get('destination_net')} "
            f"dport={r.get('destination_port')} | {r.get('description') or r.get('descr')}"
        )
