#!/usr/bin/env python3
"""Employee master (SQL) + Hikvision UserInfo / face sync for Peak Energy Biometrics."""

from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime
from typing import Any

import pyodbc
import requests

import collector as col

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

LOG = logging.getLogger("peak_attendance.employees")

# Default Hikvision validity window (local time strings)
DEFAULT_BEGIN = "2020-01-01T00:00:00"
DEFAULT_END = "2037-12-31T23:59:59"

# Face photo limits (Hikvision ISAPI / face terminal guidance)
FACE_MAX_BYTES = 200 * 1024  # hard max 200 KB
FACE_MIN_BYTES_SOFT = 60 * 1024  # soft warn below 60 KB
FACE_MIN_SIDE = 80  # ISAPI minimum
FACE_REC_W, FACE_REC_H = 640, 480  # recommended
FACE_MAX_W, FACE_MAX_H = 1920, 1080  # cap before compress
FACE_LIMITS_HINT = (
    "JPEG · max 200 KB · recommended ≥ 640×480 "
    "(auto-resized/compressed on load if needed)"
)


class FacePhotoError(ValueError):
    """Hard failure validating or compressing a face photo."""


def prepare_face_photo(data: bytes) -> tuple[bytes, str, list[str]]:
    """Validate and auto-resize/compress to a Hikvision-friendly JPEG.

    Returns ``(jpeg_bytes, summary, soft_warnings)``.
    Raises ``FacePhotoError`` when the image cannot meet hard limits.
    """
    if not data:
        raise FacePhotoError("No photo data.")
    if Image is None:
        raise FacePhotoError("Pillow is required to process face photos.")

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise FacePhotoError(
            "Could not read image. Use a JPEG (.jpg / .jpeg) face photo."
        ) from exc

    fmt = (img.format or "").upper()
    # Accept common formats; always output JPEG for the device.
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    if w < FACE_MIN_SIDE or h < FACE_MIN_SIDE:
        raise FacePhotoError(
            f"Photo resolution is {w}×{h}. Minimum is {FACE_MIN_SIDE}×{FACE_MIN_SIDE}."
        )

    notes: list[str] = []
    soft: list[str] = []
    original_kb = len(data) / 1024.0

    if w > FACE_MAX_W or h > FACE_MAX_H:
        img.thumbnail((FACE_MAX_W, FACE_MAX_H), Image.Resampling.LANCZOS)
        w, h = img.size
        notes.append(f"resized to {w}×{h} (max {FACE_MAX_W}×{FACE_MAX_H})")

    def _encode(im: Image.Image, quality: int) -> bytes:
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    # Prefer keeping original JPEG bytes if already valid and under the cap.
    if (
        fmt in ("JPEG", "JPG")
        and len(data) <= FACE_MAX_BYTES
        and w <= FACE_MAX_W
        and h <= FACE_MAX_H
        and not notes
    ):
        jpeg = data
    else:
        jpeg = _encode(img, 85)

    quality = 85
    scale_passes = 0
    while len(jpeg) > FACE_MAX_BYTES:
        if quality > 40:
            quality -= 10
            jpeg = _encode(img, quality)
            continue
        # Scale down further while staying above ISAPI minimum.
        nw = max(FACE_MIN_SIDE, int(img.width * 0.85))
        nh = max(FACE_MIN_SIDE, int(img.height * 0.85))
        if nw == img.width and nh == img.height:
            break
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        quality = 75
        jpeg = _encode(img, quality)
        scale_passes += 1
        if scale_passes > 12:
            break

    if len(jpeg) > FACE_MAX_BYTES:
        raise FacePhotoError(
            f"Photo is too large ({len(jpeg) / 1024:.0f} KB) even after compress. "
            f"Maximum is {FACE_MAX_BYTES // 1024} KB. Use a simpler/closer face crop."
        )

    w, h = img.size
    if w < FACE_MIN_SIDE or h < FACE_MIN_SIDE:
        raise FacePhotoError(
            f"Photo resolution became {w}×{h} after compress. "
            f"Minimum is {FACE_MIN_SIDE}×{FACE_MIN_SIDE}."
        )

    if quality < 85 or scale_passes or notes:
        notes.append(f"compressed to {len(jpeg) / 1024:.0f} KB (was {original_kb:.0f} KB)")
    if w < FACE_REC_W or h < FACE_REC_H:
        soft.append(
            f"Resolution is {w}×{h}. Recommended is ≥ {FACE_REC_W}×{FACE_REC_H} "
            "for reliable face enrollment."
        )
    if len(jpeg) < FACE_MIN_BYTES_SOFT:
        soft.append(
            f"File is {len(jpeg) / 1024:.0f} KB. Hikvision often prefers "
            f"{FACE_MIN_BYTES_SOFT // 1024}–{FACE_MAX_BYTES // 1024} KB."
        )

    summary = "; ".join(notes) if notes else (
        f"OK — {w}×{h}, {len(jpeg) / 1024:.0f} KB JPEG"
    )
    return jpeg, summary, soft


