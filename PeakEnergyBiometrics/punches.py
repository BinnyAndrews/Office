#!/usr/bin/env python3
"""Read punches from SQL (legacy atteninfo or AccessEvents) for the UI."""

from __future__ import annotations

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


def fetch_punches_for_day(sql: dict[str, Any], day: date, *, limit: int = 10000) -> list[dict[str, Any]]:
    """Load punches for one calendar day from the configured punch table."""
    table = col.punch_table_name(sql)
    legacy = col.uses_legacy_atteninfo(sql)
    dmy = day.strftime("%d-%m-%Y")
    ymd = day.strftime("%Y-%m-%d")
    lim = max(1, min(int(limit), 50000))

    if legacy:
        select_cols = """
            ID, [datetime], [date], [time], direction, device,
            personname, firstname, lastname, cardno, readername, deviceno,
            authenticationtype
        """
    else:
        select_cols = """
            ID, [datetime], [date], [time], direction, device,
            personname, firstname, lastname, authenticationtype, DeviceIP
        """

    query = f"""
        SELECT TOP ({lim})
            {select_cols}
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
        rows: list[dict[str, Any]] = []
        for raw in cur.fetchall():
            item = {cols[i]: raw[i] for i in range(len(cols))}
            item["direction_label"] = direction_label(item.get("direction"))
            name = str(item.get("personname") or "").strip()
            if not name:
                parts = [str(item.get("firstname") or "").strip(), str(item.get("lastname") or "").strip()]
                name = " ".join(p for p in parts if p)
            item["display_name"] = name or "—"
            rows.append(item)
        return rows
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
