#!/usr/bin/env python3
"""Copy Peak ACS tables between SQL Servers (e.g. 10.80.100.10 → localhost\\SQLEXPRESS)."""

from __future__ import annotations

from typing import Any, Callable

import collector as col

HELPER_TABLES = (
    "DeviceConfig",
    "AppConfig",
    "CollectorState",
    "Employees",
    "EmployeeDeviceSync",
)
# Keys we keep on the destination when copying AppConfig (local collector settings)
PRESERVE_APPCONFIG_KEYS = frozenset(
    {
        "CollectorEnabled",
        "SyncIntervalMinutes",
        "FirstLookbackHours",
        "TimeoutSeconds",
        "OverlapSeconds",
        "MaxResults",
    }
)
PUNCH_TABLE = "atteninfo"
BATCH = 500
ProgressFn = Callable[[str], None]


def sql_cfg(server: str, user: str, password: str) -> dict[str, Any]:
    return {
        "server": server,
        "database": "master",
        "punch_table": "atteninfo",
        "username": user,
        "password": password,
        "driver": "ODBC Driver 18 for SQL Server",
    }


def _quote_ident(name: str) -> str:
    if not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(f"Bad identifier: {name}")
    return f"[{name}]"


def _table_exists(cur: Any, table: str) -> bool:
    cur.execute("SELECT OBJECT_ID(?, N'U')", f"dbo.{table}")
    row = cur.fetchone()
    return row is not None and row[0] is not None