def _timeout(cfg: dict[str, Any]) -> int:
    return int((cfg.get("poll") or {}).get("timeout_seconds") or 20)


def _devices(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return list(cfg.get("devices") or [])


def ensure_employee_tables(cur: pyodbc.Cursor) -> list[str]:
    """Create Employees + EmployeeDeviceSync if missing; add FirstName/LastName if needed."""
    notes: list[str] = []
    statements = [
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
    for label, sql_text in statements:
        cur.execute(sql_text)
        notes.append(f"OK: {label}")

    # Existing DBs: add columns without touching AccessEvents
    cur.execute(
        """
        IF OBJECT_ID(N'dbo.Employees', N'U') IS NOT NULL
           AND COL_LENGTH(N'dbo.Employees', N'FirstName') IS NULL
            ALTER TABLE dbo.Employees ADD FirstName NVARCHAR(64) NULL;
        """
    )
    cur.execute(
        """
        IF OBJECT_ID(N'dbo.Employees', N'U') IS NOT NULL
           AND COL_LENGTH(N'dbo.Employees', N'LastName') IS NULL
            ALTER TABLE dbo.Employees ADD LastName NVARCHAR(64) NULL;
        """
    )
    # Backfill from existing Name where first/last still empty
    cur.execute(
        """
        UPDATE dbo.Employees
        SET
            FirstName = CASE
                WHEN CHARINDEX(N' ', LTRIM(RTRIM(Name))) > 0
                    THEN LEFT(LTRIM(RTRIM(Name)), CHARINDEX(N' ', LTRIM(RTRIM(Name))) - 1)
                ELSE LTRIM(RTRIM(Name))
            END,
            LastName = CASE
                WHEN CHARINDEX(N' ', LTRIM(RTRIM(Name))) > 0
                    THEN LTRIM(SUBSTRING(
                        LTRIM(RTRIM(Name)),
                        CHARINDEX(N' ', LTRIM(RTRIM(Name))) + 1,
                        128
                    ))
                ELSE NULL
            END
        WHERE (FirstName IS NULL OR FirstName = N'')
          AND (LastName IS NULL OR LastName = N'')
          AND Name IS NOT NULL
          AND LTRIM(RTRIM(Name)) <> N'';
        """
    )
    notes.append("OK: Employees.FirstName/LastName")
    return notes


def split_person_name(full: str | None) -> tuple[str, str]:
    """Split a display name into (first, last). Last may be empty."""
    text = (full or "").strip()
    if not text:
        return "", ""
    parts = text.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def combine_person_name(first: str | None, last: str | None, fallback: str = "") -> str:
    """Build Hikvision/display Name from first + last."""
    combined = f"{(first or '').strip()} {(last or '').strip()}".strip()
    return combined or (fallback or "").strip()


def ensure_name_fields(emp: dict[str, Any]) -> dict[str, Any]:
    """Ensure FirstName, LastName, and Name are consistent on an employee dict."""
    first = str(emp.get("FirstName") or "").strip()
    last = str(emp.get("LastName") or "").strip()
    name = str(emp.get("Name") or "").strip()
    if not first and not last and name:
        first, last = split_person_name(name)
    name = combine_person_name(first, last, name)
    emp["FirstName"] = first or None
    emp["LastName"] = last or None
    emp["Name"] = name
    return emp


# --- Hikvision UserInfo / face -------------------------------------------------


def _parse_user_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    block = payload.get("UserInfoSearch") or payload
    users = block.get("UserInfo") or []
    if isinstance(users, dict):
        users = [users]
    return list(users)


def search_users(hik: col.HikTerminal, page_size: int = 30) -> list[dict[str, Any]]:
    """Paginate all UserInfo records from one device."""
    search_id = f"emp-{uuid.uuid4().hex[:12]}"
    position = 0
    out: list[dict[str, Any]] = []
    while True:
        body = {
            "UserInfoSearchCond": {
                "searchID": search_id,
                "searchResultPosition": position,
                "maxResults": page_size,
            }
        }
        resp = hik.request(
            "POST",
            "/ISAPI/AccessControl/UserInfo/Search?format=json",
            headers={"Content-Type": "application/json"},
            data=json.dumps(body),
        )
        payload = resp.json()
        block = payload.get("UserInfoSearch") or payload
        users = _parse_user_list(payload)
        out.extend(users)
        status = str(block.get("responseStatusStrg") or "").upper()
        got = int(block.get("numOfMatches") or len(users) or 0)
        if status in {"OK", "NO MATCH", "NO MATCHES", "NOMATCH"} or got == 0:
            break
        if status != "MORE":
            break
        position += got
    return out


def _parse_bool_flag(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on", "enable", "enabled"}:
        return True
    if text in {"false", "0", "no", "n", "off", "disable", "disabled"}:
        return False
    return default


def _user_access_enabled(raw: dict[str, Any]) -> bool:
    """Whether the person can access (Hikvision 'enabled').

    Devices expose this several ways:
    - ``Valid.enable`` false → disabled / validity off for access on many firmwares
    - ``userType`` = ``blackList`` → person disabled / denied (common UI disable)
    - top-level ``enable`` / ``enabled`` when present
    """
    user_type = str(raw.get("userType") or raw.get("UserType") or "").strip().lower()
    if user_type in {"blacklist", "black_list", "black-list"}:
        return False

    for key in ("enable", "enabled", "Enabled", "personEnable", "userEnable"):
        if key in raw and raw.get(key) is not None:
            return _parse_bool_flag(raw.get(key), default=True)

    valid = raw.get("Valid") or raw.get("valid") or {}
    if isinstance(valid, dict) and "enable" in valid:
        return _parse_bool_flag(valid.get("enable"), default=True)

    return True


def _normalize_user(raw: dict[str, Any], device_key: str) -> dict[str, Any]:
    emp = str(raw.get("employeeNo") or raw.get("employeeNoString") or "").strip()
    valid = raw.get("Valid") or {}
    begin = valid.get("beginTime") or raw.get("beginTime")
    end = valid.get("endTime") or raw.get("endTime")
    card = raw.get("cardNo") or raw.get("CardNo")
    if not card:
        cards = raw.get("Card") or raw.get("cardList") or []
        if isinstance(cards, dict):
            card = cards.get("cardNo")
        elif isinstance(cards, list) and cards:
            card = (cards[0] or {}).get("cardNo")
    full_name = str(raw.get("name") or emp or "").strip() or emp
    first, last = split_person_name(full_name)
    return {
        "EmployeeNo": emp,
        "Name": full_name,
        "FirstName": first or None,
        "LastName": last or None,
        "Gender": (str(raw.get("gender") or "").strip() or None),
        "UserType": (str(raw.get("userType") or "normal").strip() or "normal"),
        "CardNo": (str(card).strip() if card else None),
        "ValidEnabled": _user_access_enabled(raw),
        "ValidFrom": _parse_hik_dt(begin),
        "ValidTo": _parse_hik_dt(end),
        "device_key": device_key,
        "raw": raw,
    }


def _parse_hik_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text[:19], fmt[:19].replace("%z", "") if "T" in fmt else fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def _fmt_hik_dt(dt: datetime | None, default: str) -> str:
    if dt is None:
        return default
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def get_face_jpeg(hik: col.HikTerminal, employee_no: str) -> bytes | None:
    """Try to download face JPEG for an employee (best-effort)."""
    try:
        fdid = _resolve_fdid(hik)
        body = {
            "FaceInfoSearchCond": {
                "searchID": f"face-{uuid.uuid4().hex[:8]}",
                "searchResultPosition": 0,
                "maxResults": 5,
                "faceLibType": "blackFD",
                "FDID": fdid,
                "FPID": employee_no,
            }
        }
        # Some firmwares use FDSearch with different cond name
        for path, payload in (
            ("/ISAPI/Intelligent/FDLib/FDSearch?format=json", body),
            (
                "/ISAPI/Intelligent/FDLib/FDSearch?format=json",
                {
                    "SearchResultPosition": 0,
                    "MaxResults": 5,
                    "FaceLibType": "blackFD",
                    "FDID": fdid,
                    "FPID": employee_no,
                },
            ),
        ):
            try:
                resp = hik.request(
                    "POST",
                    path,
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(payload),
                )
                data = resp.json()
            except Exception:
                continue
            matches = (
                data.get("MatchList")
                or data.get("FaceInfoSearch")
                or data.get("FaceSearchResult")
                or {}
            )
            if isinstance(matches, dict):
                items = matches.get("MatchElement") or matches.get("FaceInfo") or matches.get("InfoList") or []
                if not items and matches.get("faceURL"):
                    items = [matches]
            else:
                items = matches
            if isinstance(items, dict):
                items = [items]
            for item in items or []:
                url = item.get("faceURL") or item.get("FaceURL") or item.get("picURL")
                if not url:
                    continue
                if str(url).startswith("http"):
                    r = hik.session.get(str(url), timeout=hik.timeout, verify=False)
                    if r.status_code == 200 and r.content:
                        return r.content
                else:
                    r = hik.request("GET", str(url) if str(url).startswith("/") else f"/{url}")
                    if r.content:
                        return r.content
    except Exception as exc:
        LOG.debug("%s: face fetch failed for %s: %s", hik.dev.get("ip"), employee_no, exc)
    return None


def _resolve_fdid(hik: col.HikTerminal) -> str:
    try:
        resp = hik.request("GET", "/ISAPI/Intelligent/FDLib?format=json")
        data = resp.json()
        libs = data.get("FaceLibList") or data.get("FDLibList") or data.get("FDLib") or []
        if isinstance(libs, dict):
            libs = libs.get("FDLib") or libs.get("FaceLib") or [libs]
        if isinstance(libs, list) and libs:
            first = libs[0]
            return str(first.get("FDID") or first.get("fdid") or "1")
    except Exception:
        pass
    return "1"


def create_user_on_device(hik: col.HikTerminal, emp: dict[str, Any]) -> None:
    body = {"UserInfo": _userinfo_payload(emp)}
    hik.request(
        "POST",
        "/ISAPI/AccessControl/UserInfo/Record?format=json",
        headers={"Content-Type": "application/json"},
        data=json.dumps(body),
    )


def modify_user_on_device(hik: col.HikTerminal, emp: dict[str, Any]) -> None:
    body = {"UserInfo": _userinfo_payload(emp)}
    hik.request(
        "PUT",
        "/ISAPI/AccessControl/UserInfo/Modify?format=json",
        headers={"Content-Type": "application/json"},
        data=json.dumps(body),
    )


def _userinfo_payload(emp: dict[str, Any]) -> dict[str, Any]:
    """Build UserInfo for create/modify — map Access enabled ↔ Valid.enable / userType."""
    enabled = bool(emp.get("ValidEnabled", True))
    user_type = str(emp.get("UserType") or "normal").strip() or "normal"
    # Re-enable: clear blacklist type so the person works again
    if enabled and user_type.lower() in {"blacklist", "black_list", "black-list"}:
        user_type = "normal"
    # Disable: keep blacklist if already set; otherwise Valid.enable=false is enough
    info: dict[str, Any] = {
        "employeeNo": emp["EmployeeNo"],
        "name": ensure_name_fields(dict(emp))["Name"],
        "userType": user_type,
        "Valid": {
            "enable": enabled,
            "beginTime": _fmt_hik_dt(emp.get("ValidFrom"), DEFAULT_BEGIN),
            "endTime": _fmt_hik_dt(emp.get("ValidTo"), DEFAULT_END),
            "timeType": "local",
        },
        "doorRight": "1",
        "RightPlan": [{"doorNo": 1, "planTemplateNo": "1"}],
    }
    if emp.get("Gender"):
        info["gender"] = emp["Gender"]
    return info


def delete_user_on_device(hik: col.HikTerminal, employee_no: str) -> None:
    body = {"UserInfoDelCond": {"EmployeeNoList": [{"employeeNo": employee_no}]}}
    hik.request(
        "PUT",
        "/ISAPI/AccessControl/UserInfo/Delete?format=json",
        headers={"Content-Type": "application/json"},
        data=json.dumps(body),
    )


def prepare_face_for_device(data: bytes) -> tuple[bytes, str, list[str]]:
    """Prepare face JPEG and gently boost undersized photos for Hikvision enroll."""
    jpeg, summary, soft = prepare_face_photo(data)
    if Image is None:
        return jpeg, summary, soft
    try:
        img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    except Exception:
        return jpeg, summary, soft

    w, h = img.size
    notes = [summary]
    # Upscale toward recommended size when too small (helps lowScoreFacePic)
    if w < FACE_REC_W or h < FACE_REC_H:
        scale = max(FACE_REC_W / max(w, 1), FACE_REC_H / max(h, 1))
        nw = min(FACE_MAX_W, max(FACE_REC_W, int(w * scale)))
        nh = min(FACE_MAX_H, max(FACE_REC_H, int(h * scale)))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        notes.append(f"upscaled to {nw}×{nh} for device enroll")
        soft = [s for s in soft if "Resolution" not in s]

    def _encode(quality: int) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    # Prefer a mid-range file size when still under soft minimum
    out = jpeg
    if len(out) < FACE_MIN_BYTES_SOFT or "upscaled" in ";".join(notes):
        for q in (90, 85, 80, 75, 70):
            candidate = _encode(q)
            if len(candidate) <= FACE_MAX_BYTES:
                out = candidate
            if FACE_MIN_BYTES_SOFT <= len(out) <= FACE_MAX_BYTES:
                break
        # If still tiny, pad quality won't help much; keep best effort
        if len(out) > FACE_MAX_BYTES:
            out = _encode(60)
        notes.append(f"device JPEG {len(out) / 1024:.0f} KB")
        soft = [s for s in soft if "File is" not in s]

    if len(out) > FACE_MAX_BYTES:
        raise FacePhotoError(
            f"Photo is too large ({len(out) / 1024:.0f} KB) after prepare. "
            f"Maximum is {FACE_MAX_BYTES // 1024} KB."
        )
    return out, "; ".join(notes), soft


def delete_face_on_device(hik: col.HikTerminal, employee_no: str) -> None:
    """Best-effort delete of existing face so re-enroll does not return HTTP 400."""
    fdid = _resolve_fdid(hik)
    attempts: list[tuple[str, dict[str, Any]]] = [
        (
            f"/ISAPI/Intelligent/FDLib/FDSearch/Delete?format=json&FDID={fdid}&faceLibType=blackFD",
            {"FaceInfoDelCond": {"faceLibType": "blackFD", "FDID": str(fdid), "FPID": employee_no}},
        ),
        (
            f"/ISAPI/Intelligent/FDLib/FDSearch/Delete?format=json&FDID={fdid}&faceLibType=blackFD",
            {"FPID": [employee_no]},
        ),
        (
            f"/ISAPI/Intelligent/FDLib/FDSearch/Delete?format=json&FDID={fdid}&faceLibType=normalFD",
            {"FaceInfoDelCond": {"faceLibType": "normalFD", "FDID": str(fdid), "FPID": employee_no}},
        ),
    ]
    for path, body in attempts:
        try:
            hik.request(
                "PUT",
                path,
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
            )
            return
        except Exception:
            continue


def _face_multipart(meta_json: bytes, jpeg: bytes, boundary: str) -> bytes:
    """Hikvision-strict multipart: FaceDataRecord then FaceImage (trailing ';' on names)."""
    crlf = b"\r\n"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="FaceDataRecord";\r\n'
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(meta_json)}\r\n"
        f"\r\n"
    ).encode("ascii") + meta_json + crlf
    mid = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="FaceImage";\r\n'
        f"Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg)}\r\n"
        f"\r\n"
    ).encode("ascii")
    tail = f"\r\n--{boundary}--\r\n".encode("ascii")
    return head + mid + jpeg + tail


