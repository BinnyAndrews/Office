#!/usr/bin/env python3
import base64
import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
OUT = Path(__file__).with_name("rules_live_summary.json")
CTX = ssl._create_unverified_context()

creds = {}
for line in KEYFILE.read_text(encoding="utf-8").splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip()
token = base64.b64encode(f"{creds['key']}:{creds['secret']}".encode()).decode()


def api(path: str):
    req = urllib.request.Request(
        BASE + path,
        headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
        return json.loads(resp.read().decode())


q = urllib.parse.urlencode({"current": 1, "rowCount": 200, "searchPhrase": ""})
page = api(f"/api/firewall/filter/searchRule?{q}")
full = api("/api/firewall/filter/get")
OUT.write_text(json.dumps({"search": page, "get": full}, indent=2), encoding="utf-8")
rows = page.get("rows") or []
print(f"total={len(rows)}")
for r in rows:
    seq = r.get("sequence", "?")
    action = r.get("action")
    iface = r.get("interface")
    direction = r.get("direction")
    proto = r.get("protocol")
    src = r.get("source_net")
    dst = r.get("destination_net")
    dport = r.get("destination_port")
    gw = r.get("gateway")
    desc = r.get("description") or r.get("descr")
    enabled = r.get("enabled")
    print(
        f"{seq:>6} | {enabled=!s:5} | {action!s:6} | if={iface} | dir={direction} | "
        f"proto={proto} | src={src} | dst={dst} | dport={dport} | gw={gw} | {desc}"
    )
