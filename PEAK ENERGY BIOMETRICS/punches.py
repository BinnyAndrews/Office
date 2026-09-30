#!/usr/bin/env python3
"""Read punches from SQL (legacy atteninfo or AccessEvents) for the UI."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any

import collector as col


def day_window(today: date | None = None) -> tuple[date, date]:
    """Selectable range: today back 2 years (inclusive)."""
    end = today or date.today()
    try:
        start = end.replace(year=end.year - 2)
    except ValueError:
        start = end.replace(year=end.year - 2, day=28)
    return start, end


def direction_label(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"1", "In", "in", "IN", "Entry", "entry"}:
        return "Entry"
    if text in {"2", "Out", "out", "OUT", "Exit", "exit"}:
        return "Exit"
    return text or "—"


def _punch_columns(legacy: bool) -> str:
    if legacy:
        return """
            ID, [datetime], [date], [time], direction, device,
            personname, firstname, lastname, cardno, readername, deviceno,
            authenticationtype
        """
    return """
        ID, [datetime], [date], [time], direction, device,
        personname, firstname, lastname, authenticationtype, DeviceIP
    """


def _hydrate_punch(cols: list[str], raw: Any) -> dict[str, Any]:
    item = {cols[i]: raw[i] for i in range(len(cols))}
    item["direction_label"] = direction_label(item.get("direction"))
    name = str(item.get("personname") or "").strip()
    if not name:
        parts = [str(item.get("firstname") or "").strip(), str(item.get("lastname") or "").strip()]
        name = " ".join(p for p in parts if p)
    item["display_name"] = name or "—"
    return item


def fetch_punches_for_day(sql: dict[str, Any], day: date, *, limit: int = 10000) -> list[dict[str, Any]]:
    """Load punches for one calendar day from the configured punch table."""
    table = col.punch_table_name(sql)
    legacy = col.uses_legacy_atteninfo(sql)
    dmy = day.strftime("%d-%m-%Y")
    ymd = day.strftime("%Y-%m-%d")
    lim = max(1, min(int(limit), 50000))

    query = f"""
        SELECT TOP ({lim})
            {_punch_columns(legacy)}
        FROM dbo.[{table}]
        WHERE [date] IN (?, ?)
           OR LEFT(REPLACE(CONVERT(varchar(32), [datetime]), 'T', ' '), 10) = ?
        ORDER BY [time], ID
    """

    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        cur.execute(query, dmy, ymd, ymd)
        cols = [d[0] for d in cur.description]
        return [_hydrate_punch(cols, raw) for raw in cur.fetchall()]
    finally:
        conn.close()


def shift_day(day: date, delta_days: int, *, mindate: date, maxdate: date) -> date:
    nxt = day + timedelta(days=delta_days)
    if nxt < mindate:
        return mindate
    if nxt > maxdate:
        return maxdate
    return nxt


def format_punch_date(row: dict[str, Any]) -> str:
    """Normalize punch date to yyyy-mm-dd for display."""
    raw = str(row.get("date") or "").strip()
    if raw:
        # Legacy atteninfo: dd-mm-YYYY
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw[:10], fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return raw[:10]
    dt = str(row.get("datetime") or "").strip().replace("T", " ")
    if len(dt) >= 10:
        chunk = dt[:10]
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(chunk, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return chunk
    return "—"


def format_punch_time(row: dict[str, Any]) -> str:
    t = str(row.get("time") or "").strip()
    if t:
        return t[:8]
    dt = str(row.get("datetime") or "").strip().replace("T", " ")
    if len(dt) >= 19:
        return dt[11:19]
    return dt or "—"


_DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
)


def parse_punch_datetime(row: dict[str, Any]) -> datetime | None:
    """Best-effort punch timestamp from date + time, or the datetime column."""
    date_raw = str(row.get("date") or "").strip()
    time_raw = str(row.get("time") or "").strip()
    dt_raw = str(row.get("datetime") or "").strip().replace("T", " ")
    candidates: list[str] = []
    if date_raw and time_raw:
        candidates.append(f"{date_raw} {time_raw}")
    if dt_raw:
        candidates.append(dt_raw)
    if date_raw:
        candidates.append(date_raw)
    for text in candidates:
        chunk = text.strip()
        if "." in chunk:
            chunk = chunk.split(".", 1)[0].strip()
        for fmt in _DT_FORMATS:
            try:
                return datetime.strptime(chunk, fmt)
            except ValueError:
                continue
    return None


def format_duration(seconds: int) -> str:
    """Hours and minutes, with hours allowed to exceed 24 (monthly totals)."""
    total = max(0, int(seconds)) // 60
    hours, minutes = divmod(total, 60)
    return f"{hours}:{minutes:02d}"


def shift_month(
    year: int,
    month: int,
    delta: int,
    *,
    mindate: date,
    maxdate: date,
) -> tuple[int, int]:
    """Move by whole months and clamp to the inclusive month of mindate..maxdate."""
    index = year * 12 + (month - 1) + delta
    y, m = divmod(index, 12)
    start = date(y, m + 1, 1)
    min_start = date(mindate.year, mindate.month, 1)
    max_start = date(maxdate.year, maxdate.month, 1)
    if start < min_start:
        return min_start.year, min_start.month
    if start > max_start:
        return max_start.year, max_start.month
    return start.year, start.month


def fetch_punches_for_month(sql: dict[str, Any], year: int, month: int) -> list[dict[str, Any]]:
    """Load punches whose date text or datetime falls in the given calendar month.

    Rows are filtered again in Python, because atteninfo stores dates as text
    in more than one pattern (yyyy-mm-dd and dd-mm-yyyy).
    """
    table = col.punch_table_name(sql)
    legacy = col.uses_legacy_atteninfo(sql)
    ymd_prefix = f"{year:04d}-{month:02d}-%"
    dmy_suffix = f"%-{month:02d}-{year:04d}"
    slash_suffix = f"%/{month:02d}/{year:04d}"
    iso_month = f"{year:04d}-{month:02d}"

    query = f"""
        SELECT
            {_punch_columns(legacy)}
        FROM dbo.[{table}]
        WHERE [date] LIKE ?
           OR [date] LIKE ?
           OR [date] LIKE ?
           OR LEFT(REPLACE(CONVERT(varchar(32), [datetime]), 'T', ' '), 7) = ?
           OR [datetime] LIKE ?
           OR [datetime] LIKE ?
    """

    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        cur.execute(
            query,
            ymd_prefix,
            dmy_suffix,
            slash_suffix,
            iso_month,
            dmy_suffix,
            slash_suffix,
        )
        cols = [d[0] for d in cur.description]
        return [_hydrate_punch(cols, raw) for raw in cur.fetchall()]
    finally:
        conn.close()


def fetch_employee_names(sql: dict[str, Any]) -> dict[str, str]:
    """EmployeeNo → display name. Empty when dbo.Employees is not present."""
    conn = col.connect_sql(sql)
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT EmployeeNo, Name, FirstName, LastName
                FROM dbo.Employees
                """
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "employees" in msg or "invalid object" in msg or "42s02" in msg:
                return {}
            raise
        names: dict[str, str] = {}
        for raw in cur.fetchall():
            emp_no = str(raw[0] or "").strip()
            if not emp_no:
                continue
            full = str(raw[1] or "").strip()
            if not full:
                parts = [str(raw[2] or "").strip(), str(raw[3] or "").strip()]
                full = " ".join(p for p in parts if p)
            if full:
                names[emp_no] = full
        return names
    finally:
        conn.close()


