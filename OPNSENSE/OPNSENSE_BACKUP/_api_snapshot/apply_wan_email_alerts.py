#!/usr/bin/env python3
"""Enable WAN loss/drop/link email alerts on PEAK-CORP-FW via Monit.

Recipient: binny.andrews@peakenergy.asia
SMTP: Microsoft 365 (smtp.office365.com:587) — password must be set separately
      unless SMTP_PASSWORD env var is provided when running this script.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
OUTDIR = Path(__file__).resolve().parent
CTX = ssl._create_unverified_context()

ALERT_UUID = "6ffffdba-4c51-4e6d-86c8-f5a4f720703c"
GATEWAY_ALERT_UUID = "3e9f49f1-a559-40c9-96e5-672d3d8055a9"
NETWORK_LINK_UUID = "b06d0cd5-1968-4725-a824-454f035a62ca"
NONZERO_UUID = "326e1735-fec1-410c-8e03-d61a9384d173"
CHANGED_UUID = "767cb94a-603b-4150-9380-c6b053bd9ede"

GW_AIRTEL = "661fa084-7e66-4687-a09b-7b3aa650c307"
GW_JIO = "f7e80d15-4e8d-4982-a114-7e87de9aa1cc"

RECIPIENT = "binny.andrews@peakenergy.asia"
MAIL_FORMAT = (
    f"From: {RECIPIENT}\n"
    "Subject: PEAK-CORP-FW $SERVICE — $EVENT\n"
)


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


def log(msg: str):
    print(msg)


def selected_map(options: dict, keep: set[str] | str | None) -> dict:
    """Build OPNsense multi-select map with selected=1 for keep uuids/keys."""
    if keep is None:
        keep_set: set[str] = set()
    elif isinstance(keep, str):
        keep_set = {keep} if keep else set()
    else:
        keep_set = set(keep)
    out = {}
    for k in options:
        out[k] = 1 if k in keep_set else 0
    return out


def main():
    key, secret = load_creds()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()

    # --- 1) Monit general: SMTP toward M365 + faster poll ---
    st, cur = api("GET", "/api/monit/settings/get", key, secret)
    general = cur["monit"]["general"]
    general_payload = {
        "enabled": "1",
        "interval": "60",
        "startdelay": "60",
        "mailserver": "smtp.office365.com",
        "port": "587",
        "username": RECIPIENT,
        "password": smtp_password if smtp_password else general.get("password") or "",
        "ssl": "1",
        "sslversion": "auto",
        "sslverify": "1",
        "logfile": general.get("logfile") or "",
        "statefile": general.get("statefile") or "",
        "eventqueuePath": general.get("eventqueuePath") or "",
        "eventqueueSlots": general.get("eventqueueSlots") or "",
        "httpdEnabled": general.get("httpdEnabled") or "0",
        "httpdUsername": general.get("httpdUsername") or "root",
        "httpdPassword": general.get("httpdPassword") or "",
        "httpdPort": general.get("httpdPort") or "2812",
        "httpdAllow": "",
        "mmonitUrl": general.get("mmonitUrl") or "",
        "mmonitTimeout": general.get("mmonitTimeout") or "5",
        "mmonitRegisterCredentials": general.get("mmonitRegisterCredentials") or "1",
    }
    st, res = api("POST", "/api/monit/settings/set", key, secret, {"monit": {"general": general_payload}})
    log(f"set general SMTP: {st} {res}")

    # --- 2) Enable alert recipient ---
    st, alert_cur = api("GET", f"/api/monit/settings/getAlert/{ALERT_UUID}", key, secret)
    events = selected_map(alert_cur["alert"]["events"], set())  # empty = all events
    alert_payload = {
        "enabled": "1",
        "recipient": RECIPIENT,
        "noton": "0",
        "events": events,
        "format": MAIL_FORMAT,
        "reminder": "60",
        "description": "WAN / system alerts to Binny",
    }
    st, res = api(
        "POST",
        f"/api/monit/settings/setAlert/{ALERT_UUID}",
        key,
        secret,
        {"alert": alert_payload},
    )
    log(f"setAlert: {st} {res}")

    # --- 3) Ensure gateway_alert uses NonZeroStatus + ChangedStatus, poll every minute ---
    st, gwsvc = api("GET", f"/api/monit/settings/getService/{GATEWAY_ALERT_UUID}", key, secret)
    svc = gwsvc["service"]
    tests = selected_map(svc["tests"], {NONZERO_UUID, CHANGED_UUID})
    depends = selected_map(svc["depends"], set())
    iface = selected_map(svc["interface"], {""})
    st, res = api(
        "POST",
        f"/api/monit/settings/setService/{GATEWAY_ALERT_UUID}",
        key,
        secret,
        {
            "service": {
                "enabled": "1",
                "name": "gateway_alert",
                "description": "Alert when WAN_AIRTEL / WAN_JIO (WAN_LB) go down or recover",
                "type": "custom",
                "pidfile": "",
                "match": "",
                "path": "/usr/local/opnsense/scripts/monit/gateway_alert.php",
                "timeout": "120",
                "starttimeout": "30",
                "address": "",
                "interface": iface,
                "start": "",
                "stop": "",
                "tests": tests,
                "depends": depends,
                "polltime": "* * * * *",
            }
        },
    )
    log(f"set gateway_alert: {st} {res}")

    # --- 4) Add physical WAN link monitors if missing ---
    st, services = api("GET", "/api/monit/settings/searchService", key, secret)
    have = {r.get("name") for r in (services.get("rows") or [])}
    for name, iface_key, descr in [
        ("WAN_AIRTEL_link", "wan", "Physical link down on Airtel WAN (re1)"),
        ("WAN_JIO_link", "opt1", "Physical link down on Jio WAN (re2)"),
    ]:
        if name in have:
            log(f"service exists: {name}")
            continue
        st, blank = api("GET", "/api/monit/settings/getService/", key, secret)
        tests = selected_map(blank["service"]["tests"], {NETWORK_LINK_UUID})
        depends = selected_map(blank["service"]["depends"], set())
        iface = selected_map(blank["service"]["interface"], {iface_key})
        payload = {
            "service": {
                "enabled": "1",
                "name": name,
                "description": descr,
                "type": "network",
                "pidfile": "",
                "match": "",
                "path": "",
                "timeout": "300",
                "starttimeout": "30",
                "address": "",
                "interface": iface,
                "start": "",
                "stop": "",
                "tests": tests,
                "depends": depends,
                "polltime": "* * * * *",
            }
        }
        st, res = api("POST", "/api/monit/settings/addService", key, secret, payload)
        log(f"addService {name}: {st} {res}")

    # --- 5) Gateway fluctuation thresholds (loss / latency → down) ---
    for uuid, label in [(GW_AIRTEL, "WAN_AIRTEL"), (GW_JIO, "WAN_JIO")]:
        st, g = api("GET", f"/api/routing/settings/getGateway/{uuid}", key, secret)
        item = g.get("gateway_item") or g.get("gateway") or {}
        # Flatten selected fields from get response
        payload = {
            "disabled": item.get("disabled", "0"),
            "name": item.get("name", label),
            "descr": item.get("descr", ""),
            "interface": next(
                (k for k, v in (item.get("interface") or {}).items() if v.get("selected")),
                "wan" if label == "WAN_AIRTEL" else "opt1",
            ),
            "ipprotocol": "inet",
            "gateway": item.get("gateway", ""),
            "defaultgw": item.get("defaultgw", "1"),
            "fargw": item.get("fargw", "0"),
            "monitor_disable": item.get("monitor_disable", "0"),
            "monitor_noroute": item.get("monitor_noroute", "0"),
            "monitor_killstates": item.get("monitor_killstates", "1"),
            "monitor_killstates_priority": item.get("monitor_killstates_priority", "0"),
            "monitor": item.get("monitor", ""),
            "force_down": item.get("force_down", "0"),
            "nosync": item.get("nosync", "0"),
            "priority": item.get("priority", "1"),
            "weight": item.get("weight", "1"),
            # Warn / down thresholds for fluctuation
            "latencylow": "200",
            "latencyhigh": "500",
            "losslow": "10",
            "losshigh": "20",
            "interval": item.get("interval") or "1",
            "time_period": item.get("time_period") or "",
            "loss_interval": item.get("loss_interval") or "",
            "data_length": item.get("data_length") or "",
        }
        st, res = api(
            "POST",
            f"/api/routing/settings/setGateway/{uuid}",
            key,
            secret,
            {"gateway_item": payload},
        )
        log(f"setGateway {label}: {st} {res}")

    st, res = api("POST", "/api/routing/settings/reconfigure", key, secret, {})
    log(f"routing reconfigure: {st} {res}")

    st, res = api("POST", "/api/monit/service/reconfigure", key, secret, {})
    log(f"monit reconfigure: {st} {res}")

    # --- Verify ---
    st, alerts = api("GET", "/api/monit/settings/searchAlert", key, secret)
    st, services = api("GET", "/api/monit/settings/searchService", key, secret)
    st, monit = api("GET", "/api/monit/settings/get", key, secret)
    st, gwstat = api("GET", "/api/routes/gateway/status", key, secret)
    summary = {
        "alerts": alerts.get("rows"),
        "services": [
            {
                "name": r.get("name"),
                "enabled": r.get("enabled"),
                "type": r.get("type"),
                "interface": r.get("interface"),
                "tests": r.get("%tests"),
            }
            for r in (services.get("rows") or [])
        ],
        "mailserver": monit.get("monit", {}).get("general", {}).get("mailserver"),
        "port": monit.get("monit", {}).get("general", {}).get("port"),
        "username": monit.get("monit", {}).get("general", {}).get("username"),
        "ssl": monit.get("monit", {}).get("general", {}).get("ssl"),
        "password_set": bool(
            (monit.get("monit", {}).get("general", {}).get("password") or "")
            or smtp_password
        ),
        "gateways": gwstat.get("items"),
    }
    OUTDIR.joinpath("wan_email_alerts_verify.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    log(json.dumps(summary, indent=2))
    if not summary["password_set"]:
        log(
            "\nNOTE: SMTP password is empty. "
            "Set an M365 SMTP AUTH / app password, then re-run with SMTP_PASSWORD=... "
            "or paste it in Services → Monit → General Settings."
        )


if __name__ == "__main__":
    main()
