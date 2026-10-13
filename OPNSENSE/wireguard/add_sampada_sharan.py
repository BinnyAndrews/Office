#!/usr/bin/env python3
"""Add WireGuard peers Sampada (10.80.200.8) and Sharan (10.80.200.9) to PEAK-WG."""
from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CRED = Path(r"c:\DEV\OFFICE\OPNSENSE\OPNSENSE_BACKUP\PEAK-CORP-FW.peakenergy.asia_root_apikey.txt")
OUT = Path(r"c:\DEV\OFFICE\OPNSENSE\wireguard")
CTX = ssl._create_unverified_context()

SERVER_UUID = "f698e248-6917-4b8a-97cb-bd5a32c48ccb"
SERVER_PUB = "MCUPmFkyIS6C6nFn0ccrt6uNh7EHDJP9NDkqDueifxo="
SERVER_PRIV = "cMipoWXs325I7cE+6WXbJBhGKvVCUsGGMoFJPBxUf0w="
ENDPOINT = "125.19.224.18:51820"

USERS = [
    ("Sampada", "sampada", "10.80.200.8/32"),
    ("Sharan", "sharan", "10.80.200.9/32"),
]

WANT_NAMES = {
    "binny.andrews",
    "admin",
    "jagadeshwar",
    "venu.gopal.reddy",
    "poovarasu",
    "sanoj.james",
    "sampada",
    "sharan",
}

# AMC-style: CORP PeakPulse only, no RDP
WG_NO_RDP = "WG_NO_RDP"
WG_NO_RDP_CONTENT = (
    "10.80.200.5/32\n"  # venu
    "10.80.200.6/32\n"  # poovarasu
    "10.80.200.7/32\n"  # sanoj
    "10.80.200.8/32\n"  # sampada
    "10.80.200.9/32"  # sharan
)


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
        with urllib.request.urlopen(req, context=CTX, timeout=120) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} HTTP {e.code}: {err[:800]}") from e


def selected_keys(field) -> str:
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return ",".join(
            k
            for k, v in field.items()
            if isinstance(v, dict) and str(v.get("selected")) in ("1", "true", "True")
        )
    return str(field)


def ensure_peer(display: str, slug: str, tunnel: str) -> None:
    existing = api("GET", "/api/wireguard/client/searchClient").get("rows", [])
    match = next((r for r in existing if r.get("name") == slug), None)
    if match:
        print(f"peer already exists: {slug} uuid={match['uuid']} tunnel={match.get('tunneladdress')}")
        if not (OUT / f"{slug}.conf").exists():
            raise SystemExit(
                f"WARNING: {slug}.conf missing; private key unknown — delete peer in GUI and re-run"
            )
        return

    kp = api("GET", "/api/wireguard/server/keyPair")
    priv, pub = kp["privkey"], kp["pubkey"]
    res = api(
        "POST",
        "/api/wireguard/client/addClient",
        {
            "client": {
                "enabled": "1",
                "name": slug,
                "pubkey": pub,
                "psk": "",
                "tunneladdress": tunnel,
                "serveraddress": "",
                "serverport": "",
                "servers": SERVER_UUID,
                "keepalive": "25",
            }
        },
    )
    print(f"add {slug}:", res)
    if not res.get("uuid"):
        raise SystemExit(f"failed to create {slug}: {res}")

    conf = f"""[Interface]
# PEAK-WG — {display} ({tunnel.split('/')[0]})
PrivateKey = {priv}
Address = {tunnel}
DNS = 10.80.200.1

[Peer]
PublicKey = {SERVER_PUB}
Endpoint = {ENDPOINT}
# Alternate if Airtel is down: 47.247.169.94:51820
AllowedIPs = 10.80.0.0/16
PersistentKeepalive = 25
"""
    (OUT / f"{slug}.conf").write_text(conf, encoding="utf-8")
    (OUT / f"{slug}.public.key").write_text(pub + "\n", encoding="utf-8")
    (OUT / f"{slug}.private.key").write_text(priv + "\n", encoding="utf-8")
    print(f"wrote {OUT / f'{slug}.conf'}")


def attach_peers() -> None:
    live = api("GET", "/api/wireguard/client/searchClient").get("rows", [])
    peer_uuids = [r["uuid"] for r in live if r.get("name") in WANT_NAMES]
    missing = WANT_NAMES - {r.get("name") for r in live}
    if missing:
        raise SystemExit(f"missing peers on firewall: {sorted(missing)}")

    set_res = api(
        "POST",
        f"/api/wireguard/server/setServer/{SERVER_UUID}",
        {
            "server": {
                "enabled": "1",
                "name": "PEAK-WG",
                "pubkey": SERVER_PUB,
                "privkey": SERVER_PRIV,
                "port": "51820",
                "mtu": "",
                "dns": "",
                "tunneladdress": "10.80.200.1/28",
                "disableroutes": "1",
                "gateway": "",
                "carp_depend_on": "",
                "peers": ",".join(peer_uuids),
                "debug": "0",
                "endpoint": "",
                "peer_dns": "",
            }
        },
    )
    print("setServer:", set_res)
    print("reconfigure:", api("POST", "/api/wireguard/service/reconfigure", {}))


def update_no_rdp_alias() -> None:
    rows = api("POST", "/api/firewall/alias/searchItem", {}).get("rows", [])
    existing = next((r for r in rows if r.get("name") == WG_NO_RDP), None)
    if not existing:
        print(f"WARNING: alias {WG_NO_RDP} not found — skip RDP block update")
        return
    uuid = existing["uuid"]
    raw = api("GET", f"/api/firewall/alias/getItem/{uuid}")["alias"]
    payload = {
        "alias": {
            "enabled": "1",
            "name": WG_NO_RDP,
            "type": selected_keys(raw.get("type")) or "network",
            "proto": "",
            "interface": "",
            "counters": raw.get("counters", "0"),
            "updatefreq": "",
            "content": WG_NO_RDP_CONTENT,
            "password": "",
            "username": "",
            "authtype": "",
            "path": "",
            "description": "AMC WG peers without RDP (venu/poovarasu/sanoj/sampada/sharan)",
        }
    }
    print("set WG_NO_RDP:", api("POST", f"/api/firewall/alias/setItem/{uuid}", payload))
    print("alias reconfigure:", api("POST", "/api/firewall/alias/reconfigure", {}))


def main() -> int:
    for display, slug, tunnel in USERS:
        ensure_peer(display, slug, tunnel)
    attach_peers()
    update_no_rdp_alias()

    print("\nVERIFY peers:")
    for row in api("GET", "/api/wireguard/client/searchClient").get("rows", []):
        if row.get("name") in WANT_NAMES:
            print(
                f"  {row['name']:20} {row['tunneladdress']:18} "
                f"server={row.get('%servers')} uuid={row['uuid']}"
            )
    for row in api("POST", "/api/firewall/alias/searchItem", {}).get("rows", []):
        if row.get("name") == WG_NO_RDP:
            print(f"\n{WG_NO_RDP}={row.get('content')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
