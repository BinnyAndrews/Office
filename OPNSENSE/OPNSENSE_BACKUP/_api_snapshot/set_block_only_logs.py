#!/usr/bin/env python3
"""Disable firewall pass-rule logs; keep/enable block-rule logs via OPNsense API."""

from __future__ import annotations

import base64
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://10.80.99.1:4444"
KEYFILE = Path(__file__).resolve().parents[1] / "PEAK-CORP-FW.peakenergy.asia_root_apikey.txt"
CTX = ssl._create_unverified_context()


def load_creds(path: Path) -> tuple[str, str]:
    key = secret = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("key="):
            key = line.split("=", 1)[1]
        elif line.startswith("secret="):
            secret = line.split("=", 1)[1]
    if not key or not secret:
        raise SystemExit(f"Missing key/secret in {path}")
    return key, secret


def api(method: str, path: str, key: str, secret: str, data: dict | None = None) -> dict | str:
    url = BASE + path
    body = None
    token = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("ascii")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {token}",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code} {path}: {raw[:500]}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"URL error {path}: {e}") from e
    if raw.lstrip().startswith("<!doctype") or raw.lstrip().startswith("<html"):
        raise SystemExit(f"Auth failed for {path} (got login HTML)")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def selected_action(rule: dict) -> str:
    action = rule.get("action")
    if isinstance(action, dict):
        for name, meta in action.items():
            if isinstance(meta, dict) and str(meta.get("selected")) in ("1", "true", "True"):
                return name
        return ""
    return str(action or "")


def is_truthy(val) -> bool:
    return str(val).lower() in ("1", "true", "yes", "on")


def toggle_log(key: str, secret: str, uuid: str, enabled: int) -> dict | str:
    """Prefer toggleRuleLog (POST on this host); fall back to setRule."""
    path = f"/api/firewall/filter/toggleRuleLog/{uuid}/{enabled}"
    r = api("POST", path, key, secret, data={})
    if isinstance(r, dict) and r.get("status") != "error":
        return r
    return api(
        "POST",
        f"/api/firewall/filter/setRule/{uuid}",
        key,
        secret,
        data={"rule": {"log": str(enabled)}},
    )


def main() -> int:
    key, secret = load_creds(KEYFILE)
    print(f"Using API host {BASE}")

    # Fetch all rules (paged)
    rows: list[dict] = []
    current = 1
    row_count = 200
    while True:
        q = urllib.parse.urlencode(
            {"current": current, "rowCount": row_count, "searchPhrase": ""}
        )
        page = api("GET", f"/api/firewall/filter/searchRule?{q}", key, secret)
        if not isinstance(page, dict):
            raise SystemExit(f"Unexpected searchRule response: {page!r}")
        batch = page.get("rows") or []
        rows.extend(batch)
        total = int(page.get("total") or 0)
        print(f"Fetched page {current}: {len(batch)} rows (total reported {total})")
        if not batch or len(rows) >= total:
            break
        current += 1

    # Full model for UUID-keyed rules
    full = api("GET", "/api/firewall/filter/get", key, secret)
    model_rules = {}
    if isinstance(full, dict):
        model_rules = (
            full.get("filter", {})
            .get("rules", {})
            .get("rule", {})
        ) or {}

    to_disable_pass: list[tuple[str, str]] = []
    to_enable_block: list[tuple[str, str]] = []
    already_ok = 0
    legacy_skipped = 0

    seen = set()
    # Prefer model rules (mutable via API)
    for uuid, rule in model_rules.items():
        seen.add(uuid)
        action = selected_action(rule)
        log_on = is_truthy(rule.get("log"))
        desc = rule.get("description") or rule.get("descr") or ""
        if action == "pass":
            if log_on:
                to_disable_pass.append((uuid, desc))
            else:
                already_ok += 1
        elif action in ("block", "reject"):
            if not log_on:
                to_enable_block.append((uuid, desc))
            else:
                already_ok += 1

    # searchRule may include legacy/non-model rules; report only
    for row in rows:
        uuid = row.get("uuid")
        if not uuid or uuid in seen:
            continue
        action = str(row.get("action") or "")
        log_on = is_truthy(row.get("log"))
        desc = row.get("description") or row.get("descr") or ""
        if (action == "pass" and log_on) or (
            action in ("block", "reject") and not log_on
        ):
            print(
                f"LEGACY/non-model needs change but not via filter API: "
                f"{uuid} action={action} log={row.get('log')} desc={desc!r}"
            )
            legacy_skipped += 1

    print(
        f"Plan: disable pass logs={len(to_disable_pass)}, "
        f"enable block logs={len(to_enable_block)}, already_ok={already_ok}, "
        f"legacy_skipped={legacy_skipped}"
    )

    changed = 0
    errors = 0
    for uuid, desc in to_disable_pass:
        r = toggle_log(key, secret, uuid, 0)
        ok = isinstance(r, dict) and (
            r.get("result") in ("saved", "ok", "OK")
            or r.get("status") in ("ok", "OK")
            or "result" in r
        )
        print(f"PASS log OFF  {uuid}  {desc!r}  -> {r}")
        if ok and not (isinstance(r, dict) and r.get("status") == "error"):
            changed += 1
        else:
            errors += 1

    for uuid, desc in to_enable_block:
        r = toggle_log(key, secret, uuid, 1)
        print(f"BLOCK log ON  {uuid}  {desc!r}  -> {r}")
        if isinstance(r, dict) and r.get("status") == "error":
            errors += 1
        else:
            changed += 1

    if changed:
        apply = api("POST", "/api/firewall/filter/apply", key, secret, data={})
        print(f"Applied filter changes: {apply}")
    else:
        print("No per-rule log toggles applied.")

    # Verify against live model
    verify = api("GET", "/api/firewall/filter/get", key, secret)
    bad_pass = []
    bad_block = []
    if isinstance(verify, dict):
        rules = (
            verify.get("filter", {})
            .get("rules", {})
            .get("rule", {})
        ) or {}
        for uuid, rule in rules.items():
            action = selected_action(rule)
            log_on = is_truthy(rule.get("log"))
            desc = rule.get("description") or ""
            if action == "pass" and log_on:
                bad_pass.append((uuid, desc))
            if action in ("block", "reject") and not log_on:
                bad_block.append((uuid, desc))

    print(
        f"Verify: pass-with-log={len(bad_pass)} "
        f"block-without-log={len(bad_block)} errors={errors}"
    )
    for uuid, desc in bad_pass[:30]:
        print(f"  STILL PASS LOG {uuid} {desc}")
    for uuid, desc in bad_block[:30]:
        print(f"  STILL BLOCK NOLOG {uuid} {desc}")

    return 1 if bad_pass or bad_block or errors else 0


if __name__ == "__main__":
    sys.exit(main())