def _event_kind(row: dict[str, Any]) -> str | None:
    label = str(row.get("direction_label") or direction_label(row.get("direction")))
    if label == "Entry":
        return "entry"
    if label == "Exit":
        return "exit"
    return None


def summarize_day(events: list[tuple[datetime, str]]) -> dict[str, Any]:
    """Same-day Entry/Exit pairing.

    Worked time is each Entry until the next Exit. Break is each Exit until the
    next Entry. An Entry still open at the end of the day is incomplete and is
    not added to worked time. A second Entry while already inside, or a second
    Exit while already outside, is ignored.
    """
    ordered = sorted(events, key=lambda item: (item[0], 0 if item[1] == "entry" else 1))
    worked = 0
    brk = 0
    inside = False
    open_entry: datetime | None = None
    last_exit: datetime | None = None
    for ts, kind in ordered:
        if kind == "entry":
            if inside:
                continue
            if last_exit is not None and ts >= last_exit:
                brk += int((ts - last_exit).total_seconds())
            inside = True
            open_entry = ts
            continue
        if not inside or open_entry is None:
            continue
        if ts >= open_entry:
            worked += int((ts - open_entry).total_seconds())
        inside = False
        open_entry = None
        last_exit = ts
    return {
        "worked_seconds": worked,
        "break_seconds": brk,
        "incomplete": inside,
        "present": bool(ordered),
    }