def _http_substatus(exc: BaseException) -> str:
    resp = getattr(exc, "response", None)
    if resp is None:
        return ""
    try:
        data = resp.json()
    except Exception:
        return ""
    if isinstance(data, dict):
        return str(data.get("subStatusCode") or data.get("statusString") or "")
    return ""


def upload_face_on_device(hik: col.HikTerminal, employee_no: str, jpeg: bytes) -> None:
    """Multipart face enroll (Hikvision ACS). Prefer POST FaceDataRecord; avoid bad PUTs."""
    try:
        delete_face_on_device(hik, employee_no)
    except Exception as exc:
        LOG.debug("%s: face delete skipped for %s: %s", hik.dev.get("ip"), employee_no, exc)

    fdid = _resolve_fdid(hik)
    boundary = f"----PeakAttendance{uuid.uuid4().hex}"
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}

    # POST FaceDataRecord is the supported create path on most terminals.
    # PUT FaceDataRecord often returns methodNotAllowed — do not use it.
    attempts: list[tuple[str, str, str, dict[str, Any]]] = []
    for lib in ("blackFD", "normalFD"):
        meta = {
            "faceLibType": lib,
            "FDID": str(fdid),
            "FPID": str(employee_no),
        }
        attempts.append(
            (
                "POST",
                "/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json",
                lib,
                meta,
            )
        )
    # Modify / re-bind paths used by some firmwares after delete
    for lib in ("blackFD", "normalFD"):
        meta = {"faceLibType": lib, "FDID": str(fdid), "FPID": str(employee_no)}
        attempts.append(
            ("PUT", "/ISAPI/Intelligent/FDLib/FDSetUp/Modify?format=json", lib, meta)
        )
        attempts.append(
            ("PUT", "/ISAPI/Intelligent/FDLib/FDSetUp?format=json", lib, meta)
        )

    errors: list[str] = []
    for method, path, lib, meta in attempts:
        body = _face_multipart(json.dumps(meta).encode("utf-8"), jpeg, boundary)
        try:
            hik.request(method, path, headers=headers, data=body)
            LOG.info(
                "%s: face enrolled for %s via %s %s (%s)",
                hik.dev.get("ip"),
                employee_no,
                method,
                path.split("?")[0],
                lib,
            )
            return
        except Exception as exc:
            sub = _http_substatus(exc)
            # Skip further PUT FaceDataRecord-style noise; keep useful codes
            if sub.lower() in {"methodnotallowed", "notsupport", "notsupportapi"}:
                errors.append(f"{method} {lib}: {sub}")
                continue
            errors.append(f"{method} {lib}: {sub or exc}")
            # face already exists — delete again and retry POST once
            if "face" in sub.lower() and "exist" in sub.lower():
                try:
                    delete_face_on_device(hik, employee_no)
                    hik.request(
                        "POST",
                        "/ISAPI/Intelligent/FDLib/FaceDataRecord?format=json",
                        headers=headers,
                        data=_face_multipart(
                            json.dumps(
                                {
                                    "faceLibType": lib,
                                    "FDID": str(fdid),
                                    "FPID": str(employee_no),
                                }
                            ).encode("utf-8"),
                            jpeg,
                            boundary,
                        ),
                    )
                    return
                except Exception as retry_exc:
                    errors.append(f"retry: {_http_substatus(retry_exc) or retry_exc}")
            continue

    detail = "; ".join(errors[-4:]) if errors else "unknown"
    raise RuntimeError(f"Face enroll failed on device — {detail}")




