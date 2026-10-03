#!/usr/bin/env python3
"""Apply remaining PEAK-CORP-FW firewall optimizations via API."""

from __future__ import annotations

import base64
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()
LOG = []

# --- UUID map from live gather ---
UUID = {
    "mgmt_dns": "54a56996-fc5c-45e1-b7e2-e7cf7c5aa88b",
    "wl_corp_wired": "0ece8789-12d7-4651-8f87-ce2cb91a8095",
    "wl_corp_mgmt": "05a6e3db-16f6-47b4-af7a-596edbdc9fbd",
    "wl_corp_inet": "4e991f78-76e2-4986-a64f-984965cde410",
    "mac_inet": "ec42364f-09b4-4133-bdd7-eb03dfd3a2f2",
    "mac_wired": "8af6f814-5b8a-4f93-8db3-eb3f4248c1fc",
    "mac_mgmt": "a30a91bf-3393-4e49-85f2-77143cde5311",
    "mac_block": "4bd7e3ec-20e9-4c0c-8262-006f294131c8",
    "wg_wan": "d3afe269-6a1b-45d8-963c-5b1c08249b1a",
    "admin_block": "a8645db6-7a3e-4de6-a2d7-be6f6c291693",
    "acs": "eb0252a3-5817-48f8-af35-672050c5fb46",
    "peak_app": "832c830f-abc7-4ca5-ac1a-68987b7144b3",
    "mgmt_self": "d7583097-3044-4ccd-a391-67c1fde978d5",
    "mgmt_wired": "4766a786-2140-4cf2-a15b-63b6a8983261",
    "mgmt_wlcorp": "d44d0f95-e3ac-4f1a-b6fb-c577ce7f865a",
    "mgmt_wlguest": "6e07864c-a5e2-4af6-a498-a0d4ff58ad77",
    "mgmt_inet": "abf92213-2f30-496f-af4a-f57fd51fae8b",
    "wired_dns": "8775d0bb-edc7-4736-b7a4-98752dd86206",
    "wired_wlcorp": "9cdb9a90-6e4e-440a-bc3a-14cedf3e9ab9",
    "wired_inet": "06034113-3a1d-461e-9427-1daa9b16d8a2",
    "wired_block_guest": "b6c1281f-6be6-4a15-9b45-d6bf4fbcafef",
    "wl_icmp": "a7c3e91f-2b84-4d6e-9f1a-5e8d0c4b7a12",
    "wl_dns": "69c0df77-61f5-4e9b-8c87-2b6c7bd35dbc",
    "guest_dns": "204b9f91-cdaa-4077-ac22-8c73c1f4db88",
    "guest_cp": "49cd1036-18a0-406e-bebb-e71c7735e47b",
    "guest_block": "92a13ced-799a-4355-bc69-b27f633c795a",
    "guest_inet": "04d2ba2b-490f-4707-98a9-e317371ca83d",
    "wg_lan": "855bf1aa-21de-463e-8bf9-fbc2542abceb",
    "wg_self": "aadf170f-d2a7-4de0-8f37-bc85fd571ec7",
}


def log(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))
    LOG.append(msg)


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
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        raise SystemExit(f"HTTP {e.code} {path}: {raw[:800]}") from e
    if raw.lstrip().startswith("<!"):
        raise SystemExit(f"Auth failed {path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def selected_keys(field) -> str:
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, (list, tuple)):
        return ",".join(str(x) for x in field if x not in ("", None))
    if isinstance(field, dict):
        selected = []
        for name, meta in field.items():
            if name == "" and isinstance(meta, dict) and str(meta.get("selected")) in (
                "1",
                "true",
                "True",
            ):
                return ""
            if isinstance(meta, dict) and str(meta.get("selected")) in ("1", "true", "True"):
                selected.append(name)
            elif meta in (1, "1", True):
                selected.append(name)
        return ",".join(selected)
    return str(field)


OMIT_IF_EMPTY = {
    "categories",
    "sched",
    "gateway",
    "replyto",
    "shaper1",
    "shaper2",
    "prio",
    "set-prio",
    "set-prio-low",
    "tos",
    "overload",
    "received-on",
    "icmptype",
    "icmp6type",
    "state-policy",
}
OPTION_FIELDS = (
    "statetype",
    "state-policy",
    "action",
    "interface",
    "direction",
    "ipprotocol",
    "protocol",
    "gateway",
    "replyto",
    "categories",
    "sched",
    "icmptype",
    "icmp6type",
    "shaper1",
    "shaper2",
    "prio",
    "set-prio",
    "set-prio-low",
    "tos",
    "overload",
    "received-on",
)


