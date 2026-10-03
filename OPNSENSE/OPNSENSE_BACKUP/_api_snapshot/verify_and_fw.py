#!/usr/bin/env python3
import base64
import json
import ssl
import time
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
CTX = ssl._create_unverified_context()
lines = Path(
    r"c:\DEV\OFFICE\OPNSENSE\OPNSENSE_BACKUP\PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
).read_text(encoding="utf-8").splitlines()
key = next(l[4:] for l in lines if l.startswith("key="))
secret = next(l[7:] for l in lines if l.startswith("secret="))
auth = base64.b64encode(f"{key}:{secret}".encode()).decode()


def api(method, path, payload=None):
    data = None
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, context=CTX, timeout=300) as r:
        return json.loads(r.read().decode() or "{}")


def main():
    rules = api("POST", "/api/firewall/filter/searchRule", {})
    print("=== WL / target rules ===")
    for row in rules.get("rows", []):
        d = row.get("description") or ""
        u = row.get("uuid")
        if "WL_CORP" in d or u in {
            "0ece8789-12d7-4651-8f87-ce2cb91a8095",
            "05a6e3db-16f6-47b4-af7a-596edbdc9fbd",
        }:
            print(
                f"seq={row.get('sequence')} log={row.get('log')} uuid={u} "
                f"dst={row.get('destination_net')} dnot={row.get('destination_not')} desc={d}"
            )

    # If getRule returns [], toggle log via search+clone is hard; report only.
    for u in (
        "0ece8789-12d7-4651-8f87-ce2cb91a8095",
        "05a6e3db-16f6-47b4-af7a-596edbdc9fbd",
    ):
        g = api("GET", f"/api/firewall/filter/getRule/{u}")
        print(f"getRule {u} -> {type(g).__name__} {g if g != [] else '[]'}")

    print("=== firmware poll ===")
    api("POST", "/api/core/firmware/check", {})
    status = None
    for i in range(40):
        st = api("GET", "/api/core/firmware/status")
        status = st.get("status")
        msg = (st.get("status_msg") or "")[:160]
        latest = st.get("product", {}).get("product_latest")
        ver = st.get("product", {}).get("product_version")
        print(f"{i}: status={status} ver={ver} latest={latest} msg={msg}")
        if status in ("update", "upgrade", "error") or (
            status == "none" and i > 2 and "requires to check" not in msg
        ):
            # 'none' with useful msg may mean up to date / or still settling
            if status in ("update", "upgrade", "error"):
                break
        if status == "ok" and latest:
            break
        time.sleep(3)

    st = api("GET", "/api/core/firmware/status")
    print("FINAL_FW", json.dumps({
        "status": st.get("status"),
        "status_msg": st.get("status_msg"),
        "version": st.get("product", {}).get("product_version"),
        "latest": st.get("product", {}).get("product_latest"),
    }))

    # Only trigger update if an update is available
    if st.get("status") in ("update", "upgrade"):
        print("Starting firmware update...")
        print(api("POST", "/api/core/firmware/update", {"upgrade": "0"}))
        print("Update kicked off; firewall may reboot.")
    else:
        print("No firmware update action taken automatically; status=", st.get("status"))


if __name__ == "__main__":
    main()