def _employee_summary_from_groups(
    grouped: dict[tuple[str, date], list[tuple[datetime, str]]],
    names: dict[str, str],
    punch_names: dict[str, str],
) -> list[dict[str, Any]]:
    by_emp: dict[str, dict[str, Any]] = {}
    for (emp, day), events in grouped.items():
        day_sum = summarize_day(events)
        rec = by_emp.get(emp)
        if rec is None:
            rec = {
                "employee_no": emp,
                "name": names.get(emp) or punch_names.get(emp) or "—",
                "days_present": 0,
                "worked_seconds": 0,
                "break_seconds": 0,
                "incomplete_days": 0,
                "days": [],
            }
            by_emp[emp] = rec
        note = "Missing exit" if day_sum["incomplete"] else ""
        rec["days"].append(
            {
                "date": day,
                "worked_seconds": day_sum["worked_seconds"],
                "break_seconds": day_sum["break_seconds"],
                "incomplete": day_sum["incomplete"],
                "note": note,
                "worked_label": format_duration(day_sum["worked_seconds"]),
                "break_label": format_duration(day_sum["break_seconds"]),
            }
        )
        if day_sum["present"]:
            rec["days_present"] += 1
        rec["worked_seconds"] += day_sum["worked_seconds"]
        rec["break_seconds"] += day_sum["break_seconds"]
        if day_sum["incomplete"]:
            rec["incomplete_days"] += 1

    result: list[dict[str, Any]] = []
    for rec in by_emp.values():
        rec["days"].sort(key=lambda item: item["date"])
        rec["worked_label"] = format_duration(rec["worked_seconds"])
        rec["break_label"] = format_duration(rec["break_seconds"])
        if not rec["name"] or rec["name"] == "—":
            rec["name"] = names.get(rec["employee_no"]) or punch_names.get(rec["employee_no"]) or "—"
        result.append(rec)
    result.sort(key=lambda item: str(item["employee_no"]).lower())
    return result


def summarize_month(
    rows: list[dict[str, Any]],
    names: dict[str, str],
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    """One record per employee for the month, each with a per-day breakdown."""
    grouped: dict[tuple[str, date], list[tuple[datetime, str]]] = {}
    punch_names: dict[str, str] = {}
    for row in rows:
        emp = str(row.get("ID") or "").strip()
        if not emp:
            continue
        kind = _event_kind(row)
        if kind is None:
            continue
        ts = parse_punch_datetime(row)
        if ts is None or ts.year != year or ts.month != month:
            continue
        grouped.setdefault((emp, ts.date()), []).append((ts, kind))
        pname = str(row.get("display_name") or "").strip()
        if pname and pname != "—" and emp not in punch_names:
            punch_names[emp] = pname
    return _employee_summary_from_groups(grouped, names, punch_names)


def summarize_day_employees(
    rows: list[dict[str, Any]],
    names: dict[str, str],
    day: date,
) -> list[dict[str, Any]]:
    """One record per employee for a single calendar day."""
    grouped: dict[tuple[str, date], list[tuple[datetime, str]]] = {}
    punch_names: dict[str, str] = {}
    for row in rows:
        emp = str(row.get("ID") or "").strip()
        if not emp:
            continue
        kind = _event_kind(row)
        if kind is None:
            continue
        ts = parse_punch_datetime(row)
        if ts is None or ts.date() != day:
            continue
        grouped.setdefault((emp, day), []).append((ts, kind))
        pname = str(row.get("display_name") or "").strip()
        if pname and pname != "—" and emp not in punch_names:
            punch_names[emp] = pname
    return _employee_summary_from_groups(grouped, names, punch_names)


def load_month_summary(sql: dict[str, Any], year: int, month: int) -> list[dict[str, Any]]:
    """Punches for the month, named from dbo.Employees when that person exists."""
    rows = fetch_punches_for_month(sql, year, month)
    names = fetch_employee_names(sql)
    return summarize_month(rows, names, year, month)


def load_day_summary(sql: dict[str, Any], day: date) -> list[dict[str, Any]]:
    """Punches for one day, named from dbo.Employees when that person exists."""
    rows = fetch_punches_for_day(sql, day)
    names = fetch_employee_names(sql)
    return summarize_day_employees(rows, names, day)


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"