def rule_to_set_payload(rule: dict, overrides: dict) -> dict:
    out = {}
    for k, v in rule.items():
        if k in ("audit",):
            continue
        if k in OPTION_FIELDS:
            sel = selected_keys(v)
            if not sel and k in OMIT_IF_EMPTY:
                continue
            out[k] = sel
        elif isinstance(v, dict):
            continue
        else:
            out[k] = v if v is not None else ""
    out.update(overrides)
    for k in list(out.keys()):
        if k in OMIT_IF_EMPTY and out[k] in ("", None, []):
            del out[k]
    return {"rule": out}


def get_rule(key, secret, uuid):
    r = api("GET", f"/api/firewall/filter/getRule/{uuid}", key, secret)
    return r["rule"]


def set_rule(key, secret, uuid, overrides, label):
    rule = get_rule(key, secret, uuid)
    payload = rule_to_set_payload(rule, overrides)
    res = api("POST", f"/api/firewall/filter/setRule/{uuid}", key, secret, payload)
    log(f"SET {label} ({uuid}): {res}")
    if isinstance(res, dict) and res.get("result") == "failed":
        raise SystemExit(f"setRule failed for {label}: {res}")
    return res


def toggle_rule(key, secret, uuid, enabled: int, label):
    # POST toggleRule/{uuid}/{enabled}
    res = api(
        "POST",
        f"/api/firewall/filter/toggleRule/{uuid}/{enabled}",
        key,
        secret,
        {},
    )
    log(f"TOGGLE {label} enabled={enabled}: {res}")
    return res


def del_rule(key, secret, uuid, label):
    res = api("POST", f"/api/firewall/filter/delRule/{uuid}", key, secret, {})
    log(f"DEL {label}: {res}")
    return res


def ensure_category(key, secret, name, color="000000"):
    q = urllib.parse.urlencode({"current": 1, "rowCount": 100, "searchPhrase": ""})
    page = api("GET", f"/api/firewall/category/searchItem?{q}", key, secret)
    for row in page.get("rows") or []:
        if row.get("name") == name:
            log(f"CATEGORY exists {name}={row.get('uuid')}")
            return row["uuid"]
    res = api(
        "POST",
        "/api/firewall/category/addItem",
        key,
        secret,
        {"category": {"name": name, "auto": "0", "color": color}},
    )
    log(f"CATEGORY add {name}: {res}")
    uuid = res.get("uuid") if isinstance(res, dict) else None
    if not uuid:
        raise SystemExit(f"Failed to create category {name}: {res}")
    return uuid


def ensure_wan_group(key, secret):
    q = urllib.parse.urlencode({"current": 1, "rowCount": 50, "searchPhrase": ""})
    page = api("GET", f"/api/firewall/group/searchItem?{q}", key, secret)
    for row in page.get("rows") or []:
        ifname = row.get("ifname") or row.get("name")
        if ifname == "WAN" or row.get("descr") == "WAN dual uplinks":
            log(f"GROUP exists WAN uuid={row.get('uuid')} ifname={ifname}")
            uuid = row["uuid"]
            got = api("GET", f"/api/firewall/group/getItem/{uuid}", key, secret)
            grp = got.get("group") if isinstance(got, dict) else {}
            members = selected_keys(grp.get("members")) if grp else ""
            if "wan" in members.split(",") and "opt1" in members.split(","):
                return "WAN", uuid
            api(
                "POST",
                f"/api/firewall/group/setItem/{uuid}",
                key,
                secret,
                {
                    "group": {
                        "ifname": "WAN",
                        "descr": "WAN dual uplinks",
                        "members": "wan,opt1",
                        "sequence": "5",
                        "nogroup": "0",
                    }
                },
            )
            api("POST", "/api/firewall/group/reconfigure", key, secret, {})
            return "WAN", uuid

    blank = api("GET", "/api/firewall/group/getItem", key, secret)
    log(f"GROUP blank keys: {list((blank.get('group') or {}).keys())}")
    res = api(
        "POST",
        "/api/firewall/group/addItem",
        key,
        secret,
        {
            "group": {
                "ifname": "WAN",
                "descr": "WAN dual uplinks",
                "members": "wan,opt1",
                "sequence": "5",
                "nogroup": "0",
            }
        },
    )
    log(f"GROUP add WAN: {res}")
    if isinstance(res, dict) and res.get("result") == "failed":
        raise SystemExit(f"group add failed: {res}")
    uuid = res.get("uuid")
    api("POST", "/api/firewall/group/reconfigure", key, secret, {})
    return "WAN", uuid


