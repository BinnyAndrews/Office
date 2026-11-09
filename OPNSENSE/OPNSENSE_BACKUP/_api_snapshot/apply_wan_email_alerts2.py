#!/usr/bin/env python3
"""Retry Monit alert/service updates with simpler payload shapes."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()

ALERT_UUID = "6ffffdba-4c51-4e6d-86c8-f5a4f720703c"
GATEWAY_ALERT_UUID = "3e9f49f1-a559-40c9-96e5-672d3d8055a9"
NETWORK_LINK_UUID = "b06d0cd5-1968-4725-a824-454f035a62ca"
NONZERO_UUID = "326e1735-fec1-410c-8e03-d61a9384d173"
CHANGED_UUID = "767cb94a-603b-4150-9380-c6b053bd9ede"
RECIPIENT = "binny.andrews@peakenergy.asia"
MAIL_FORMAT = f"From: {RECIPIENT}\nSubject: PEAK-CORP-FW $SERVICE — $EVENT\n"


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
    try:
        with urllib.request.urlopen(req, timeout=90, context=CTX) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:800]}


def try_payloads(label, method, path, key, secret, payloads):
    for i, payload in enumerate(payloads, 1):
        st, res = api(method, path, key, secret, payload)
        print(f"{label} try{i}: {st} {res}")
        if st == 200 and (res.get("result") == "saved" or res.get("uuid") or res.get("status") == "ok"):
            return True, res
        # also accept validations that aren't hard fail if result saved
        if st == 200 and res.get("result") != "failed":
            # some return result saved nested
            if "validations" not in res:
                return True, res
    return False, None


def main():
    key, secret = load_creds()

    # Alert — try several shapes
    alert_base = {
        "enabled": "1",
        "recipient": RECIPIENT,
        "noton": "0",
        "format": MAIL_FORMAT,
        "reminder": "60",
        "description": "WAN / system alerts to Binny",
    }
    alert_payloads = [
        {"alert": {**alert_base, "events": ""}},
        {"alert": {**alert_base}},
        {"alert": {**alert_base, "events": []}},
        {"alert": {**alert_base, "events": {"status": "1", "link": "1", "connection": "1", "icmp": "1"}}},
    ]
    ok, _ = try_payloads(
        "setAlert",
        "POST",
        f"/api/monit/settings/setAlert/{ALERT_UUID}",
        key,
        secret,
        alert_payloads,
    )
    if not ok:
        # try addAlert instead of editing default
        ok, res = try_payloads(
            "addAlert",
            "POST",
            "/api/monit/settings/addAlert",
            key,
            secret,
            [{"alert": {**alert_base, "events": ""}}],
        )
        print("addAlert fallback", ok, res)

    # gateway_alert setService
    gw_payloads = [
        {
            "service": {
                "enabled": "1",
                "name": "gateway_alert",
                "description": "Alert when WAN gateways in WAN_LB go down or recover",
                "type": "custom",
                "path": "/usr/local/opnsense/scripts/monit/gateway_alert.php",
                "timeout": "120",
                "starttimeout": "30",
                "tests": f"{NONZERO_UUID},{CHANGED_UUID}",
                "polltime": "* * * * *",
            }
        },
        {
            "service": {
                "enabled": "1",
                "name": "gateway_alert",
                "description": "Alert when WAN gateways in WAN_LB go down or recover",
                "type": "custom",
                "path": "/usr/local/opnsense/scripts/monit/gateway_alert.php",
                "timeout": "120",
                "starttimeout": "30",
                "tests": NONZERO_UUID,
            }
        },
    ]
    try_payloads(
        "setGatewayAlert",
        "POST",
        f"/api/monit/settings/setService/{GATEWAY_ALERT_UUID}",
        key,
        secret,
        gw_payloads,
    )

    # Link services
    st, services = api("GET", "/api/monit/settings/searchService", key, secret)
    have = {r.get("name") for r in (services.get("rows") or [])}
    for name, iface in [("WAN_AIRTEL_link", "wan"), ("WAN_JIO_link", "opt1")]:
        if name in have:
            print("exists", name)
            continue
        payloads = [
            {
                "service": {
                    "enabled": "1",
                    "name": name,
                    "description": f"Physical link monitor ({iface})",
                    "type": "network",
                    "interface": iface,
                    "tests": NETWORK_LINK_UUID,
                    "timeout": "300",
                    "starttimeout": "30",
                    "polltime": "* * * * *",
                }
            },
            {
                "service": {
                    "enabled": "1",
                    "name": name,
                    "description": f"Physical link monitor ({iface})",
                    "type": "network",
                    "interface": iface,
                    "tests": [NETWORK_LINK_UUID],
                }
            },
        ]
        try_payloads("addService_" + name, "POST", "/api/monit/settings/addService", key, secret, payloads)

    st, res = api("POST", "/api/monit/service/reconfigure", key, secret, {})
    print("reconfigure", st, res)

    st, alerts = api("GET", "/api/monit/settings/searchAlert", key, secret)
    st, services = api("GET", "/api/monit/settings/searchService", key, secret)
    print("ALERTS:", json.dumps(alerts.get("rows"), indent=2))
    print(
        "SERVICES:",
        json.dumps(
            [
                {
                    "name": r.get("name"),
                    "enabled": r.get("enabled"),
                    "type": r.get("type"),
                    "interface": r.get("interface"),
                    "tests": r.get("%tests"),
                    "description": r.get("description"),
                }
                for r in (services.get("rows") or [])
            ],
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
