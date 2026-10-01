#!/usr/bin/env python3
"""Pull attendance events from Hikvision terminals into atteninfo for Keka."""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import pyodbc
import requests
import urllib3
from requests.auth import HTTPDigestAuth

from paths import app_dir, resource_dir

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = app_dir()
BUNDLE = resource_dir()


def normalize_hik_device_serial(raw: str | None) -> str:
    """Match old ACS atteninfo.deviceno (short serial, e.g. FF6135365).

    DeviceInfo sometimes returns a long product string ending in that serial
    (e.g. DS-K1T342MFWX…ENFF6135365). Prefer the short form Keka/ACS used.
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    m = re.search(r"(FF[0-9A-Fa-f]{7,})\s*$", s, re.I)
    if m:
        return m.group(1).upper()
    if len(s) > 20:
        m2 = re.search(r"([A-Z0-9]{8,12})\s*$", s, re.I)
        if m2:
            return m2.group(1).upper()
    return s[:50]


def normalize_card_no(raw: Any) -> str:
    """Match old ACS cardno: real badge digits, or empty string (never NULL)."""
    s = str(raw if raw is not None else "").strip()
    if not s or s.lower() in {"none", "null"}:
        return ""
    # Face/verify events often emit huge uint64-ish junk instead of a badge number
    if s.isdigit() and len(s) >= 16:
        try:
            if int(s) > 10**15:
                return ""
        except ValueError:
            pass
    return s[:50]


def as_text(value: Any, *, default: str = "", limit: int = 50) -> str:
    """VARCHAR fields for atteninfo — never None/NULL."""
    if value is None:
        return default[:limit]
    s = str(value).strip()
    return (s if s else default)[:limit]


ATTENINFO_VARCHAR_COLS = (
    "ID",
    "datetime",
    "date",
    "time",
    "authenticationresult",
    "authenticationtype",
    "device",
    "deviceno",
    "readername",
    "firstname",
    "lastname",
    "personname",
    "persongroup",
    "cardno",
    "direction",
)


def scrub_atteninfo_nulls(conn: pyodbc.Connection) -> int:
    """Replace NULL varchar cells with '' (and blank persongroup → All Departments)."""
    cur = conn.cursor()
    cur.execute("SELECT OBJECT_ID(N'dbo.atteninfo', N'U')")
    if cur.fetchone()[0] is None:
        return 0
    total = 0
    for col_name in ATTENINFO_VARCHAR_COLS:
        # Safe identifiers only (fixed list above)
        cur.execute(
            f"UPDATE dbo.atteninfo SET [{col_name}] = N'' WHERE [{col_name}] IS NULL"
        )
        total += int(cur.rowcount or 0)
    cur.execute(
        """
        UPDATE dbo.atteninfo
        SET persongroup = N'All Departments'
        WHERE persongroup IS NULL OR LTRIM(RTRIM(persongroup)) = N''
        """
    )
    total += int(cur.rowcount or 0)
    conn.commit()
    return total
FAIL_MINORS = {76}  # face auth failed — skip
LOG = logging.getLogger("peak-attendance")
APPSETTINGS = ROOT / "appsettings.json"


def setup_logging() -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_h = RotatingFileHandler(
        log_dir / "collector.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    LOG.addHandler(file_h)
    # Avoid attaching a console under pythonw / Task Scheduler
    if sys.stdout is not None and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        stream_h = logging.StreamHandler(sys.stdout)
        stream_h.setFormatter(fmt)
        LOG.addHandler(stream_h)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as fh:
        return json.load(fh)


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def parse_hik_time(value: str) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        try:
            dt = datetime.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
        return dt
    if dt.tzinfo is not None:
        return dt.astimezone(IST).replace(tzinfo=None)
    return dt


def fmt_hik_time(dt: datetime) -> str:
    # Hikvision AcsEvent requires an explicit offset (+05:30 for IST).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0530", "+05:30")


def resolve_device_port(dev: dict[str, Any]) -> int:
    """Effective HTTP(S) port. HTTPS + port 80 (left at HTTP default) → 443."""
    https = bool(dev.get("https"))
    try:
        port = int(dev.get("port") or (443 if https else 80))
    except (TypeError, ValueError):
        port = 443 if https else 80
    if https and port == 80:
        return 443
    if (not https) and port == 443:
        return 80
    return port


def device_base(dev: dict[str, Any]) -> str:
    scheme = "https" if dev.get("https") else "http"
    port = resolve_device_port(dev)
    return f"{scheme}://{dev['ip']}:{port}"


def local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1]


def xml_text(node: ET.Element, name: str) -> str | None:
    for child in node:
        if local_tag(child.tag) == name and child.text:
            return child.text.strip()
    return None


def parse_acs_xml(text: str) -> dict[str, Any]:
    root = ET.fromstring(text)
    info: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    for child in root:
        name = local_tag(child.tag)
        if name == "InfoList":
            rec = {local_tag(g.tag): (g.text or "").strip() for g in child}
            info.append(rec)
        else:
            payload[name] = (child.text or "").strip()
    payload["InfoList"] = info
    return payload


def parse_acs_body(resp: requests.Response) -> dict[str, Any]:
    text = resp.text or ""
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "json" in ctype or text.lstrip().startswith("{") or text.lstrip().startswith("["):
        data = resp.json()
        if isinstance(data, dict) and "AcsEvent" in data:
            return data["AcsEvent"]
        if isinstance(data, dict):
            return data
        raise ValueError("unexpected JSON from AcsEvent")
    return parse_acs_xml(text)


class HikTerminal:
    def __init__(self, dev: dict[str, Any], timeout: int) -> None:
        self.dev = dev
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = HTTPDigestAuth(dev["username"], dev["password"])
        self.session.headers["Accept"] = "application/json"
        self.session.verify = False
        self.base = device_base(dev)

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = self.base + path
        kwargs.setdefault("timeout", self.timeout)
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code == 401:
            raise RuntimeError(
                f"{self.dev['ip']}: auth failed or device locked (HTTP 401). "
                "Wait if lockout, then check admin password."
            )
        resp.raise_for_status()
        return resp

    def probe(self) -> str:
        resp = self.request("GET", "/ISAPI/System/deviceInfo?format=json")
        try:
            data = resp.json()
        except ValueError:
            root = ET.fromstring(resp.text)
            model = xml_text(root, "model") or "?"
            name = xml_text(root, "deviceName") or "?"
            return f"{name} ({model})"
        info = data.get("DeviceInfo", data)
        return f"{info.get('deviceName', '?')} ({info.get('model', '?')})"

    def device_serial(self) -> str | None:
        """Hikvision device serial (maps to atteninfo.deviceno). Cached per terminal."""
        cached = getattr(self, "_device_serial", None)
        if cached is not None:
            return cached or None
        serial = ""
        try:
            resp = self.request("GET", "/ISAPI/System/deviceInfo?format=json")
            try:
                data = resp.json()
                info = data.get("DeviceInfo", data) if isinstance(data, dict) else {}
                serial = str(
                    info.get("serialNumber")
                    or info.get("deviceID")
                    or info.get("macAddress")
                    or ""
                ).strip()
            except ValueError:
                root = ET.fromstring(resp.text)
                serial = (
                    xml_text(root, "serialNumber")
                    or xml_text(root, "deviceID")
                    or ""
                ).strip()
        except Exception as exc:
            LOG.warning("%s: could not read device serial: %s", self.dev.get("ip"), exc)
            serial = ""
        self._device_serial = normalize_hik_device_serial(serial)
        return self._device_serial or None

    def search_events(
        self,
        start: datetime,
        end: datetime,
        max_results: int,
    ) -> list[dict[str, Any]]:
        try:
            return self._search_pages(start, end, max_results, minor=0)
        except RuntimeError as exc:
            if "invalidOperation" not in str(exc) and "notSupport" not in str(exc):
                raise
            LOG.warning("%s: minor=0 rejected, retrying face/card/fingerprint", self.dev["ip"])
            merged: list[dict[str, Any]] = []
            for minor in (75, 38, 113):
                merged.extend(self._search_pages(start, end, max_results, minor=minor))
            return merged

    def _search_pages(
        self,
        start: datetime,
        end: datetime,
        max_results: int,
        minor: int,
    ) -> list[dict[str, Any]]:
        search_id = f"keka-{uuid.uuid4().hex[:12]}"
        position = 0
        collected: list[dict[str, Any]] = []
        while True:
            body = {
                "AcsEventCond": {
                    "searchID": search_id,
                    "searchResultPosition": position,
                    "maxResults": max_results,
                    "major": 5,
                    "minor": minor,
                    "startTime": fmt_hik_time(start),
                    "endTime": fmt_hik_time(end),
                }
            }
            resp = self.request(
                "POST",
                "/ISAPI/AccessControl/AcsEvent?format=json",
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
            )
            acs = parse_acs_body(resp)
            sub = str(acs.get("subStatusCode") or "").lower()
            if sub in {"invalidoperation", "notsupport"}:
                raise RuntimeError(sub)
            matches = acs.get("InfoList") or acs.get("infoList") or []
            if isinstance(matches, dict):
                matches = [matches]
            collected.extend(matches)
            status = str(acs.get("responseStatusStrg") or "").upper()
            got = int(acs.get("numOfMatches") or len(matches) or 0)
            if status in {"OK", "NO MATCH", "NO MATCHES", "NOMATCH"} or got == 0:
                break
            if status != "MORE":
                break
            position += got
        return collected

    def find_security_user_id(self, username: str) -> int:
        """Resolve Hikvision Security user id for the given login name (usually admin → 1)."""
        want = (username or "admin").strip().lower() or "admin"
        users = self._list_security_users()
        for u in users:
            name = str(u.get("userName") or u.get("username") or "").strip().lower()
            if name == want:
                uid = as_int(u.get("id"))
                if uid is not None:
                    return uid
        for u in users:
            level = str(u.get("userLevel") or u.get("userType") or "").lower()
            if "admin" in level:
                uid = as_int(u.get("id"))
                if uid is not None:
                    return uid
        if users:
            uid = as_int(users[0].get("id"))
            if uid is not None:
                return uid
        return 1

    def _list_security_users(self) -> list[dict[str, Any]]:
        """GET /ISAPI/Security/users — JSON preferred, XML fallback."""
        for path in (
            "/ISAPI/Security/users?format=json",
            "/ISAPI/Security/users",
        ):
            try:
                resp = self.request("GET", path)
            except Exception as exc:
                LOG.debug("%s: Security/users %s failed: %s", self.dev.get("ip"), path, exc)
                continue
            users = _parse_security_user_list(resp)
            if users:
                return users
        return []

    def change_admin_password(self, new_password: str) -> None:
        """Change this device's admin (login) password via ISAPI Security/users.

        Authenticates with the current password in ``self.dev``, then verifies
        with the new password. Does not update SQL/config — caller does that.
        """
        new_password = str(new_password or "")
        if not new_password.strip():
            raise ValueError("New password is empty.")
        old_password = str(self.dev.get("password") or "")
        username = str(self.dev.get("username") or "admin").strip() or "admin"
        if new_password == old_password:
            raise ValueError("New password is the same as the current password.")

        # Confirm current credentials before attempting a change
        self.probe()
        user_id = self.find_security_user_id(username)

        errors: list[str] = []
        # JSON first (modern ACS), then XML (older firmware)
        attempts: list[tuple[str, dict[str, str], Any]] = [
            (
                f"/ISAPI/Security/users/{user_id}?format=json",
                {"Content-Type": "application/json"},
                json.dumps(
                    {
                        "User": {
                            "id": user_id,
                            "userName": username,
                            "password": new_password,
                            "loginPassword": old_password,
                        }
                    }
                ),
            ),
            (
                f"/ISAPI/Security/users/{user_id}",
                {"Content-Type": "application/xml"},
                (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    f"<User><id>{user_id}</id>"
                    f"<userName>{_xml_escape(username)}</userName>"
                    f"<password>{_xml_escape(new_password)}</password>"
                    f"<loginPassword>{_xml_escape(old_password)}</loginPassword>"
                    "</User>"
                ),
            ),
            (
                "/ISAPI/Security/users",
                {"Content-Type": "application/xml"},
                (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    "<UserList><User>"
                    f"<id>{user_id}</id>"
                    f"<userName>{_xml_escape(username)}</userName>"
                    f"<password>{_xml_escape(new_password)}</password>"
                    f"<loginPassword>{_xml_escape(old_password)}</loginPassword>"
                    "</User></UserList>"
                ),
            ),
        ]
        changed = False
        for path, headers, body in attempts:
            try:
                resp = self._request_check_status("PUT", path, headers=headers, data=body)
                changed = True
                LOG.info(
                    "%s: admin password changed via %s (HTTP %s)",
                    self.dev.get("ip"),
                    path,
                    resp.status_code,
                )
                break
            except Exception as exc:
                errors.append(f"{path}: {exc}")
                LOG.warning(
                    "%s: password change attempt failed (%s): %s",
                    self.dev.get("ip"),
                    path,
                    exc,
                )

        if not changed:
            detail = errors[-1] if errors else "unknown error"
            raise RuntimeError(
                f"{self.dev.get('ip')}: could not change admin password — {detail}"
            )

        # Verify new password works (digest with updated credentials)
        verify_dev = dict(self.dev)
        verify_dev["password"] = new_password
        try:
            HikTerminal(verify_dev, timeout=self.timeout).probe()
        except Exception as exc:
            raise DevicePasswordChangedError(
                f"{self.dev.get('ip')}: admin password was changed on the device, "
                f"but login with the new password failed — {exc}"
            ) from exc

    def _request_check_status(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Like request(), but also reject Hikvision ResponseStatus failures (riskPassword, etc.)."""
        url = self.base + path
        kwargs.setdefault("timeout", self.timeout)
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code == 401:
            raise RuntimeError(
                f"{self.dev['ip']}: auth failed or device locked (HTTP 401). "
                "Wait if lockout, then check admin password."
            )
        ok, detail = parse_hik_response_status(resp)
        if resp.status_code >= 400 or not ok:
            msg = detail or f"HTTP {resp.status_code}"
            raise RuntimeError(f"{self.dev['ip']}: {msg}")
        return resp