def upsert_user_on_device(hik: col.HikTerminal, emp: dict[str, Any]) -> None:
    try:
        create_user_on_device(hik, emp)
    except Exception:
        modify_user_on_device(hik, emp)


# --- SQL ----------------------------------------------------------------------


def list_employees(sql: dict[str, Any]) -> list[dict[str, Any]]:
    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.EmployeeNo, e.Name, e.FirstName, e.LastName, e.Gender, e.UserType, e.CardNo,
                   e.ValidEnabled, e.ValidFrom, e.ValidTo, e.HasFace, e.Notes,
                   e.SourceDevices, e.UpdatedAt,
                   CASE WHEN e.FaceImage IS NULL THEN 0 ELSE 1 END AS HasImageBytes
            FROM dbo.Employees e
            ORDER BY e.EmployeeNo
            """
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for row in rows:
            cur.execute(
                """
                SELECT DeviceKey, Status, Error, LastSyncUtc
                FROM dbo.EmployeeDeviceSync WHERE EmployeeNo = ?
                """,
                row["EmployeeNo"],
            )
            sync = {s.DeviceKey: {"Status": s.Status, "Error": s.Error, "LastSyncUtc": s.LastSyncUtc} for s in cur.fetchall()}
            row["Sync"] = sync
        return rows
    finally:
        conn.close()


def get_employee(sql: dict[str, Any], employee_no: str) -> dict[str, Any] | None:
    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT EmployeeNo, Name, FirstName, LastName, Gender, UserType, CardNo, ValidEnabled,
                   ValidFrom, ValidTo, FaceImage, HasFace, Notes, SourceDevices, UpdatedAt
            FROM dbo.Employees WHERE EmployeeNo = ?
            """,
            employee_no,
        )
        r = cur.fetchone()
        if not r:
            return None
        cols = [c[0] for c in cur.description]
        return dict(zip(cols, r))
    finally:
        conn.close()


