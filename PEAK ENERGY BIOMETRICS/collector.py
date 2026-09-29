#!/usr/bin/env python3
"""Pull attendance events from Hikvision terminals into atteninfo for Keka."""

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

from paths import app_dir, resource_dir

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = app_dir()
BUNDLE = resource_dir()
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
        self._device_serial = serial[:50]
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


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def split_name(full: str) -> tuple[str | None, str | None]:
    parts = full.strip().split(None, 1)
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0][:50], None
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
    first, last = split_name(person) if person else (None, None)
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
        # Prefer face-style type string used by the existing collector when mode is face
        verify = str(raw.get("currentVerifyMode") or raw.get("type") or "").strip()
        if not verify or "face" in verify.lower():
            auth_type = "ACSEventFaceVerifyPass"
        else:
            auth_type = verify[:50]
        card_no = str(raw.get("cardNo") or "").strip()
        reader = str(
            raw.get("cardReaderName")
            or raw.get("readerName")
            or raw.get("doorName")
            or "Cardreader 01"
        ).strip() or "Cardreader 01"
        device_no = str(
            dev.get("device_serial")
            or raw.get("serialNumber")
            or raw.get("deviceSerialNo")
            or ""
        ).strip()
    else:
        direction = direction_ui[:50]
        dt_s = punch.strftime("%Y-%m-%d %H:%M:%S")
        date_s = punch.strftime("%Y-%m-%d")
        auth_result = auth_result_label(minor)[:50]
        auth_type = (str(raw.get("currentVerifyMode") or "")[:50] or None)
        card_no = str(raw.get("cardNo") or "").strip()
        reader = None
        device_no = None
    return {
        "ID": emp[:50],
        "datetime": dt_s,
        "date": date_s,
        "time": punch.strftime("%H:%M:%S"),
        "authenticationresult": auth_result,
        "authenticationtype": auth_type,
        "device": device_label,
        "deviceno": (device_no[:50] if device_no else None),
        "readername": (reader[:50] if reader else None),
        "firstname": first,
        "lastname": last,
        "personname": (person[:50] if person else None),
        "persongroup": None,
        "cardno": (card_no[:50] if card_no else None),
        "direction": direction[:50],
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
) -> pyodbc.Connection:
    drivers = [sql.get("driver") or "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]
    installed = {d for d in pyodbc.drivers()}
    db = database if database is not None else sql["database"]
    last_err: Exception | None = None
    for driver in drivers:
        if driver not in installed and installed:
            continue
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


def punch_table_name(sql: dict[str, Any]) -> str:
    """Punch/events table used by the collector (AccessEvents or legacy atteninfo)."""
    name = str(sql.get("punch_table") or "").strip()
    if not name:
        # Existing Peak ACS installs keep punches in master.dbo.atteninfo
        if str(sql.get("database") or "").strip().lower() == "master":
            name = "atteninfo"
        else:
            name = "AccessEvents"
    if not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"Invalid punch table name: {name}")
    return name


def uses_legacy_atteninfo(sql: dict[str, Any]) -> bool:
    return punch_table_name(sql).lower() == "atteninfo"


def ensure_atteninfo_database(sql: dict[str, Any]) -> list[str]:
    """Create target database (unless system DB) + app tables. Returns status messages."""
    db_name = (sql.get("database") or "atteninfo").strip() or "atteninfo"
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
            # Legacy master.dbo.atteninfo — leave existing table/data untouched
            cur.execute("SELECT OBJECT_ID(N'dbo.atteninfo', N'U')")
            if cur.fetchone()[0] is None:
                raise RuntimeError(
                    "Configured punch table dbo.atteninfo was not found in this database.\n"
                    "Create it first, or set Database=atteninfo and Punch table=AccessEvents."
                )
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
                        ('entry', N'Entry Reader', '10.80.100.11', 80, N'admin', N'CHANGE_ME', 'In',  0, 1),
                        ('exit',  N'Exit Reader',  '10.80.100.12', 80, N'admin', N'CHANGE_ME', 'Out', 0, 1);
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
    if "CollectorEnabled" in app_cfg:
        enabled = str(app_cfg.get("CollectorEnabled") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    elif "collector_enabled" in boot:
        enabled = bool(boot.get("collector_enabled"))
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
    punch_table: str = "AccessEvents",
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                    row["ID"],
                    row["datetime"],
                    row["date"],
                    row["time"],
                    row["authenticationresult"],
                    row["authenticationtype"],
                    row["device"],
                    row.get("deviceno"),
                    row.get("readername"),
                    row["firstname"],
                    row["lastname"],
                    row["personname"],
                    row["persongroup"],
                    row.get("cardno"),
                    row["direction"],
                )
            else:
                cur.execute(
                    sql,
                    row["ID"],
                    row["datetime"],
                    row["date"],
                    row["time"],
                    row["authenticationresult"],
                    row["authenticationtype"],
                    row["device"],
                    row["firstname"],
                    row["lastname"],
                    row["personname"],
                    row["persongroup"],
                    row["direction"],
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