class DevicePasswordChangedError(RuntimeError):
    """Password was applied on the device, but a later verify step failed."""


def _xml_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def parse_hik_response_status(resp: requests.Response) -> tuple[bool, str]:
    """Return (ok, detail) from a Hikvision ResponseStatus JSON/XML body.

    Empty 2xx body is treated as success. statusCode 1 / subStatusCode ok → success.
    """
    text = (resp.text or "").strip()
    if not text:
        return resp.status_code < 400, f"HTTP {resp.status_code}" if resp.status_code >= 400 else ""

    data: dict[str, Any] | None = None
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "json" in ctype or text.startswith("{") or text.startswith("["):
        try:
            raw = resp.json()
            if isinstance(raw, dict):
                data = raw.get("ResponseStatus") if isinstance(raw.get("ResponseStatus"), dict) else raw
        except Exception:
            data = None
    if data is None and text.startswith("<"):
        try:
            root = ET.fromstring(text)
            tag = local_tag(root.tag).lower()
            if tag == "responsestatus":
                data = {local_tag(c.tag): (c.text or "").strip() for c in root}
            else:
                # Nested ResponseStatus
                for child in root.iter():
                    if local_tag(child.tag).lower() == "responsestatus":
                        data = {local_tag(c.tag): (c.text or "").strip() for c in child}
                        break
        except ET.ParseError:
            data = None

    if not isinstance(data, dict):
        if resp.status_code < 400:
            return True, ""
        return False, (text[:200] or f"HTTP {resp.status_code}")

    status_code = str(data.get("statusCode") or "").strip()
    sub = str(data.get("subStatusCode") or "").strip()
    status = str(
        data.get("statusString") or data.get("statusMsg") or data.get("errorMsg") or ""
    ).strip()
    hints = {
        "riskPassword": "password rejected as too weak (riskPassword) — use a stronger password",
        "userPasswordError": "current admin password rejected",
        "deviceLocked": "device locked after failed logins — wait and retry",
        "notSupport": "password change not supported on this firmware",
        "invalidOperation": "invalid operation on this device",
    }
    hint = hints.get(sub, "")
    detail_parts = [p for p in (status, sub, hint) if p]
    detail = " — ".join(detail_parts) if detail_parts else ""

    # statusCode "1" = OK on Hikvision; missing statusCode on success payloads is OK
    if status_code in {"", "1", "OK", "ok"} and sub.lower() in {"", "ok"}:
        if resp.status_code < 400:
            return True, detail
    if status_code in {"1"} or sub.lower() == "ok":
        return True, detail
    if not status_code and not sub and resp.status_code < 400:
        return True, detail
    return False, detail or f"HTTP {resp.status_code}"


