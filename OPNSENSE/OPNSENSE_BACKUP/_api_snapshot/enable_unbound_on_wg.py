#!/usr/bin/env python3
"""Listen Unbound on WIREGUARD (opt6) so WG client DNS 10.80.200.1 works."""
from __future__ import annotations

import base64
import json
import ssl
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()


def load_creds() -> tuple[str, str]:
    key = secret = ""
    for line in CRED.read_text(encoding="utf-8").splitlines():
        if line.startswith("key="):
            key = line[4:]
        elif line.startswith("secret="):
            secret = line[7:]
    return key, secret


def api(method: str, path: str, payload=None):
    key, secret = load_creds()
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def selected_ifaces(ai) -> list[str]:
    if ai is None:
        return []
    if isinstance(ai, str):
        return [p for p in ai.split(",") if p]
    if isinstance(ai, dict):
        out = []
        for k, v in ai.items():
            if isinstance(v, dict) and str(v.get("selected")) in ("1", "True", "true"):
                out.append(k)
            elif v in (1, "1", True):
                out.append(k)
        return out
    return []


def main() -> int:
    g = api("GET", "/api/unbound/settings/get")
    general = (g.get("unbound") or g).get("general") or {}
    ai = general.get("active_interface")
    cur = selected_ifaces(ai)
    print("active_interface before:", cur if cur else ai)

    want = list(cur) if cur else ["lan", "opt2", "opt3", "opt4"]
    if "opt6" not in want:
        want.append("opt6")

    # Keep only scalar general fields we already have as simple values
    new_general = {}
    for k, v in general.items():
        if k == "active_interface":
            continue
        if isinstance(v, (str, int, float)) or v is None:
            new_general[k] = v
        elif isinstance(v, dict) and set(v.keys()) <= {"value", "selected"}:
            # skip select widgets
            continue
    new_general["active_interface"] = ",".join(want)

    payload = {"unbound": {"general": new_general}}
    print("setting active_interface:", new_general["active_interface"])
    print("set:", api("POST", "/api/unbound/settings/set", payload))
    print("reconfigure:", api("POST", "/api/unbound/service/reconfigure", {}))

    g2 = api("GET", "/api/unbound/settings/get")
    ai2 = ((g2.get("unbound") or g2).get("general") or {}).get("active_interface")
    print("active_interface after:", selected_ifaces(ai2) or ai2)

    # Keep public PeakPulse off (read-only verify)
    print("\nVERIFY public PeakPulse still disabled:")
    for r in api("POST", "/api/firewall/d_nat/searchRule", {}).get("rows", []):
        desc = str(r.get("description") or r.get("descr") or "")
        if "PEAK-APP" in desc:
            print(f"  DNAT disabled={r.get('disabled')} {desc}")
    for r in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if "PEAK-APP" in str(r.get("description") or ""):
            print(f"  filter enabled={r.get('enabled')} {r.get('description')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