def save_employee_sql(sql: dict[str, Any], emp: dict[str, Any], face: bytes | None = None) -> None:
    """Upsert employee. face=None leaves image unchanged; face=b'' clears it."""
    emp = ensure_name_fields(dict(emp))
    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        no = emp["EmployeeNo"]
        name = emp["Name"]
        first = emp.get("FirstName")
        last = emp.get("LastName")
        gender = emp.get("Gender")
        user_type = emp.get("UserType") or "normal"
        card = emp.get("CardNo")
        valid_en = 1 if emp.get("ValidEnabled", True) else 0
        valid_from = emp.get("ValidFrom")
        valid_to = emp.get("ValidTo")
        notes = emp.get("Notes")
        sources = emp.get("SourceDevices")

        # Avoid CASE WHEN ? THEN ? for VARBINARY — SQL Server rejects varchar-typed NULLs.
        if face is None:
            cur.execute(
                """
                MERGE dbo.Employees AS t
                USING (SELECT ? AS EmployeeNo) AS s ON t.EmployeeNo = s.EmployeeNo
                WHEN MATCHED THEN UPDATE SET
                    Name=?, FirstName=?, LastName=?, Gender=?, UserType=?, CardNo=?, ValidEnabled=?,
                    ValidFrom=?, ValidTo=?, Notes=?,
                    SourceDevices=COALESCE(?, t.SourceDevices),
                    UpdatedAt=SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT
                    (EmployeeNo, Name, FirstName, LastName, Gender, UserType, CardNo, ValidEnabled,
                     ValidFrom, ValidTo, FaceImage, HasFace, Notes, SourceDevices)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?);
                """,
                no,
                name,
                first,
                last,
                gender,
                user_type,
                card,
                valid_en,
                valid_from,
                valid_to,
                notes,
                sources,
                no,
                name,
                first,
                last,
                gender,
                user_type,
                card,
                valid_en,
                valid_from,
                valid_to,
                notes,
                sources,
            )
        else:
            face_bin = pyodbc.Binary(face) if face else None
            has_face = 1 if face else 0
            cur.execute(
                """
                MERGE dbo.Employees AS t
                USING (SELECT ? AS EmployeeNo) AS s ON t.EmployeeNo = s.EmployeeNo
                WHEN MATCHED THEN UPDATE SET
                    Name=?, FirstName=?, LastName=?, Gender=?, UserType=?, CardNo=?, ValidEnabled=?,
                    ValidFrom=?, ValidTo=?, FaceImage=?, HasFace=?, Notes=?,
                    SourceDevices=COALESCE(?, t.SourceDevices),
                    UpdatedAt=SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT
                    (EmployeeNo, Name, FirstName, LastName, Gender, UserType, CardNo, ValidEnabled,
                     ValidFrom, ValidTo, FaceImage, HasFace, Notes, SourceDevices)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                no,
                name,
                first,
                last,
                gender,
                user_type,
                card,
                valid_en,
                valid_from,
                valid_to,
                face_bin,
                has_face,
                notes,
                sources,
                no,
                name,
                first,
                last,
                gender,
                user_type,
                card,
                valid_en,
                valid_from,
                valid_to,
                face_bin,
                has_face,
                notes,
                sources,
            )
        conn.commit()
    finally:
        conn.close()


def delete_employee_sql(sql: dict[str, Any], employee_no: str) -> None:
    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM dbo.Employees WHERE EmployeeNo = ?", employee_no)
        conn.commit()
    finally:
        conn.close()


def set_sync_status(
    sql: dict[str, Any],
    employee_no: str,
    device_key: str,
    status: str,
    error: str | None = None,
) -> None:
    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            MERGE dbo.EmployeeDeviceSync AS t
            USING (SELECT ? AS EmployeeNo, ? AS DeviceKey) AS s
            ON t.EmployeeNo = s.EmployeeNo AND t.DeviceKey = s.DeviceKey
            WHEN MATCHED THEN UPDATE SET
                LastSyncUtc=SYSUTCDATETIME(), Status=?, Error=?
            WHEN NOT MATCHED THEN INSERT (EmployeeNo, DeviceKey, LastSyncUtc, Status, Error)
            VALUES (?, ?, SYSUTCDATETIME(), ?, ?);
            """,
            employee_no,
            device_key,
            status,
            (error or None)[:400] if error else None,
            employee_no,
            device_key,
            status,
            (error or None)[:400] if error else None,
        )
        conn.commit()
    finally:
        conn.close()