def _parse_security_user_list(resp: requests.Response) -> list[dict[str, Any]]:
    text = (resp.text or "").strip()
    if not text:
        return []
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "json" in ctype or text.startswith("{"):
        try:
            data = resp.json()
        except Exception:
            data = None
        if isinstance(data, dict):
            block = data.get("UserList") or data
            users = block.get("User") if isinstance(block, dict) else None
            if users is None and isinstance(data.get("User"), (list, dict)):
                users = data.get("User")
            if isinstance(users, dict):
                return [users]
            if isinstance(users, list):
                return [u for u in users if isinstance(u, dict)]
    if text.startswith("<"):
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        users: list[dict[str, Any]] = []
        for node in root.iter():
            if local_tag(node.tag).lower() != "user":
                continue
            rec = {local_tag(c.tag): (c.text or "").strip() for c in node}
            if rec.get("id") or rec.get("userName"):
                users.append(rec)
        return users
    return []


def change_device_admin_password(
    dev: dict[str, Any],
    new_password: str,
    *,
    timeout: int = 20,
) -> None:
    """Change admin password on one device and verify login with the new password."""
    HikTerminal(dev, timeout=timeout).change_admin_password(new_password)


def change_both_admin_passwords(
    devices: list[dict[str, Any]],
    new_password: str,
    *,
    timeout: int = 20,
) -> list[dict[str, Any]]:
    """Change admin password on each device in order (Entry then Exit).

    Stops after the first failure. Earlier devices may already have the new
    password on the hardware — caller must follow P1 (do not update SQL until
    every device in the list succeeds).
    """
    results: list[dict[str, Any]] = []
    for dev in devices:
        name = str(dev.get("display_name") or dev.get("name") or "?")
        ip = str(dev.get("ip") or "?")
        item: dict[str, Any] = {
            "name": name,
            "ip": ip,
            "ok": False,
            "changed": False,
            "detail": "",
        }
        try:
            change_device_admin_password(dev, new_password, timeout=timeout)
            item["ok"] = True
            item["changed"] = True
            item["detail"] = "Admin password changed and verified."
            LOG.info("OK password change %s (%s)", name, ip)
        except DevicePasswordChangedError as exc:
            item["changed"] = True
            item["detail"] = str(exc)
            item["reason"] = "password"
            LOG.error("PARTIAL password change %s (%s): %s", name, ip, exc)
            results.append(item)
            break
        except Exception as exc:
            code, detail = classify_device_error(exc)
            msg = str(exc).strip() or detail
            item["detail"] = msg
            item["reason"] = code
            LOG.error("FAIL password change %s (%s): %s", name, ip, msg)
            results.append(item)
            break
        results.append(item)
    return results


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def split_name(full: str) -> tuple[str, str]:
    """Split person name; missing parts are empty string (old ACS style, not NULL)."""
    parts = full.strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0][:50], ""
    return parts[0][:50], parts[1][:50]


def auth_result_label(minor: int | None) -> str:
    if minor in FAIL_MINORS:
        return "Failed"
    return "Succeeded"


def normalize_event(
    raw: dict[str, Any],
    dev: dict[str, Any],
    *,
    legacy_atteninfo: bool = False,
) -> dict[str, Any] | None:
    emp = str(raw.get("employeeNoString") or raw.get("employeeNo") or "").strip()
    if not emp:
        return None
    minor = as_int(raw.get("minor"))
    if minor in FAIL_MINORS:
        return None
    punch = parse_hik_time(str(raw.get("time") or ""))
    if punch is None:
        return None
    serial = as_int(raw.get("serialNo") or raw.get("serialNO"))
    person = (str(raw.get("name") or "").strip() or None)
    first, last = split_name(person) if person else ("", "")
    direction_ui = str(dev.get("direction") or ("In" if int(dev.get("status", 0)) == 0 else "Out"))
    device_label = str(dev.get("display_name") or dev.get("name") or dev["ip"])[:50]
    if legacy_atteninfo:
        # Match existing master.dbo.atteninfo conventions (Keka)
        direction = "1" if direction_ui.lower() in {"in", "entry", "0", "1"} else "2"
        if direction_ui.strip() in {"1", "2"}:
            direction = direction_ui.strip()
        dt_s = punch.strftime("%Y-%m-%dT%H:%M:%S")
        date_s = punch.strftime("%d-%m-%Y")
        device_label = device_label.upper()
        auth_result = "1"  # legacy stores numeric success
        auth_type = as_text(raw.get("currentVerifyMode") or raw.get("type") or "")
        if not auth_type or "face" in auth_type.lower():
            auth_type = "ACSEventFaceVerifyPass"
        card_no = normalize_card_no(raw.get("cardNo"))
        reader = as_text(
            raw.get("cardReaderName")
            or raw.get("readerName")
            or raw.get("doorName")
            or "Cardreader 01",
            default="Cardreader 01",
        )
        device_no = normalize_hik_device_serial(
            str(
                dev.get("device_serial")
                or raw.get("serialNumber")
                or raw.get("deviceSerialNo")
                or ""
            ).strip()
        )
    else:
        direction = direction_ui[:50]
        dt_s = punch.strftime("%Y-%m-%d %H:%M:%S")
        date_s = punch.strftime("%Y-%m-%d")
        auth_result = auth_result_label(minor)[:50]
        auth_type = as_text(raw.get("currentVerifyMode"))
        card_no = normalize_card_no(raw.get("cardNo"))
        reader = ""
        device_no = ""
    return {
        "ID": as_text(emp),
        "datetime": as_text(dt_s),
        "date": as_text(date_s),
        "time": as_text(punch.strftime("%H:%M:%S")),
        "authenticationresult": as_text(auth_result),
        "authenticationtype": as_text(auth_type),
        "device": as_text(device_label),
        "deviceno": as_text(device_no),
        "readername": as_text(reader),
        "firstname": as_text(first),
        "lastname": as_text(last),
        "personname": as_text(person),
        "persongroup": as_text(
            raw.get("belongGroup")
            or raw.get("employeeGroup")
            or raw.get("department")
            or raw.get("persongroup")
            or "",
            default="All Departments",
        ),
        "cardno": as_text(card_no),
        "direction": as_text(direction),
        "DeviceIP": dev["ip"],
        "SerialNo": serial,
        "LogTime": punch,  # for watermark
    }


