#!/usr/bin/env python3
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


def api(path, key, secret):
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    req = urllib.request.Request(
        BASE + path, headers={"Authorization": f"Basic {token}", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
        return json.loads(resp.read().decode())


def main():
    key, secret = load_creds()
    alerts = api("/api/monit/settings/searchAlert", key, secret)
    services = api("/api/monit/settings/searchService", key, secret)
    monit = api("/api/monit/settings/get", key, secret)
    g = monit["monit"]["general"]
    for uuid in (
        "661fa084-7e66-4687-a09b-7b3aa650c307",
        "f7e80d15-4e8d-4982-a114-7e87de9aa1cc",
    ):
        gw = api(f"/api/routing/settings/getGateway/{uuid}", key, secret)["gateway_item"]
        print(
            gw["name"],
            "loss",
            gw.get("losslow"),
            gw.get("losshigh"),
            "lat",
            gw.get("latencylow"),
            gw.get("latencyhigh"),
        )
    print("ALERT", alerts["rows"][0])
    print(
        "SMTP",
        g.get("mailserver"),
        g.get("port"),
        g.get("username"),
        "ssl="+str(g.get("ssl")),
        "pw="+("yes" if g.get("password") else "NO"),
    )
    for r in services["rows"]:
        if r["name"] in {"gateway_alert", "WAN_AIRTEL_link", "WAN_JIO_link"} or "WAN" in (r.get("name") or ""):
            print("SVC", r["name"], "en="+r["enabled"], r.get("%tests"), r.get("interface"))


if __name__ == "__main__":
    main()