def _device_label(dev: dict[str, Any]) -> str:
    key = str(dev.get("name") or "?")
    label = str(dev.get("display_name") or key)
    ip = str(dev.get("ip") or "?")
    return f"{label} ({ip})"


def _friendly_device_error(dev: dict[str, Any], exc: BaseException) -> str:
    """Human-readable device error (no raw requests pool traceback)."""
    _code, detail = col.classify_device_error(exc)
    return f"{_device_label(dev)}: {detail}"


def _friendly_sql_error(exc: BaseException) -> str:
    msg = str(exc)
    low = msg.lower()
    if "varchar to varbinary" in low or "varbinary" in low:
        return "Could not save face photo to SQL (binary field). Try Pull again after update."
    if "login failed" in low:
        return "SQL login failed — check server username/password."
    if "foreign key" in low:
        return "SQL relationship error — employee row missing."
    # Keep short; strip long ODBC noise
    if len(msg) > 220:
        return msg[:220] + "…"
    return msg


# --- High-level sync ----------------------------------------------------------


def pull_from_devices(cfg: dict[str, Any]) -> dict[str, Any]:
    """Pull UserInfo (+ face best-effort) from all enabled devices; merge into SQL."""
    sql = cfg["sql"]
    devices = _devices(cfg)
    if not devices:
        raise RuntimeError("No enabled devices configured.")

    # Ensure tables exist
    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        ensure_employee_tables(cur)
        conn.commit()
    finally:
        conn.close()

    by_emp: dict[str, dict[str, Any]] = {}
    device_errors: list[str] = []
    faces: dict[str, bytes] = {}

    for dev in devices:
        key = str(dev.get("name") or "?")
        try:
            hik = col.HikTerminal(dev, timeout=_timeout(cfg))
            users = search_users(hik)
            LOG.info("%s: pulled %s user(s)", key, len(users))
            for raw in users:
                norm = _normalize_user(raw, key)
                emp_no = norm["EmployeeNo"]
                if not emp_no:
                    continue
                existing = by_emp.get(emp_no)
                if existing is None:
                    by_emp[emp_no] = norm
                    by_emp[emp_no]["_devices"] = {key}
                else:
                    existing["_devices"].add(key)
                    # Prefer non-empty fields from either side
                    for fld in ("Name", "FirstName", "LastName", "Gender", "UserType", "CardNo", "ValidFrom", "ValidTo"):
                        if not existing.get(fld) and norm.get(fld):
                            existing[fld] = norm[fld]
                    # Disabled on any device wins (do not OR-merge to True)
                    existing["ValidEnabled"] = bool(existing.get("ValidEnabled", True)) and bool(
                        norm.get("ValidEnabled", True)
                    )
                    # Prefer blackList if either side has it (device disable)
                    if str(norm.get("UserType") or "").lower() == "blacklist":
                        existing["UserType"] = norm["UserType"]
                    elif str(existing.get("UserType") or "").lower() != "blacklist" and norm.get(
                        "UserType"
                    ):
                        if not existing.get("UserType") or existing.get("UserType") == "normal":
                            existing["UserType"] = norm["UserType"]

                if emp_no not in faces:
                    jpeg = get_face_jpeg(hik, emp_no)
                    if jpeg:
                        faces[emp_no] = jpeg
        except Exception as exc:
            msg = _friendly_device_error(dev, exc)
            device_errors.append(msg)
            LOG.exception("Pull failed on %s", key)

    for emp_no, emp in by_emp.items():
        emp["SourceDevices"] = ",".join(sorted(emp.get("_devices") or []))
        try:
            save_employee_sql(sql, emp, face=faces.get(emp_no))
        except Exception as exc:
            LOG.exception("SQL save failed for %s", emp_no)
            device_errors.append(f"SQL save {emp_no}: {_friendly_sql_error(exc)}")
            continue
        for key in emp.get("_devices") or []:
            set_sync_status(sql, emp_no, key, "OK", None)

    # Mark employees missing on a device
    for emp_no, emp in by_emp.items():
        present = emp.get("_devices") or set()
        for dev in devices:
            key = str(dev.get("name") or "?")
            if key not in present:
                try:
                    set_sync_status(sql, emp_no, key, "Missing", "Not found on device during pull")
                except Exception:
                    pass

    return {
        "count": len(by_emp),
        "faces": len(faces),
        "errors": device_errors,
    }