def connect_sql(
    sql: dict[str, Any],
    database: str | None = None,
    *,
    autocommit: bool = False,
    timeout: int = 10,
    trusted: bool = False,
) -> pyodbc.Connection:
    drivers = [sql.get("driver") or "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]
    installed = {d for d in pyodbc.drivers()}
    db = database if database is not None else sql["database"]
    last_err: Exception | None = None
    for driver in drivers:
        if driver not in installed and installed:
            continue
        if trusted:
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={sql['server']};"
                f"DATABASE={db};"
                "Trusted_Connection=yes;"
                "Encrypt=yes;TrustServerCertificate=yes;"
            )
        else:
            conn_str = (
                f"DRIVER={{{driver}}};"
                f"SERVER={sql['server']};"
                f"DATABASE={db};"
                f"UID={sql['username']};"
                f"PWD={sql['password']};"
                "Encrypt=yes;TrustServerCertificate=yes;"
            )
        try:
            return pyodbc.connect(conn_str, timeout=max(1, int(timeout)), autocommit=autocommit)
        except pyodbc.Error as exc:
            last_err = exc
    raise RuntimeError(
        f"SQL connect failed. Installed ODBC drivers: {sorted(installed)}. Last error: {last_err}"
    )


def _sql_quote_literal(value: str) -> str:
    return value.replace("'", "''")


def is_local_sql_server(server: str) -> bool:
    host = (server or "").split(",")[0].split("\\")[0].strip().lower()
    return host in {"", ".", "localhost", "127.0.0.1", "(local)", "::1"} or host.endswith(".local")


def ensure_sa_and_sql_authentication(sql: dict[str, Any]) -> list[str]:
    """
    Ensure Mixed Mode (SQL + Windows auth) and enable the sa login.
    Prefer Windows auth when available (sysadmin); fall back to configured SQL login.
    Restart of SQL Server may be required for Mixed Mode to take effect.
    """
    notes: list[str] = []
    conn: pyodbc.Connection | None = None
    last_err: Exception | None = None

    # Prefer Windows auth for local/admin setup; also try configured SQL login
    attempts: list[bool] = [True, False] if is_local_sql_server(str(sql.get("server") or "")) else [False, True]
    for trusted in attempts:
        try:
            conn = connect_sql(sql, database="master", autocommit=True, trusted=trusted)
            mode = "Windows" if trusted else "SQL"
            notes.append(f"Connected to master via {mode} authentication.")
            break
        except Exception as exc:
            last_err = exc
            conn = None

    if conn is None:
        raise RuntimeError(
            "Cannot connect to SQL Server to enable sa / SQL authentication.\n"
            "On the SQL PC, run Create / Repair while logged on as a Windows admin, "
            "or enable Mixed Mode + sa in SSMS.\n"
            f"Last error: {last_err}"
        )

    try:
        cur = conn.cursor()
        cur.execute("SELECT CAST(SERVERPROPERTY('IsIntegratedSecurityOnly') AS int)")
        row = cur.fetchone()
        windows_only = bool(row and int(row[0] or 0) == 1)

        if windows_only:
            try:
                cur.execute(
                    """
                    EXEC xp_instance_regwrite
                        N'HKEY_LOCAL_MACHINE',
                        N'Software\\Microsoft\\MSSQLServer\\MSSQLServer',
                        N'LoginMode',
                        REG_DWORD,
                        2
                    """
                )
                notes.append(
                    "SQL authentication (Mixed Mode) enabled in registry — "
                    "restart the SQL Server service for it to take effect."
                )
                if is_local_sql_server(str(sql.get("server") or "")):
                    restarted = _restart_local_sql_services()
                    if restarted:
                        notes.extend(restarted)
                    else:
                        notes.append("Could not auto-restart SQL Server; restart the service manually.")
            except Exception as exc:
                notes.append(
                    "Could not set Mixed Mode automatically (need sysadmin on the SQL host). "
                    f"Details: {exc}"
                )
        else:
            notes.append("SQL authentication already enabled (Mixed Mode).")

        # Enable sa (Peak ACS uses sa → master.dbo.atteninfo)
        sa_password = str(sql.get("password") or "").strip()
        try:
            cur.execute("ALTER LOGIN [sa] ENABLE")
            notes.append("Login sa is ENABLED.")
            if sa_password:
                cur.execute(
                    "ALTER LOGIN [sa] WITH PASSWORD = N'"
                    + _sql_quote_literal(sa_password)
                    + "', CHECK_POLICY = OFF, CHECK_EXPIRATION = OFF"
                )
                notes.append("Login sa password updated from app settings.")
        except Exception as exc:
            notes.append(f"Could not enable/update sa: {exc}")

        # Confirm auth mode after changes
        try:
            cur.execute(
                """
                SELECT CASE SERVERPROPERTY('IsIntegratedSecurityOnly')
                    WHEN 1 THEN 'WindowsOnly' ELSE 'Mixed' END
                """
            )
            mode_row = cur.fetchone()
            if mode_row:
                notes.append(f"Current auth mode: {mode_row[0]}")
        except Exception:
            pass
    finally:
        conn.close()

    return notes


def _restart_local_sql_services() -> list[str]:
    """Restart local MSSQL* services so LoginMode=2 is applied."""
    notes: list[str] = []
    try:
        # List SQL Server services
        listed = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Service | Where-Object { $_.Name -like 'MSSQL*' -or $_.Name -eq 'MSSQLSERVER' } "
             "| Select-Object -ExpandProperty Name"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        names = [n.strip() for n in (listed.stdout or "").splitlines() if n.strip()]
        if not names:
            return notes
        for name in names:
            # Elevate restart via PowerShell RunAs when needed
            ps = (
                f"try {{ Restart-Service -Name '{name}' -Force -ErrorAction Stop; exit 0 }} "
                f"catch {{ "
                f"$p = Start-Process powershell -Verb RunAs -Wait -PassThru "
                f"-ArgumentList '-NoProfile -Command Restart-Service -Name ''{name}'' -Force'; "
                f"exit $p.ExitCode }}"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if r.returncode == 0:
                notes.append(f"Restarted service {name}.")
            else:
                notes.append(f"Service {name} restart exit={r.returncode}.")
        time.sleep(5)
    except Exception as exc:
        notes.append(f"SQL service restart skipped: {exc}")
    return notes


def punch_table_name(sql: dict[str, Any]) -> str:
    """Punch/events table — Peak ACS uses master.dbo.atteninfo."""
    name = str(sql.get("punch_table") or "atteninfo").strip() or "atteninfo"
    if not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"Invalid punch table name: {name}")
    return name


def uses_legacy_atteninfo(sql: dict[str, Any]) -> bool:
    return punch_table_name(sql).lower() == "atteninfo"


