#!/usr/bin/env python3
"""Create 3 WireGuard peers for AMC PeakPulse access and write client .conf files."""
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
EXISTING_PEERS = [
    "7e8a2f64-eb29-4f5e-b93c-8a43bb33b0ba",  # admin
    "cde43c9a-5410-4b0c-820e-6f5e45a7c787",  # binny.andrews
]

USERS = [
    ("Jagadeshwar", "jagadeshwar", "10.80.200.4/32"),
    ("Venu Gopal Reddy", "venu.gopal.reddy", "10.80.200.5/32"),
    ("Poovarasu", "poovarasu", "10.80.200.6/32"),
]


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
    print("enable general:", api("POST", "/api/wireguard/general/set", {"general": {"enabled": "1"}}))

    created = []
    for display, slug, tunnel in USERS:
        # skip if already present
        existing = api("GET", "/api/wireguard/client/searchClient").get("rows", [])
        match = next((r for r in existing if r.get("name") == slug), None)
        if match:
            print(f"skip existing {slug} uuid={match['uuid']}")
            # still ensure conf exists if keys unknown — regenerate only if no conf
            conf_path = OUT / f"{slug}.conf"
            if not conf_path.exists():
                print(f"WARNING: {conf_path} missing; peer exists but private key unknown — recreate manually")
            created.append((display, slug, tunnel, match["uuid"], None, match.get("pubkey")))
            continue

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
        uuid = res.get("uuid")
        if not uuid:
            raise SystemExit(f"failed to create {slug}: {res}")

        conf = f"""[Interface]
# PEAK-WG — {display} ({tunnel.split('/')[0]})
PrivateKey = {priv}
Address = {tunnel}
DNS = 10.80.100.1

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
        created.append((display, slug, tunnel, uuid, priv, pub))

    # Attach all peer UUIDs to PEAK-WG
    live = api("GET", "/api/wireguard/client/searchClient").get("rows", [])
    want_names = {"binny.andrews", "admin", "jagadeshwar", "venu.gopal.reddy", "poovarasu"}
    peer_uuids = [r["uuid"] for r in live if r.get("name") in want_names]
    peer_str = ",".join(peer_uuids)
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
                "peers": peer_str,
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
        print(
            f"  {row['name']:20} {row['tunneladdress']:18} "
            f"server={row.get('%servers')} uuid={row['uuid']}"
        )
    print("general:", api("GET", "/api/wireguard/general/get"))
    show = api("GET", "/api/wireguard/service/show")
    print("service show keys:", list(show.keys()) if isinstance(show, dict) else type(show))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