def push_employee(cfg: dict[str, Any], employee_no: str) -> list[str]:
    """Create/update employee on all enabled devices (UserInfo + face if present)."""
    sql = cfg["sql"]
    emp = get_employee(sql, employee_no)
    if not emp:
        raise RuntimeError(f"Employee {employee_no} not found in SQL.")
    notes: list[str] = []
    for dev in _devices(cfg):
        key = str(dev.get("name") or "?")
        try:
            hik = col.HikTerminal(dev, timeout=_timeout(cfg))
            upsert_user_on_device(hik, emp)
            face = emp.get("FaceImage")
            if face:
                # Face enroll is unreliable while person is disabled / blackList
                user_type = str(emp.get("UserType") or "").lower()
                if not emp.get("ValidEnabled", True) or user_type in {
                    "blacklist",
                    "black_list",
                    "black-list",
                }:
                    notes.append(
                        f"{_device_label(dev)}: person saved; face skipped "
                        "(Access enabled is off or User type is blackList — enable access, then Save + Push again)"
                    )
                    set_sync_status(
                        sql,
                        employee_no,
                        key,
                        "Partial",
                        "Face skipped — person disabled/blackList",
                    )
                    continue
                try:
                    jpeg, _summary, _soft = prepare_face_for_device(bytes(face))
                    upload_face_on_device(hik, employee_no, jpeg)
                except FacePhotoError as face_exc:
                    notes.append(
                        f"{_device_label(dev)}: person saved, face rejected — {face_exc}"
                    )
                    set_sync_status(sql, employee_no, key, "Partial", str(face_exc)[:400])
                    continue
                except Exception as face_exc:
                    _c, detail = col.classify_device_error(face_exc)
                    notes.append(f"{_device_label(dev)}: person saved, face failed — {detail}")
                    set_sync_status(sql, employee_no, key, "Partial", detail[:400])
                    continue
            set_sync_status(sql, employee_no, key, "OK", None)
            notes.append(f"{_device_label(dev)}: OK")
        except Exception as exc:
            msg = _friendly_device_error(dev, exc)
            set_sync_status(sql, employee_no, key, "Error", msg[:400])
            notes.append(f"{msg}")
    return notes