def ensure_atteninfo_database(sql: dict[str, Any]) -> list[str]:
    """Ensure helper tables in target DB (master for ACS). Returns status messages."""
    db_name = (sql.get("database") or "master").strip() or "master"
    # Only allow simple identifiers
    if not all(c.isalnum() or c == "_" for c in db_name):
        raise ValueError(f"Invalid database name: {db_name}")

    notes: list[str] = []
    system_dbs = {"master", "model", "msdb", "tempdb"}
    if db_name.lower() not in system_dbs:
        master = connect_sql(sql, database="master", autocommit=True)
        try:
            cur = master.cursor()
            cur.execute("SELECT DB_ID(?)", db_name)
            row = cur.fetchone()
            if row is None or row[0] is None:
                cur.execute(f"CREATE DATABASE [{db_name}]")
                notes.append(f"Created database [{db_name}].")
            else:
                notes.append(f"Database [{db_name}] already exists.")
        finally:
            master.close()
    else:
        notes.append(f"Using system database [{db_name}] (no CREATE DATABASE).")

    punch = punch_table_name(sql)
    notes.append(f"Punch table: dbo.{punch}")

    conn = connect_sql(sql, database=db_name, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute("SET QUOTED_IDENTIFIER ON")
        cur.execute("SET ANSI_NULLS ON")

        statements: list[tuple[str, str]] = []
        # Only create AccessEvents when that is the configured punch table
        if punch.lower() == "accessevents":
            statements.append(
                (
                    "AccessEvents",
                    """
                IF OBJECT_ID(N'dbo.AccessEvents', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.AccessEvents (
                        RowId                 BIGINT IDENTITY(1, 1) NOT NULL
                            CONSTRAINT PK_AccessEvents PRIMARY KEY,
                        ID                    VARCHAR(50)  NOT NULL,
                        [datetime]            VARCHAR(50)  NOT NULL,
                        [date]                VARCHAR(50)  NOT NULL,
                        [time]                VARCHAR(50)  NOT NULL,
                        authenticationresult  VARCHAR(50)  NULL,
                        authenticationtype    VARCHAR(50)  NULL,
                        device                VARCHAR(50)  NULL,
                        firstname             VARCHAR(50)  NULL,
                        lastname              VARCHAR(50)  NULL,
                        personname            VARCHAR(50)  NULL,
                        persongroup           VARCHAR(50)  NULL,
                        direction             VARCHAR(50)  NOT NULL,
                        DeviceIP              NVARCHAR(64) NULL,
                        SerialNo              BIGINT       NULL,
                        InsertedAt            DATETIME2(0) NOT NULL
                            CONSTRAINT DF_AccessEvents_InsertedAt DEFAULT (SYSUTCDATETIME())
                    );
                END
                """,
                )
            )
            statements.append(
                (
                    "UX_AccessEvents_DeviceSerial",
                    """
                IF NOT EXISTS (
                    SELECT 1 FROM sys.indexes
                    WHERE name = N'UX_AccessEvents_DeviceSerial'
                      AND object_id = OBJECT_ID(N'dbo.AccessEvents')
                )
                BEGIN
                    CREATE UNIQUE INDEX UX_AccessEvents_DeviceSerial
                        ON dbo.AccessEvents (DeviceIP, SerialNo)
                        WHERE SerialNo IS NOT NULL;
                END
                """,
                )
            )
            statements.append(
                (
                    "UX_AccessEvents_Punch",
                    """
                IF NOT EXISTS (
                    SELECT 1 FROM sys.indexes
                    WHERE name = N'UX_AccessEvents_Punch'
                      AND object_id = OBJECT_ID(N'dbo.AccessEvents')
                )
                BEGIN
                    CREATE UNIQUE INDEX UX_AccessEvents_Punch
                        ON dbo.AccessEvents (ID, [datetime], direction, device);
                END
                """,
                )
            )
        else:
            # Peak ACS punch table master.dbo.atteninfo — create if missing, never alter if present
            cur.execute("SELECT OBJECT_ID(N'dbo.atteninfo', N'U')")
            if cur.fetchone()[0] is None:
                cur.execute(
                    """
                    CREATE TABLE dbo.atteninfo (
                        ID                    VARCHAR(50) NULL CONSTRAINT DF_atteninfo_ID DEFAULT (''),
                        [datetime]            VARCHAR(50) NULL CONSTRAINT DF_atteninfo_datetime DEFAULT (''),
                        [date]                VARCHAR(50) NULL CONSTRAINT DF_atteninfo_date DEFAULT (''),
                        [time]                VARCHAR(50) NULL CONSTRAINT DF_atteninfo_time DEFAULT (''),
                        authenticationresult  VARCHAR(50) NULL CONSTRAINT DF_atteninfo_authresult DEFAULT (''),
                        authenticationtype    VARCHAR(50) NULL CONSTRAINT DF_atteninfo_authtype DEFAULT (''),
                        device                VARCHAR(50) NULL CONSTRAINT DF_atteninfo_device DEFAULT (''),
                        deviceno              VARCHAR(50) NULL CONSTRAINT DF_atteninfo_deviceno DEFAULT (''),
                        readername            VARCHAR(50) NULL CONSTRAINT DF_atteninfo_readername DEFAULT (''),
                        firstname             VARCHAR(50) NULL CONSTRAINT DF_atteninfo_firstname DEFAULT (''),
                        lastname              VARCHAR(50) NULL CONSTRAINT DF_atteninfo_lastname DEFAULT (''),
                        personname            VARCHAR(50) NULL CONSTRAINT DF_atteninfo_personname DEFAULT (''),
                        persongroup           VARCHAR(50) NULL CONSTRAINT DF_atteninfo_persongroup DEFAULT ('All Departments'),
                        cardno                VARCHAR(50) NULL CONSTRAINT DF_atteninfo_cardno DEFAULT (''),
                        direction             VARCHAR(50) NULL CONSTRAINT DF_atteninfo_direction DEFAULT ('')
                    );
                    """
                )
                notes.append("Created dbo.atteninfo (ACS / Keka punch table).")
            else:
                notes.append("OK: atteninfo (existing — not modified)")

        statements.extend(
            [
            (
                "CollectorState",
                """
                IF OBJECT_ID(N'dbo.CollectorState', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.CollectorState (
                        DeviceIP        NVARCHAR(64)  NOT NULL
                            CONSTRAINT PK_CollectorState PRIMARY KEY,
                        LastEventTime   DATETIME2(0)  NULL,
                        LastSerialNo    BIGINT        NULL,
                        LastSuccessUtc  DATETIME2(0)  NULL,
                        LastError       NVARCHAR(400) NULL
                    );
                END
                """,
            ),
            (
                "DeviceConfig",
                """
                IF OBJECT_ID(N'dbo.DeviceConfig', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.DeviceConfig (
                        DeviceKey    VARCHAR(32)   NOT NULL
                            CONSTRAINT PK_DeviceConfig PRIMARY KEY,
                        DisplayName  NVARCHAR(64)  NOT NULL,
                        IpAddress    VARCHAR(64)   NOT NULL,
                        Port         INT           NOT NULL
                            CONSTRAINT DF_DeviceConfig_Port DEFAULT (80),
                        Username     NVARCHAR(64)  NOT NULL,
                        Password     NVARCHAR(128) NOT NULL,
                        Direction    VARCHAR(10)   NOT NULL,
                        Https        BIT           NOT NULL
                            CONSTRAINT DF_DeviceConfig_Https DEFAULT (0),
                        Enabled      BIT           NOT NULL
                            CONSTRAINT DF_DeviceConfig_Enabled DEFAULT (1),
                        UpdatedAt    DATETIME2(0)  NOT NULL
                            CONSTRAINT DF_DeviceConfig_UpdatedAt DEFAULT (SYSUTCDATETIME())
                    );
                END
                """,
            ),
            (
                "AppConfig",
                """
                IF OBJECT_ID(N'dbo.AppConfig', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.AppConfig (
                        ConfigKey    VARCHAR(64)    NOT NULL
                            CONSTRAINT PK_AppConfig PRIMARY KEY,
                        ConfigValue  NVARCHAR(512)  NOT NULL,
                        UpdatedAt    DATETIME2(0)   NOT NULL
                            CONSTRAINT DF_AppConfig_UpdatedAt DEFAULT (SYSUTCDATETIME())
                    );
                END
                """,
            ),
            (
                "seed DeviceConfig",
                """
                IF NOT EXISTS (SELECT 1 FROM dbo.DeviceConfig)
                BEGIN
                    INSERT INTO dbo.DeviceConfig
                        (DeviceKey, DisplayName, IpAddress, Port, Username, Password, Direction, Https, Enabled)
                    VALUES
                        ('entry', N'Entry Reader', '10.80.100.11', 80, N'admin', N'poli44557', 'In',  0, 1),
                        ('exit',  N'Exit Reader',  '10.80.100.12', 80, N'admin', N'poli44557', 'Out', 0, 1);
                END
                """,
            ),
            (
                "seed AppConfig",
                """
                IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'SyncIntervalMinutes')
                    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'SyncIntervalMinutes', N'1');
                IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'MaxResults')
                    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'MaxResults', N'30');
                IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'OverlapSeconds')
                    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'OverlapSeconds', N'120');
                IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'FirstLookbackHours')
                    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'FirstLookbackHours', N'24');
                IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'TimeoutSeconds')
                    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'TimeoutSeconds', N'20');
                IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'CollectorEnabled')
                    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'CollectorEnabled', N'0');
                """,
            ),
            (
                "Employees",
                """
                IF OBJECT_ID(N'dbo.Employees', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.Employees (
                        EmployeeNo      VARCHAR(32)    NOT NULL
                            CONSTRAINT PK_Employees PRIMARY KEY,
                        Name            NVARCHAR(128)  NOT NULL,
                        FirstName       NVARCHAR(64)   NULL,
                        LastName        NVARCHAR(64)   NULL,
                        Gender          VARCHAR(16)    NULL,
                        UserType        VARCHAR(32)    NULL,
                        CardNo          VARCHAR(64)    NULL,
                        ValidEnabled    BIT            NOT NULL
                            CONSTRAINT DF_Employees_ValidEnabled DEFAULT (1),
                        ValidFrom       DATETIME2(0)   NULL,
                        ValidTo         DATETIME2(0)   NULL,
                        FaceImage       VARBINARY(MAX) NULL,
                        HasFace         BIT            NOT NULL
                            CONSTRAINT DF_Employees_HasFace DEFAULT (0),
                        Notes           NVARCHAR(256)  NULL,
                        SourceDevices   NVARCHAR(64)   NULL,
                        CreatedAt       DATETIME2(0)   NOT NULL
                            CONSTRAINT DF_Employees_CreatedAt DEFAULT (SYSUTCDATETIME()),
                        UpdatedAt       DATETIME2(0)   NOT NULL
                            CONSTRAINT DF_Employees_UpdatedAt DEFAULT (SYSUTCDATETIME())
                    );
                END
                """,
            ),
            (
                "EmployeeDeviceSync",
                """
                IF OBJECT_ID(N'dbo.EmployeeDeviceSync', N'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.EmployeeDeviceSync (
                        EmployeeNo   VARCHAR(32)   NOT NULL,
                        DeviceKey    VARCHAR(32)   NOT NULL,
                        LastSyncUtc  DATETIME2(0)  NULL,
                        Status       VARCHAR(32)   NOT NULL
                            CONSTRAINT DF_EmployeeDeviceSync_Status DEFAULT (N'Pending'),
                        Error        NVARCHAR(400) NULL,
                        CONSTRAINT PK_EmployeeDeviceSync PRIMARY KEY (EmployeeNo, DeviceKey),
                        CONSTRAINT FK_EmployeeDeviceSync_Employees
                            FOREIGN KEY (EmployeeNo) REFERENCES dbo.Employees(EmployeeNo)
                            ON DELETE CASCADE
                    );
                END
                """,
            ),
            ]
        )

        for label, sql_text in statements:
            cur.execute(sql_text)
            notes.append(f"OK: {label}")

        cur.execute(
            "SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo') ORDER BY name"
        )
        tables = [r[0] for r in cur.fetchall()]
        notes.append("Tables: " + ", ".join(tables))
        scrubbed = scrub_atteninfo_nulls(conn)
        if scrubbed:
            notes.append(f"Cleared NULL varchar values in atteninfo ({scrubbed} cell update(s)).")
    finally:
        conn.close()

    return notes


def load_runtime_config(appsettings_path: Path = APPSETTINGS) -> dict[str, Any]:
    """Bootstrap SQL from appsettings.json; devices/poll from DB tables."""
    if not appsettings_path.exists():
        example = ROOT / "appsettings.example.json"
        raise FileNotFoundError(
            f"Missing {appsettings_path}. Copy {example.name} to appsettings.json and edit."
        )
    boot = load_json(appsettings_path)
    sql = boot["sql"]
    conn = connect_sql(sql)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DeviceKey, DisplayName, IpAddress, Port, Username, Password,
                   Direction, Https, Enabled
            FROM dbo.DeviceConfig
            WHERE Enabled = 1
            ORDER BY CASE DeviceKey WHEN 'entry' THEN 0 WHEN 'exit' THEN 1 ELSE 2 END, DeviceKey
            """
        )
        devices: list[dict[str, Any]] = []
        for row in cur.fetchall():
            direction = (row.Direction or "In").strip()
            status = 0 if direction.lower() in {"in", "entry", "0"} else 1
            devices.append(
                {
                    "name": row.DeviceKey,
                    "display_name": row.DisplayName,
                    "ip": row.IpAddress,
                    "port": int(row.Port or 80),
                    "https": bool(row.Https),
                    "username": row.Username,
                    "password": row.Password,
                    "direction": direction,
                    "device_number": 1 if status == 0 else 2,
                    "status": status,
                }
            )
        cur.execute("SELECT ConfigKey, ConfigValue FROM dbo.AppConfig")
        app_cfg = {r.ConfigKey: r.ConfigValue for r in cur.fetchall()}
    finally:
        conn.close()

    poll = {
        "max_results": int(app_cfg.get("MaxResults") or 30),
        "overlap_seconds": int(app_cfg.get("OverlapSeconds") or 120),
        "first_lookback_hours": int(app_cfg.get("FirstLookbackHours") or 24),
        "timeout_seconds": int(app_cfg.get("TimeoutSeconds") or 20),
        "sync_interval_minutes": int(app_cfg.get("SyncIntervalMinutes") or 1),
    }
    enabled = False
    if "collector_enabled" in boot:
        # File next to the exe is authoritative for scheduled --collect runs
        enabled = bool(boot.get("collector_enabled"))
    elif "CollectorEnabled" in app_cfg:
        enabled = str(app_cfg.get("CollectorEnabled") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    return {
        "sql": sql,
        "devices": devices,
        "poll": poll,
        "app_cfg": app_cfg,
        "collector_enabled": enabled,
    }


def is_collector_enabled(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("collector_enabled"))


def load_watermark(cur: pyodbc.Cursor, device_ip: str) -> datetime | None:
    cur.execute(
        "SELECT LastEventTime FROM dbo.CollectorState WHERE DeviceIP = ?",
        device_ip,
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def reset_device_watermark(sql: dict[str, Any], device_ip: str) -> None:
    """Clear CollectorState for a device so the next collect uses FirstLookbackHours."""
    conn = connect_sql(sql)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dbo.CollectorState WHERE DeviceIP = ?", device_ip)
        conn.commit()
    finally:
        conn.close()


def save_watermark(
    cur: pyodbc.Cursor,
    device_ip: str,
    last_event: datetime | None,
    last_serial: int | None,
    error: str | None,
) -> None:
    cur.execute(
        """
        MERGE dbo.CollectorState AS t
        USING (SELECT ? AS DeviceIP) AS s
        ON t.DeviceIP = s.DeviceIP
        WHEN MATCHED THEN UPDATE SET
            LastEventTime  = COALESCE(?, t.LastEventTime),
            LastSerialNo   = COALESCE(?, t.LastSerialNo),
            LastSuccessUtc = CASE WHEN ? IS NULL THEN SYSUTCDATETIME() ELSE t.LastSuccessUtc END,
            LastError      = ?
        WHEN NOT MATCHED THEN INSERT (DeviceIP, LastEventTime, LastSerialNo, LastSuccessUtc, LastError)
        VALUES (?, ?, ?, CASE WHEN ? IS NULL THEN SYSUTCDATETIME() ELSE NULL END, ?);
        """,
        device_ip,
        last_event,
        last_serial,
        error,
        error,
        device_ip,
        last_event,
        last_serial,
        error,
        error,
    )


def insert_rows(
    cur: pyodbc.Cursor,
    rows: list[dict[str, Any]],
    *,
    punch_table: str = "atteninfo",
) -> int:
    inserted = 0
    table = punch_table_name({"punch_table": punch_table})
    legacy = table.lower() == "atteninfo"
    if legacy:
        sql = f"""
        INSERT INTO dbo.[{table}] (
            ID, [datetime], [date], [time],
            authenticationresult, authenticationtype, device,
            deviceno, readername,
            firstname, lastname, personname, persongroup, cardno, direction
        ) VALUES (
            COALESCE(?, N''), COALESCE(?, N''), COALESCE(?, N''), COALESCE(?, N''),
            COALESCE(?, N''), COALESCE(?, N''), COALESCE(?, N''),
            COALESCE(?, N''), COALESCE(?, N''),
            COALESCE(?, N''), COALESCE(?, N''), COALESCE(?, N''),
            COALESCE(NULLIF(LTRIM(RTRIM(?)), N''), N'All Departments'),
            COALESCE(?, N''), COALESCE(?, N'')
        );
        """
        # Soft de-dupe (legacy table has no unique index)
        exists_sql = f"""
        SELECT TOP 1 1 FROM dbo.[{table}]
        WHERE ID = ? AND [datetime] = ? AND direction = ? AND device = ?
        """
    else:
        sql = f"""
        INSERT INTO dbo.[{table}] (
            ID, [datetime], [date], [time],
            authenticationresult, authenticationtype, device,
            firstname, lastname, personname, persongroup, direction,
            DeviceIP, SerialNo
        ) VALUES (
            COALESCE(?, N''), COALESCE(?, N''), COALESCE(?, N''), COALESCE(?, N''),
            COALESCE(?, N''), COALESCE(?, N''), COALESCE(?, N''),
            COALESCE(?, N''), COALESCE(?, N''), COALESCE(?, N''),
            COALESCE(NULLIF(LTRIM(RTRIM(?)), N''), N'All Departments'),
            COALESCE(?, N''),
            ?, ?
        );
        """
        exists_sql = None

    for row in rows:
        try:
            if exists_sql is not None:
                cur.execute(
                    exists_sql,
                    row["ID"],
                    row["datetime"],
                    row["direction"],
                    row["device"],
                )
                if cur.fetchone():
                    continue
            if legacy:
                cur.execute(
                    sql,
                    as_text(row.get("ID")),
                    as_text(row.get("datetime")),
                    as_text(row.get("date")),
                    as_text(row.get("time")),
                    as_text(row.get("authenticationresult")),
                    as_text(row.get("authenticationtype")),
                    as_text(row.get("device")),
                    as_text(row.get("deviceno")),
                    as_text(row.get("readername")),
                    as_text(row.get("firstname")),
                    as_text(row.get("lastname")),
                    as_text(row.get("personname")),
                    as_text(row.get("persongroup"), default="All Departments"),
                    as_text(row.get("cardno")),
                    as_text(row.get("direction")),
                )
            else:
                cur.execute(
                    sql,
                    as_text(row.get("ID")),
                    as_text(row.get("datetime")),
                    as_text(row.get("date")),
                    as_text(row.get("time")),
                    as_text(row.get("authenticationresult")),
                    as_text(row.get("authenticationtype")),
                    as_text(row.get("device")),
                    as_text(row.get("firstname")),
                    as_text(row.get("lastname")),
                    as_text(row.get("personname")),
                    as_text(row.get("persongroup"), default="All Departments"),
                    as_text(row.get("direction")),
                    row["DeviceIP"],
                    row["SerialNo"],
                )
            inserted += 1
        except pyodbc.IntegrityError:
            continue
        except pyodbc.Error as exc:
            if exc.args and str(exc.args[0]) in {"23000"}:
                continue
            raise
    return inserted


def window_for(
    dev: dict[str, Any],
    cur: pyodbc.Cursor | None,
    poll: dict[str, Any],
    ignore_watermark: bool = False,
) -> tuple[datetime, datetime]:
    now = datetime.now(IST).replace(tzinfo=None)
    end = now + timedelta(minutes=5)
    overlap = int(poll.get("overlap_seconds") or 120)
    lookback_h = int(poll.get("first_lookback_hours") or 24)
    watermark = None
    if cur is not None and not ignore_watermark:
        watermark = load_watermark(cur, dev["ip"])
    if watermark:
        start = watermark - timedelta(seconds=overlap)
    else:
        start = now - timedelta(hours=lookback_h)
    return start, end


def collect_device(
    cfg: dict[str, Any],
    dev: dict[str, Any],
    conn: pyodbc.Connection | None,
    dry_run: bool,
    ignore_watermark: bool = False,
) -> dict[str, Any]:
    """Collect one device. Returns a result dict; does not raise for device errors."""
    name = str(dev.get("name") or "?")
    ip = str(dev.get("ip") or "?")
    result: dict[str, Any] = {
        "name": name,
        "ip": ip,
        "ok": False,
        "reason": "",
        "detail": "",
        "inserted": 0,
        "events": 0,
        "punches": 0,
    }
    poll = cfg.get("poll") or {}
    timeout = int(poll.get("timeout_seconds") or 20)
    max_results = int(poll.get("max_results") or 30)
    hik = HikTerminal(dev, timeout=timeout)
    cur = conn.cursor() if conn is not None else None
    start, end = window_for(dev, cur, poll, ignore_watermark=ignore_watermark)
    LOG.info(
        "%s (%s) searching %s → %s",
        name,
        ip,
        fmt_hik_time(start),
        fmt_hik_time(end),
    )
    try:
        raw_events = hik.search_events(start, end, max_results)
        legacy = uses_legacy_atteninfo(cfg.get("sql") or {})
        punch = punch_table_name(cfg.get("sql") or {})
        if legacy:
            # Populate atteninfo.deviceno from the terminal serial (e.g. FF6135365)
            serial_txt = hik.device_serial()
            if serial_txt:
                dev = dict(dev)
                dev["device_serial"] = serial_txt
        rows = [
            r
            for r in (
                normalize_event(e, dev, legacy_atteninfo=legacy) for e in raw_events
            )
            if r
        ]
        result["events"] = len(raw_events)
        result["punches"] = len(rows)
        LOG.info("%s: %s device events, %s punches after filter", ip, len(raw_events), len(rows))
        if dry_run:
            for row in rows:
                LOG.info(
                    "DRY %s id=%s time=%s dir=%s serial=%s",
                    row["DeviceIP"],
                    row["ID"],
                    row["datetime"],
                    row["direction"],
                    row["SerialNo"],
                )
            result["ok"] = True
            result["reason"] = "success"
            result["detail"] = f"Dry-run OK — {len(rows)} punch(es) (not written)."
            return result
        assert cur is not None and conn is not None
        added = insert_rows(cur, rows, punch_table=punch)
        result["inserted"] = added
        last_event = max((r["LogTime"] for r in rows), default=None)
        last_serial = None
        serials = [r["SerialNo"] for r in rows if r["SerialNo"] is not None]
        if serials:
            last_serial = max(serials)
        save_watermark(cur, dev["ip"], last_event, last_serial, None)
        conn.commit()
        LOG.info("%s: inserted %s new row(s)", ip, added)
        result["ok"] = True
        result["reason"] = "success"
        result["detail"] = (
            f"OK — {len(raw_events)} event(s), {len(rows)} punch(es), inserted {added} new row(s)."
        )
        return result
    except Exception as exc:
        code, detail = classify_device_error(exc)
        result["reason"] = code
        result["detail"] = detail
        if code in {"connectivity", "password", "http"}:
            LOG.error("%s (%s) FAILED [%s]: %s", name, ip, code, detail)
        else:
            LOG.exception("%s (%s) FAILED [%s]: %s", name, ip, code, detail)
        if cur is not None and conn is not None:
            try:
                save_watermark(cur, dev["ip"], None, None, detail[:400])
                conn.commit()
            except Exception:
                conn.rollback()
        return result


def collect_all(
    cfg: dict[str, Any],
    dry_run: bool = False,
    ignore_watermark: bool = False,
) -> list[dict[str, Any]]:
    conn = None if dry_run else connect_sql(cfg["sql"])
    results: list[dict[str, Any]] = []
    try:
        for dev in cfg["devices"]:
            results.append(
                collect_device(
                    cfg, dev, conn, dry_run=dry_run, ignore_watermark=ignore_watermark
                )
            )
    finally:
        if conn is not None:
            conn.close()
    return results


def classify_device_error(exc: BaseException) -> tuple[str, str]:
    """Return (reason_code, human_message) for probe/collect failures."""
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "connectivity", "Connectivity failed — connection timed out (device unreachable or wrong IP)."
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "connectivity", "Connectivity failed — device did not respond in time."
    if isinstance(exc, requests.exceptions.ConnectionError):
        text = str(exc).lower()
        if "name or service not known" in text or "getaddrinfo failed" in text:
            return "connectivity", "Connectivity failed — hostname/IP could not be resolved."
        if "refused" in text:
            return "connectivity", "Connectivity failed — connection refused (wrong IP/port or device offline)."
        if "timed out" in text or "timeout" in text:
            return "connectivity", "Connectivity failed — network timeout (VPN/LAN or wrong IP)."
        # Avoid dumping raw urllib3 pool text to users
        if "max retries" in text or "httpconnectionpool" in text:
            return "connectivity", "Connectivity failed — device unreachable (check IP, port, VPN/LAN)."
        return "connectivity", "Connectivity failed — could not connect to the device."
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        code = getattr(resp, "status_code", None)
        if code == 401:
            return "password", "Wrong username/password, or device temporarily locked after failed logins."
        if code == 403:
            return "password", "Access forbidden (HTTP 403) — check user permissions on the device."
        hik_detail = _hik_http_detail(resp)
        if hik_detail:
            return "http", f"HTTP {code}: {hik_detail}"
        return "http", f"HTTP error {code}: {exc}"
    msg = str(exc)
    low = msg.lower()
    if "401" in msg or "auth failed" in low or "device locked" in low:
        return "password", "Wrong username/password, or device temporarily locked after failed logins."
    if "timed out" in low or "timeout" in low:
        return "connectivity", "Connectivity failed — network timeout (VPN/LAN or wrong IP)."
    if "refused" in low or "unreachable" in low:
        return "connectivity", "Connectivity failed — device unreachable."
    return "other", msg


def _hik_http_detail(resp: Any) -> str:
    """Pull statusString / subStatusCode from Hikvision JSON error body."""
    if resp is None:
        return ""
    try:
        data = resp.json()
    except Exception:
        text = (getattr(resp, "text", None) or "")[:200].strip()
        return text
    if not isinstance(data, dict):
        return ""
    status = (
        data.get("statusString")
        or data.get("statusMsg")
        or data.get("errorMsg")
        or data.get("message")
        or ""
    )
    sub = data.get("subStatusCode") or data.get("errorCode") or data.get("statusCode") or ""
    hints = {
        "riskPassword": "password too weak — choose a stronger admin password",
        "lowScoreFacePic": "face photo quality too low — use a clearer frontal JPEG ≥ 640×480",
        "noFacePic": "no face detected in photo — use a clear frontal face crop",
        "faceExist": "face already exists — retry (app now deletes old face first)",
        "deviceBusy": "device busy — wait and retry",
        "invalidOperation": "invalid face operation on device",
    }
    sub_s = str(sub)
    hint = hints.get(sub_s, "")
    parts = [p for p in (str(status).strip(), sub_s, hint) if p]
    return " — ".join(parts) if parts else ""


def probe_devices(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Probe each enabled device; return per-device result dicts."""
    poll = cfg.get("poll") or {}
    timeout = int(poll.get("timeout_seconds") or 20)
    results: list[dict[str, Any]] = []
    for dev in cfg["devices"]:
        name = str(dev.get("name") or "?")
        ip = str(dev.get("ip") or "?")
        base = device_base(dev)
        item: dict[str, Any] = {
            "name": name,
            "ip": ip,
            "url": base,
            "ok": False,
            "reason": "",
            "detail": "",
            "info": "",
        }
        try:
            hik = HikTerminal(dev, timeout=timeout)
            info = hik.probe()
            item["ok"] = True
            item["reason"] = "success"
            item["info"] = info
            item["detail"] = f"Connected OK — {info}"
            LOG.info("OK %s %s -> %s", name, base, info)
        except Exception as exc:
            code, detail = classify_device_error(exc)
            item["reason"] = code
            item["detail"] = detail
            LOG.error("FAIL %s %s [%s]: %s", name, ip, code, detail)
        results.append(item)
    return results


def probe_all(cfg: dict[str, Any]) -> int:
    results = probe_devices(cfg)
    for r in results:
        if r["ok"]:
            _console_print(f"SUCCESS  {r['name']} ({r['ip']}): {r['detail']}")
        else:
            _console_print(f"FAILED   {r['name']} ({r['ip']}): {r['detail']}")
    failed = sum(1 for r in results if not r["ok"])
    if failed:
        _console_print(f"Result: FAILED — {failed} of {len(results)} device(s) failed.")
    else:
        _console_print(f"Result: SUCCESS — all {len(results)} device(s) OK.")
    return failed


def _console_print(msg: str) -> None:
    """Print only when an interactive console exists (never under Task Scheduler/pythonw)."""
    LOG.info("%s", msg)
    if sys.stdout is not None and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        print(msg)


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Hikvision → atteninfo collector for Keka")
    parser.add_argument("--config", default=str(APPSETTINGS), help="Bootstrap appsettings.json path")
    parser.add_argument("--probe", action="store_true", help="Ping terminals and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print events, do not write SQL")
    parser.add_argument(
        "--since-hours",
        type=int,
        default=None,
        help="Ignore watermark and pull this many hours (still de-dupes in SQL)",
    )
    args = parser.parse_args()
    try:
        cfg = load_runtime_config(Path(args.config))
    except Exception as exc:
        LOG.error("%s", exc)
        return 2
    if not cfg["devices"]:
        LOG.error("No enabled devices in dbo.DeviceConfig")
        return 2
    if args.probe:
        return 1 if probe_all(cfg) else 0
    if not is_collector_enabled(cfg) and not args.dry_run:
        LOG.info(
            "Collector disabled (CollectorEnabled=0) — skipping punch write. "
            "Enable in Peak Energy Biometrics UI when ready."
        )
        _console_print("Collector disabled — no punches written.")
        return 0
    ignore_watermark = False
    if args.since_hours:
        cfg.setdefault("poll", {})
        cfg["poll"]["first_lookback_hours"] = args.since_hours
        ignore_watermark = True
        LOG.info("Ignoring watermark; pulling last %s hour(s)", args.since_hours)

    results = collect_all(cfg, dry_run=args.dry_run, ignore_watermark=ignore_watermark)
    failed = 0
    for r in results:
        if r["ok"]:
            _console_print(f"SUCCESS  {r['name']} ({r['ip']}): {r['detail']}")
        else:
            failed += 1
            reason = {
                "connectivity": "Connectivity",
                "password": "Wrong password / auth",
                "http": "HTTP error",
                "other": "Error",
            }.get(str(r["reason"]), str(r["reason"]))
            _console_print(f"FAILED   {r['name']} ({r['ip']}): [{reason}] {r['detail']}")
    if failed:
        _console_print(f"Result: FAILED — {failed} of {len(results)} device(s) failed.")
        return 1
    _console_print(f"Result: SUCCESS — all {len(results)} device(s) OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