def try_nolog_default_block(key, secret):
    """Best-effort: probe endpoints for default-deny logging. Legacy setting has no clean API."""
    for path in (
        "/api/diagnostics/firewall/log",
        "/api/syslog/settings/get",
    ):
        try:
            r = api("GET", path, key, secret)
            blob = json.dumps(r)
            if "nologdefault" in blob or "logdefault" in blob:
                log(f"Found logging knobs in {path}")
                return r
        except SystemExit as e:
            log(f"Probe {path}: {e}")
    log(
        "SKIP quieter default-deny logs: no API for nologdefaultblock "
        "(set in Firewall → Settings → Advanced → Logging)"
    )
    return None


def main():
    key, secret = load_creds()
    log(f"Host {BASE}")

    # 1) Categories
    cat = {
        "WAN": ensure_category(key, secret, "WAN", "d9534f"),
        "MGMT": ensure_category(key, secret, "MGMT", "337ab7"),
        "CORP": ensure_category(key, secret, "CORP", "5cb85c"),
        "GUEST": ensure_category(key, secret, "GUEST", "f0ad4e"),
        "VPN": ensure_category(key, secret, "VPN", "5bc0de"),
    }

    # 2) WAN interface group
    wan_if, wan_uuid = ensure_wan_group(key, secret)
    log(f"Using WAN group ifname={wan_if} uuid={wan_uuid}")

    # 3) Delete redundant MGMT DNS (idempotent)
    mgmt_dns = api("GET", f"/api/firewall/filter/getRule/{UUID['mgmt_dns']}", key, secret)
    rule_obj = mgmt_dns.get("rule") if isinstance(mgmt_dns, dict) else None
    if isinstance(rule_obj, dict) and rule_obj:
        del_rule(key, secret, UUID["mgmt_dns"], "Allow MGMT DNS to firewall")
    else:
        log("MGMT DNS already deleted")

    # 4) MAC policy (Option A per WL-CORP-MAC-RULES.md)
    # Enable MAC allows; disable open WL_CORP east-west/internet
    for u, label in (
        (UUID["mac_inet"], "MAC internet"),
        (UUID["mac_wired"], "MAC wired"),
        (UUID["mac_mgmt"], "MAC mgmt"),
    ):
        # force enable via setRule in case toggle is flaky
        set_rule(key, secret, u, {"enabled": "1"}, f"enable {label}")

    # Fix MAC internet: !LAN_RFC1918 + WAN_LB (safer than dest any)
    set_rule(
        key,
        secret,
        UUID["mac_inet"],
        {
            "enabled": "1",
            "source_net": "WL_CORP_MACS",
            "destination_net": "LAN_RFC1918",
            "destination_not": "1",
            "gateway": "WAN_LB",
            "log": "0",
            "categories": cat["CORP"],
            "description": "Allow WL_CORP_MACS to Internet via WAN_LB",
        },
        "MAC internet harden",
    )
    set_rule(
        key,
        secret,
        UUID["mac_wired"],
        {
            "enabled": "1",
            "log": "0",
            "categories": cat["CORP"],
        },
        "MAC wired cats",
    )
    set_rule(
        key,
        secret,
        UUID["mac_mgmt"],
        {
            "enabled": "1",
            "log": "0",
            "categories": cat["CORP"],
        },
        "MAC mgmt cats",
    )

    for u, label in (
        (UUID["wl_corp_wired"], "open WL_CORP to WIRED"),
        (UUID["wl_corp_mgmt"], "open WL_CORP to MGMT"),
        (UUID["wl_corp_inet"], "open WL_CORP to Internet"),
    ):
        set_rule(key, secret, u, {"enabled": "0"}, f"disable {label}")

    set_rule(
        key,
        secret,
        UUID["mac_block"],
        {"enabled": "1", "log": "1", "categories": cat["CORP"]},
        "Block unknown MACs",
    )

    # Keep WL_CORP DNS/ICMP for all (DHCP clients); categorize
    set_rule(
        key,
        secret,
        UUID["wl_dns"],
        {"log": "0", "categories": cat["CORP"]},
        "WL DNS",
    )
    set_rule(
        key,
        secret,
        UUID["wl_icmp"],
        {"log": "0", "categories": cat["CORP"]},
        "WL ICMP",
    )

    # 5) WireGuard dest → (self)
    set_rule(
        key,
        secret,
        UUID["wg_wan"],
        {
            "destination_net": "(self)",
            "interface": wan_if,
            "log": "0",
            "categories": cat["VPN"],
            "description": "Allow WireGuard UDP 51820 on WAN",
        },
        "WG WAN dest self + WAN group",
    )

    # 6) Retarget dual-WAN rules to WAN group
    for u, label, cats in (
        (UUID["admin_block"], "Admin block", cat["WAN"]),
        (UUID["acs"], "ACS SQL", cat["WAN"]),
        (UUID["peak_app"], "PEAK-APP", cat["WAN"]),
    ):
        set_rule(
            key,
            secret,
            u,
            {"interface": wan_if, "categories": cats},
            f"{label} to {wan_if}",
        )

    # PEAK-APP: no Cloudflare alias present - leave src=any, note in log
    log(
        "SKIP PEAK-APP src lock: no Cloudflare/allowlist alias exists "
        "(src remains any -> OFFICE_PC:HTTP_HTTPS)"
    )

    # 7) Categorize remaining user rules + pass-log off / block-log on
    pass_cat = [
        (UUID["mgmt_self"], cat["MGMT"], "0"),
        (UUID["mgmt_wired"], cat["MGMT"], "0"),
        (UUID["mgmt_wlcorp"], cat["MGMT"], "0"),
        (UUID["mgmt_wlguest"], cat["MGMT"], "0"),
        (UUID["mgmt_inet"], cat["MGMT"], "0"),
        (UUID["wired_dns"], cat["CORP"], "0"),
        (UUID["wired_wlcorp"], cat["CORP"], "0"),
        (UUID["wired_inet"], cat["CORP"], "0"),
        (UUID["wired_block_guest"], cat["CORP"], "1"),
        (UUID["guest_dns"], cat["GUEST"], "0"),
        (UUID["guest_cp"], cat["GUEST"], "0"),
        (UUID["guest_block"], cat["GUEST"], "1"),
        (UUID["guest_inet"], cat["GUEST"], "0"),
        (UUID["wg_lan"], cat["VPN"], "0"),
        (UUID["wg_self"], cat["VPN"], "0"),
        (UUID["admin_block"], cat["WAN"], "1"),
        (UUID["acs"], cat["WAN"], "0"),
        (UUID["peak_app"], cat["WAN"], "0"),
    ]
    for u, c, logflag in pass_cat:
        ov = {"categories": c, "log": logflag}
        if u in (UUID["admin_block"], UUID["acs"], UUID["peak_app"]):
            ov["interface"] = wan_if
        set_rule(key, secret, u, ov, f"categorize/log {u}")

    log(
        "KEEP Guest DNS/Captive manual rules: they carry peak_optimised schedule "
        "(auto portal rules do not)"
    )

    # 8) Quieter default deny
    try_nolog_default_block(key, secret)

    # Apply
    apply = api("POST", "/api/firewall/filter/apply", key, secret, {})
    log(f"APPLY filter: {apply}")

    # Verify
    q = urllib.parse.urlencode({"current": 1, "rowCount": 200, "searchPhrase": ""})
    page = api("GET", f"/api/firewall/filter/searchRule?{q}", key, secret)
    rows = [r for r in (page.get("rows") or []) if "-" in str(r.get("uuid", ""))]
    log("\n=== USER RULES AFTER ===")
    for r in rows:
        log(
            f"  en={r.get('enabled')} {r.get('action'):5} if={r.get('interface')} "
            f"src={r.get('source_net')} dst={r.get('destination_net')} "
            f"dport={r.get('destination_port')} | {r.get('description') or r.get('descr')}"
        )

    Path(__file__).with_name("opt_apply_log.txt").write_text(
        "\n".join(LOG), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