def delete_employee_everywhere(cfg: dict[str, Any], employee_no: str) -> list[str]:
    """Delete from both devices, then from SQL."""
    sql = cfg["sql"]
    notes: list[str] = []
    for dev in _devices(cfg):
        try:
            hik = col.HikTerminal(dev, timeout=_timeout(cfg))
            delete_user_on_device(hik, employee_no)
            notes.append(f"{_device_label(dev)}: deleted on device")
        except Exception as exc:
            notes.append(_friendly_device_error(dev, exc))
    delete_employee_sql(sql, employee_no)
    notes.append("Removed from SQL database.")
    return notes
    delete_employee_sql(sql, employee_no)
    notes.append("SQL: deleted")
    return notes


def create_or_update_employee(
    cfg: dict[str, Any],
    emp: dict[str, Any],
    face: bytes | None = None,
    push: bool = True,
) -> list[str]:
    """Save to SQL, then push create/update to both devices."""
    notes: list[str] = []
    sql = cfg["sql"]
    conn = col.connect_sql(sql)
    try:
        ensure_employee_tables(conn.cursor())
        conn.commit()
    finally:
        conn.close()
    if face:
        face, summary, soft = prepare_face_photo(face)
        notes.append(f"Face photo: {summary}")
        notes.extend(f"Face note: {w}" for w in soft)
    save_employee_sql(sql, emp, face=face)
    if not push:
        notes.append("SQL: saved (no device push)")
        return notes
    notes.extend(push_employee(cfg, emp["EmployeeNo"]))
    return notes