def _copy_table(src_cur: Any, dst_conn: Any, table: str, progress: ProgressFn | None) -> int:
    src_cur.execute(f"SELECT * FROM dbo.{_quote_ident(table)}")
    cols = [d[0] for d in src_cur.description]
    if not cols:
        return 0
    col_list = ", ".join(_quote_ident(c) for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    insert_sql = f"INSERT INTO dbo.{_quote_ident(table)} ({col_list}) VALUES ({placeholders})"

    dst_cur = dst_conn.cursor()
    if not _table_exists(dst_cur, table):
        raise RuntimeError(
            f"Destination table dbo.{table} is missing. "
            "Run Create / Repair database on the local Server first."
        )

    total = 0
    while True:
        rows = src_cur.fetchmany(BATCH)
        if not rows:
            break
        dst_cur.fast_executemany = True
        dst_cur.executemany(insert_sql, [tuple(r) for r in rows])
        total += len(rows)
        if progress:
            progress(f"{table}: {total} row(s)…")
    dst_conn.commit()
    return total


def _normalize_imported_cardno(dst_conn: Any) -> int:
    """Match old ACS cardno: drop face-event uint64 junk (NULL scrubbed separately)."""
    dst_cur = dst_conn.cursor()
    if not _table_exists(dst_cur, PUNCH_TABLE):
        return 0
    n = 0
    dst_cur.execute(
        f"""
        SELECT DISTINCT cardno FROM dbo.{_quote_ident(PUNCH_TABLE)}
        WHERE cardno IS NOT NULL AND LTRIM(RTRIM(cardno)) <> N''
        """
    )
    for (raw,) in dst_cur.fetchall():
        fixed = col.normalize_card_no(raw)
        if fixed != str(raw):
            dst_cur.execute(
                f"""
                UPDATE dbo.{_quote_ident(PUNCH_TABLE)}
                SET cardno = ?
                WHERE cardno = ?
                """,
                fixed,
                raw,
            )
            n += int(dst_cur.rowcount or 0)
    dst_conn.commit()
    return n


def _normalize_imported_deviceno(dst_conn: Any) -> tuple[int, int]:
    """Shorten long Hikvision product IDs to ACS-style serials; fill blanks by device."""
    dst_cur = dst_conn.cursor()
    if not _table_exists(dst_cur, PUNCH_TABLE):
        return 0, 0

    rewritten = 0
    dst_cur.execute(
        f"""
        SELECT DISTINCT deviceno FROM dbo.{_quote_ident(PUNCH_TABLE)}
        WHERE deviceno IS NOT NULL AND LTRIM(RTRIM(deviceno)) <> N''
        """
    )
    for (raw,) in dst_cur.fetchall():
        short = col.normalize_hik_device_serial(str(raw))
        if short and short != str(raw).strip():
            dst_cur.execute(
                f"""
                UPDATE dbo.{_quote_ident(PUNCH_TABLE)}
                SET deviceno = ?
                WHERE deviceno = ?
                """,
                short,
                raw,
            )
            rewritten += int(dst_cur.rowcount or 0)

    # Fill blank/null using the most common serial already present for that device label
    dst_cur.execute(
        f"""
        SELECT device, deviceno, COUNT(*) AS n
        FROM dbo.{_quote_ident(PUNCH_TABLE)}
        WHERE device IS NOT NULL
          AND deviceno IS NOT NULL AND LTRIM(RTRIM(deviceno)) <> N''
        GROUP BY device, deviceno
        ORDER BY device, n DESC
        """
    )
    best_by_device: dict[str, str] = {}
    for device, serial, _n in dst_cur.fetchall():
        key = str(device or "").strip()
        if key and key not in best_by_device:
            best_by_device[key] = col.normalize_hik_device_serial(str(serial)) or str(serial)

    filled = 0
    for device, serial in best_by_device.items():
        if not serial:
            continue
        dst_cur.execute(
            f"""
            UPDATE dbo.{_quote_ident(PUNCH_TABLE)}
            SET deviceno = ?
            WHERE device = ?
              AND (deviceno IS NULL OR LTRIM(RTRIM(deviceno)) = N'')
            """,
            serial[:50],
            device,
        )
        filled += int(dst_cur.rowcount or 0)

    dst_conn.commit()
    return rewritten, filled


def copy_acs_data(
    *,
    source_server: str,
    dest_server: str,
    username: str,
    password: str,
    include_helpers: bool = True,
    include_punches: bool = True,
    progress: ProgressFn | None = None,
) -> list[str]:
    """
    Replace selected tables on dest with a full copy from source.
    Both servers use database=master.
    """
    if not include_helpers and not include_punches:
        raise ValueError("Nothing selected to copy.")

    src_sql = sql_cfg(source_server, username, password)
    dst_sql = sql_cfg(dest_server, username, password)
    notes: list[str] = []

    if progress:
        progress("Ensuring destination tables exist…")
    notes.extend(col.ensure_atteninfo_database(dst_sql))

    tables: list[str] = []
    if include_helpers:
        tables.extend(HELPER_TABLES)
    if include_punches:
        tables.append(PUNCH_TABLE)

    clear_order = [
        "EmployeeDeviceSync",
        "Employees",
        "CollectorState",
        "AppConfig",
        "DeviceConfig",
        "atteninfo",
    ]

    src = col.connect_sql(src_sql, database="master", timeout=60)
    dst = col.connect_sql(dst_sql, database="master", timeout=60, autocommit=False)
    try:
        dst_cur = dst.cursor()
        preserved: dict[str, str] = {}
        if include_helpers and _table_exists(dst_cur, "AppConfig"):
            dst_cur.execute("SELECT ConfigKey, ConfigValue FROM dbo.AppConfig")
            for row in dst_cur.fetchall():
                key = str(row[0] or "")
                if key in PRESERVE_APPCONFIG_KEYS:
                    preserved[key] = str(row[1] if row[1] is not None else "")

        for t in clear_order:
            if t in tables and _table_exists(dst_cur, t):
                dst_cur.execute(f"DELETE FROM dbo.{_quote_ident(t)}")
        dst.commit()

        for table in tables:
            src_cur = src.cursor()
            if not _table_exists(src_cur, table):
                notes.append(f"SKIP {table} (not on source)")
                continue
            if progress:
                progress(f"Copying {table}…")
            src_cur = src.cursor()
            n = _copy_table(src_cur, dst, table, progress)
            notes.append(f"OK {table}: {n} row(s)")
            if table == PUNCH_TABLE and n > 0:
                if progress:
                    progress("Normalizing imported punches (no NULLs)…")
                rewritten, filled_serial = _normalize_imported_deviceno(dst)
                if rewritten:
                    notes.append(
                        f"Normalized deviceno to short serial on {rewritten} imported row(s)."
                    )
                if filled_serial:
                    notes.append(
                        f"Filled blank deviceno on {filled_serial} imported row(s) from device label."
                    )
                card_fixed = _normalize_imported_cardno(dst)
                if card_fixed:
                    notes.append(
                        f"Normalized cardno (NULL/junk → empty or badge) on {card_fixed} row(s)."
                    )
                scrubbed = col.scrub_atteninfo_nulls(dst)
                if scrubbed:
                    notes.append(
                        f"Replaced NULL varchar cells with empty/defaults ({scrubbed} update(s))."
                    )

        # Keep local collector on/off + intervals (ACS import must not disable the schedule)
        if preserved and _table_exists(dst.cursor(), "AppConfig"):
            dst_cur = dst.cursor()
            for key, value in preserved.items():
                dst_cur.execute(
                    """
                    MERGE dbo.AppConfig AS t
                    USING (SELECT ? AS ConfigKey) AS s
                    ON t.ConfigKey = s.ConfigKey
                    WHEN MATCHED THEN UPDATE SET ConfigValue=?, UpdatedAt=SYSUTCDATETIME()
                    WHEN NOT MATCHED THEN INSERT (ConfigKey, ConfigValue) VALUES (?, ?);
                    """,
                    key,
                    value,
                    key,
                    value,
                )
            dst.commit()
            notes.append(
                "Preserved local collector settings: " + ", ".join(sorted(preserved.keys()))
            )
    finally:
        src.close()
        dst.close()

    return notes
