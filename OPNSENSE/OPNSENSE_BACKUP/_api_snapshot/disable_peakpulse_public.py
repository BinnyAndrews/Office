#!/usr/bin/env python3
"""Disable public PeakPulse WAN access; keep rules; leave WireGuard enabled."""
from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(r"c:\DEV\OFFICE\OPNSENSE\OPNSENSE_BACKUP\PEAK-CORP-FW.peakenergy.asia_root_apikey.txt")
CTX = ssl._create_unverified_context()
LOG: list[str] = []

PEAK_DNAT_UUIDS = [
    "0165840e-c5c8-4476-b513-c4c8106b30f7",  # PEAK-APP-HTTP-Airtel
    "0bfd1f70-240b-4944-83fc-576370a76334",  # PEAK-APP-HTTPS-Airtel
    "d4406011-ee43-41bd-b351-1651cfba28aa",  # PEAK-APP-HTTP-Jio
    "2b545c2c-fe52-4d22-b5bf-148abd07e4d3",  # PEAK-APP-HTTPS-Jio
]
PEAK_WAN_ALLOW = "832c830f-abc7-4ca5-ac1a-68987b7144b3"


def log(msg: str) -> None:
    print(msg, flush=True)
    LOG.append(msg)


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
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} HTTP {e.code}: {err[:500]}") from e


def main() -> int:
    # Disable DNAT rules (0 = disabled in toggle with second arg on some builds;
    # prefer toggleRule/{uuid}/0 meaning set disabled)
    for uuid in PEAK_DNAT_UUIDS:
        row = None
        for r in api("POST", "/api/firewall/d_nat/searchRule", {}).get("rows", []):
            if r.get("uuid") == uuid:
                row = r
                break
        desc = (row or {}).get("description") or (row or {}).get("descr") or uuid
        disabled = (row or {}).get("disabled")
        log(f"DNAT before {uuid} disabled={disabled} {desc}")
        # toggleRule with /1 often means "set disabled=1" per OPNsense docs toggle_rule $uuid,$disabled
        res = api("POST", f"/api/firewall/d_nat/toggleRule/{uuid}/1", {})
        log(f"  toggle disable: {res}")

    # Disable WAN allow filter
    fr = None
    for r in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        if r.get("uuid") == PEAK_WAN_ALLOW:
            fr = r
            break
    log(
        f"FW before {PEAK_WAN_ALLOW} enabled={ (fr or {}).get('enabled') } "
        f"{(fr or {}).get('description')}"
    )
    # filter toggle: /0 = disable (enabled=0)
    res = api("POST", f"/api/firewall/filter/toggleRule/{PEAK_WAN_ALLOW}/0", {})
    log(f"  filter toggle off: {res}")

    # Apply
    for path in (
        "/api/firewall/filter/apply",
        "/api/firewall/d_nat/apply",  # may 404 on some builds
    ):
        try:
            log(f"apply {path}: {api('POST', path, {})}")
        except Exception as e:
            log(f"apply {path} skip/fail: {e}")

    # Verify
    log("\nVERIFY DNAT PEAK-APP:")
    for r in api("POST", "/api/firewall/d_nat/searchRule", {}).get("rows", []):
        desc = str(r.get("description") or r.get("descr") or "")
        if "PEAK-APP" in desc or r.get("uuid") in PEAK_DNAT_UUIDS:
            log(
                f"  {r.get('uuid')} disabled={r.get('disabled')} "
                f"if={r.get('%interface') or r.get('interface')} "
                f"port={r.get('destination.port') or r.get('destination_port')} {desc}"
            )

    log("\nVERIFY WAN allow / WG:")
    for r in api("POST", "/api/firewall/filter/searchRule", {}).get("rows", []):
        desc = str(r.get("description") or "")
        if r.get("uuid") == PEAK_WAN_ALLOW or "WireGuard" in desc or desc.startswith("WG "):
            log(
                f"  {r.get('uuid')} enabled={r.get('enabled')} "
                f"if={r.get('interface')} dport={r.get('destination_port')} {desc}"
            )

    log(f"WG general: {api('GET', '/api/wireguard/general/get')}")

    out = Path(__file__).with_name("disable_peakpulse_public_log.txt")
    out.write_text("\n".join(LOG), encoding="utf-8")
    log(f"LOG={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
