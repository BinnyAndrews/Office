#!/usr/bin/env python3
import base64
import json
import ssl
import time
import urllib.error
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


def status():
    req = urllib.request.Request(
        BASE + "/api/core/firmware/status",
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, context=CTX, timeout=20) as r:
        return json.loads(r.read().decode())


for i in range(36):
    try:
        st = status()
        ver = st.get("product", {}).get("product_version")
        print(i, st.get("status"), ver, (st.get("status_msg") or "")[:120], flush=True)
        if ver and str(ver).startswith("26.7.5"):
            print("DONE", ver)
            break
    except Exception as e:
        print(i, "WAIT", type(e).__name__, str(e)[:100], flush=True)
    time.sleep(15)
