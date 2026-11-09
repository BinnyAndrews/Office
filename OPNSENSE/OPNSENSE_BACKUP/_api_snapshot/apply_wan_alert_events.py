#!/usr/bin/env python3
"""Limit Monit alert events to WAN-relevant ones; verify thresholds + status."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
OUTDIR = Path(__file__).resolve().parent
CTX = ssl._create_unverified_context()

ALERT_UUID = "6ffffdba-4c51-4e6d-86c8-f5a4f720703c"
RECIPIENT = "binny.andrews@peakenergy.asia"
MAIL_FORMAT = f"From: {RECIPIENT}\nSubject: PEAK-CORP-FW $SERVICE — $EVENT\n"
# status=gateway_alert, link=physical NIC, connection/icmp/timeout=reachability
WAN_EVENTS = "status,link,connection,icmp,timeout"


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
            return e.code, {"raw": raw[:500]}


def main():
    key, secret = load_creds()
    st, res = api(
        "POST",
        f"/api/monit/settings/setAlert/{ALERT_UUID}",
        key,
        secret,
        {
            "alert": {
                "enabled": "1",
                "recipient": RECIPIENT,
                "noton": "0",
                "events": WAN_EVENTS,
                "format": MAIL_FORMAT,
                "reminder": "60",
                "description": "WAN loss/drop/link alerts to Binny",
            }
        },
    )
    print("setAlert events:", st, res)
    st, res = api("POST", "/api/monit/service/reconfigure", key, secret, {})
    print("reconfigure:", st, res)

    st, alerts = api("GET", "/api/monit/settings/searchAlert", key, secret)
    st, monit = api("GET", "/api/monit/settings/get", key, secret)
    st, gwa = api("GET", "/api/routing/settings/getGateway/661fa084-7e66-4687-a09b-7b3aa650c307", key, secret)
    st, gwj = api("GET", "/api/routing/settings/getGateway/f7e80d15-4e8d-4982-a114-7e87de9aa1cc", key, secret)
    st, status = api("GET", "/api/monit/service/status", key, secret)
    st, mstat = api("GET", "/api/monit/status/get/xml", key, secret)

    def gw_fields(g):
        item = g.get("gateway_item") or {}
        return {
            "name": item.get("name"),
            "latencylow": item.get("latencylow"),
            "latencyhigh": item.get("latencyhigh"),
            "losslow": item.get("losslow"),
            "losshigh": item.get("losshigh"),
            "interval": item.get("interval"),
            "monitor": item.get("monitor"),
        }

    summary = {
        "alert": (alerts.get("rows") or [None])[0],
        "smtp": {
            "mailserver": monit.get("monit", {}).get("general", {}).get("mailserver"),
            "port": monit.get("monit", {}).get("general", {}).get("port"),
            "username": monit.get("monit", {}).get("general", {}).get("username"),
            "ssl": monit.get("monit", {}).get("general", {}).get("ssl"),
            "interval": monit.get("monit", {}).get("general", {}).get("interval"),
            "password_present": bool(monit.get("monit", {}).get("general", {}).get("password")),
        },
        "WAN_AIRTEL": gw_fields(gwa),
        "WAN_JIO": gw_fields(gwj),
        "monit_service_status": status,
        "monit_xml_status_snippet": (mstat.get("status") or "")[:2000],
    }
    OUTDIR.joinpath("wan_email_alerts_verify.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2)[:4000])


if __name__ == "__main__":
    main()
