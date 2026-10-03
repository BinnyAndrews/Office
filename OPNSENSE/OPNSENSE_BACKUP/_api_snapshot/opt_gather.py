#!/usr/bin/env python3
import base64
import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
OUT = Path(__file__).with_name("opt_gather.json")
CTX = ssl._create_unverified_context()

creds = {}
for line in KEYFILE.read_text().splitlines():
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
    with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
        return json.loads(r.read().decode())


q = urllib.parse.urlencode({"current": 1, "rowCount": 300, "searchPhrase": ""})
rules = api("GET", f"/api/firewall/filter/searchRule?{q}")
aliases = api("GET", "/api/firewall/alias/searchItem?" + urllib.parse.urlencode(
    {"current": 1, "rowCount": 300, "searchPhrase": ""}
))
cats = api("GET", "/api/firewall/category/searchItem?" + urllib.parse.urlencode(
    {"current": 1, "rowCount": 100, "searchPhrase": ""}
))
groups = api("GET", "/api/firewall/group/searchItem?" + urllib.parse.urlencode(
    {"current": 1, "rowCount": 50, "searchPhrase": ""}
))
# try group get
try:
    group_get = api("GET", "/api/firewall/group/get")
except Exception as e:
    group_get = {"error": str(e)}

OUT.write_text(
    json.dumps(
        {
            "rules": rules,
            "aliases": aliases,
            "categories": cats,
            "groups_search": groups,
            "groups_get": group_get,
        },
        indent=2,
    ),
    encoding="utf-8",
)

print("RULES:")
for r in rules.get("rows") or []:
    print(
        f"  {r.get('uuid')} | en={r.get('enabled')} | {r.get('action')} | "
        f"if={r.get('interface')} | src={r.get('source_net')} | "
        f"dst={r.get('destination_net')} | dport={r.get('destination_port')} | "
        f"{r.get('description') or r.get('descr')}"
    )

print("\nALIASES (name):")
for a in aliases.get("rows") or []:
    name = a.get("name")
    print(f"  {name} | type={a.get('type')} | {a.get('description') or a.get('descr')}")

print("\nCATEGORIES:")
for c in cats.get("rows") or []:
    print(f"  {c.get('uuid')} | {c.get('name')}")

print("\nGROUPS:")
for g in groups.get("rows") or []:
    print(g)
