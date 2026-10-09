#!/usr/bin/env python3
"""Add WireGuard peer Sanoj James (10.80.200.7) to PEAK-WG and write client conf."""
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

DISPLAY = "Sanoj James"
SLUG = "sanoj.james"
TUNNEL = "10.80.200.7/32"

# All peers that must remain attached to PEAK-WG
WANT_NAMES = {
    "binny.andrews",
    "admin",
    "jagadeshwar",
    "venu.gopal.reddy",
    "poovarasu",
    "sanoj.james",
}


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


def main() -> int:
    existing = api("GET", "/api/wireguard/client/searchClient").get("rows", [])
    match = next((r for r in existing if r.get("name") == SLUG), None)

    if match:
        print(f"peer already exists: {SLUG} uuid={match['uuid']} tunnel={match.get('tunneladdress')}")
        if not (OUT / f"{SLUG}.conf").exists():
            print("WARNING: conf missing; private key unknown — delete peer in GUI and re-run to regenerate")
            return 1
    else:
        kp = api("GET", "/api/wireguard/server/keyPair")
        priv, pub = kp["privkey"], kp["pubkey"]
        res = api(
            "POST",
            "/api/wireguard/client/addClient",
            {
                "client": {
                    "enabled": "1",
                    "name": SLUG,
                    "pubkey": pub,
                    "psk": "",
                    "tunneladdress": TUNNEL,
                    "serveraddress": "",
                    "serverport": "",
                    "servers": SERVER_UUID,
                    "keepalive": "25",
                }
            },
        )
        print(f"add {SLUG}:", res)
        uuid = res.get("uuid")
        if not uuid:
            raise SystemExit(f"failed to create {SLUG}: {res}")

        conf = f"""[Interface]
# PEAK-WG — {DISPLAY} ({TUNNEL.split('/')[0]})
PrivateKey = {priv}
Address = {TUNNEL}
DNS = 10.80.100.1

[Peer]
PublicKey = {SERVER_PUB}
Endpoint = {ENDPOINT}
# Alternate if Airtel is down: 47.247.169.94:51820
AllowedIPs = 10.80.0.0/16
PersistentKeepalive = 25
"""
        (OUT / f"{SLUG}.conf").write_text(conf, encoding="utf-8")
        (OUT / f"{SLUG}.public.key").write_text(pub + "\n", encoding="utf-8")
        (OUT / f"{SLUG}.private.key").write_text(priv + "\n", encoding="utf-8")
        print(f"wrote {OUT / f'{SLUG}.conf'}")

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

    print("\nVERIFY peers:")
    for row in api("GET", "/api/wireguard/client/searchClient").get("rows", []):
        if row.get("name") in WANT_NAMES:
            print(
                f"  {row['name']:20} {row['tunneladdress']:18} "
                f"server={row.get('%servers')} uuid={row['uuid']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
