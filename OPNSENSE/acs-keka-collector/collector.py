#!/usr/bin/env python3
"""Pull attendance events from Hikvision DS-K1T terminals into MS-SQL for Keka.

Devices stay the terminals. This process only reads access events over the LAN
HTTP API and inserts rows Keka can map.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
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

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parent
FAIL_MINORS = {76}  # face auth failed — skip
LOG = logging.getLogger("acs-keka")


def setup_logging() -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_h = RotatingFileHandler(
        log_dir / "collector.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    stream_h = logging.StreamHandler(sys.stdout)
    stream_h.setFormatter(fmt)
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    LOG.addHandler(file_h)
    LOG.addHandler(stream_h)


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


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
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")


def device_base(dev: dict[str, Any]) -> str:
    scheme = "https" if dev.get("https") else "http"
    return f"{scheme}://{dev['ip']}:{int(dev.get('port') or 80)}"


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


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_event(raw: dict[str, Any], dev: dict[str, Any]) -> dict[str, Any] | None:
    emp = (
        str(raw.get("employeeNoString") or raw.get("employeeNo") or "")
        .strip()
    )
    if not emp:
        return None
    minor = as_int(raw.get("minor"))
    if minor in FAIL_MINORS:
        return None
    punch = parse_hik_time(str(raw.get("time") or ""))
    if punch is None:
        return None
    serial = as_int(raw.get("serialNo") or raw.get("serialNO"))
    return {
        "DeviceNumber": int(dev["device_number"]),
        "UserID": emp[:32],
        "LogTime": punch,
        "Status": int(dev["status"]),
        "DeviceIP": dev["ip"],
        "SerialNo": serial,
        "EmployeeName": (str(raw.get("name") or "")[:128] or None),
        "VerifyMode": (str(raw.get("currentVerifyMode") or "")[:64] or None),
        "MinorCode": minor,
    }


def connect_sql(cfg: dict[str, Any]) -> pyodbc.Connection:
    sql = cfg["sql"]
    drivers = [sql.get("driver") or "ODBC Driver 18 for SQL Server"]
    if "ODBC Driver 17 for SQL Server" not in drivers:
        drivers.append("ODBC Driver 17 for SQL Server")
    last_err: Exception | None = None
    installed = {d for d in pyodbc.drivers()}
    for driver in drivers:
        if driver not in installed and installed:
            continue
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={sql['server']};"
            f"DATABASE={sql['database']};"
            f"UID={sql['username']};"
            f"PWD={sql['password']};"
            "Encrypt=yes;TrustServerCertificate=yes;"
        )
        try:
            return pyodbc.connect(conn_str, timeout=10)
        except pyodbc.Error as exc:
            last_err = exc
    raise RuntimeError(
        f"SQL connect failed. Installed ODBC drivers: {sorted(installed)}. Last error: {last_err}"
    )


def load_watermark(cur: pyodbc.Cursor, device_ip: str) -> datetime | None:
    cur.execute(
        "SELECT LastEventTime FROM dbo.CollectorState WHERE DeviceIP = ?",
        device_ip,
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


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


def insert_rows(cur: pyodbc.Cursor, rows: list[dict[str, Any]]) -> int:
    inserted = 0
    sql = """
        INSERT INTO dbo.AttendanceLogs (
            DeviceNumber, UserID, LogTime, Status, DeviceIP, SerialNo,
            EmployeeName, VerifyMode, MinorCode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    for row in rows:
        try:
            cur.execute(
                sql,
                row["DeviceNumber"],
                row["UserID"],
                row["LogTime"],
                row["Status"],
                row["DeviceIP"],
                row["SerialNo"],
                row["EmployeeName"],
                row["VerifyMode"],
                row["MinorCode"],
            )
            inserted += 1
        except pyodbc.IntegrityError:
            continue
        except pyodbc.Error as exc:
            # 2627 / 2601 = unique index (already collected)
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
) -> None:
    poll = cfg.get("poll") or {}
    timeout = int(poll.get("timeout_seconds") or 20)
    max_results = int(poll.get("max_results") or 30)
    hik = HikTerminal(dev, timeout=timeout)
    cur = conn.cursor() if conn is not None else None
    start, end = window_for(dev, cur, poll, ignore_watermark=ignore_watermark)
    LOG.info(
        "%s (%s) searching %s → %s",
        dev.get("name"),
        dev["ip"],
        fmt_hik_time(start),
        fmt_hik_time(end),
    )
    try:
        raw_events = hik.search_events(start, end, max_results)
        rows = [r for r in (normalize_event(e, dev) for e in raw_events) if r]
        LOG.info("%s: %s device events, %s punches after filter", dev["ip"], len(raw_events), len(rows))
        if dry_run:
            for row in rows:
                LOG.info(
                    "DRY %s user=%s time=%s status=%s serial=%s",
                    row["DeviceIP"],
                    row["UserID"],
                    row["LogTime"],
                    row["Status"],
                    row["SerialNo"],
                )
            return
        assert cur is not None
        added = insert_rows(cur, rows)
        last_event = max((r["LogTime"] for r in rows), default=None)
        last_serial = None
        serials = [r["SerialNo"] for r in rows if r["SerialNo"] is not None]
        if serials:
            last_serial = max(serials)
        save_watermark(cur, dev["ip"], last_event, last_serial, None)
        conn.commit()
        LOG.info("%s: inserted %s new row(s)", dev["ip"], added)
    except Exception as exc:
        LOG.exception("%s: collect failed: %s", dev["ip"], exc)
        if cur is not None and conn is not None:
            try:
                save_watermark(cur, dev["ip"], None, None, str(exc)[:400])
                conn.commit()
            except Exception:
                conn.rollback()
        raise


def probe_all(cfg: dict[str, Any]) -> int:
    poll = cfg.get("poll") or {}
    timeout = int(poll.get("timeout_seconds") or 20)
    failures = 0
    for dev in cfg["devices"]:
        try:
            hik = HikTerminal(dev, timeout=timeout)
            info = hik.probe()
            LOG.info("OK %s %s → %s", dev.get("name"), device_base(dev), info)
        except Exception as exc:
            failures += 1
            LOG.error("FAIL %s %s: %s", dev.get("name"), dev["ip"], exc)
    return failures


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Hikvision terminal → SQL collector for Keka")
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    parser.add_argument("--probe", action="store_true", help="Ping both terminals and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print events, do not write SQL")
    parser.add_argument(
        "--since-hours",
        type=int,
        default=None,
        help="Ignore watermark and pull this many hours (still de-dupes in SQL)",
    )
    args = parser.parse_args()
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        example = ROOT / "config.example.json"
        LOG.error("Missing %s — copy %s to config.json and edit passwords", cfg_path, example)
        return 2
    cfg = load_config(cfg_path)
    if args.probe:
        return 1 if probe_all(cfg) else 0
    ignore_watermark = False
    if args.since_hours:
        cfg.setdefault("poll", {})
        cfg["poll"]["first_lookback_hours"] = args.since_hours
        ignore_watermark = True
        LOG.info("Ignoring watermark; pulling last %s hour(s)", args.since_hours)

    conn = None
    if not args.dry_run:
        conn = connect_sql(cfg)

    errors = 0
    for dev in cfg["devices"]:
        try:
            collect_device(
                cfg, dev, conn, dry_run=args.dry_run, ignore_watermark=ignore_watermark
            )
        except Exception:
            errors += 1
    if conn is not None:
        conn.close()
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
