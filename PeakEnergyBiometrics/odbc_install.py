#!/usr/bin/env python3
"""Detect / install Microsoft ODBC Driver for SQL Server (MSI embedded in the exe)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pyodbc

from paths import resource_dir

PREFERRED_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
)

MSI_NAMES = (
    "msodbcsql18_x64.msi",
    "msodbcsql.msi",
    "msodbcsql17_x64.msi",
)


def installed_sql_odbc_driver() -> str | None:
    """Return the best installed SQL Server ODBC driver name, or None."""
    try:
        installed = set(pyodbc.drivers())
    except Exception:
        return None
    for name in PREFERRED_DRIVERS:
        if name in installed:
            return name
    return None


def find_embedded_msodbcsql_msi() -> Path | None:
    """
    Locate the MSI packed into PeakEnergyBiometrics.exe (PyInstaller datas),
    or under project installers/ when running from source.
    Never requires a side-by-side installers folder next to the exe.
    """
    roots = [resource_dir() / "installers", resource_dir()]
    for root in roots:
        for name in MSI_NAMES:
            path = root / name
            if path.is_file() and path.stat().st_size > 100_000:
                return path
    return None


def materialize_msi_for_install(embedded: Path) -> Path:
    """
    Copy embedded MSI to a normal temp path so msiexec can run it reliably
    (one-file extract dir can be awkward for Windows Installer).
    """
    dest = Path(tempfile.mkdtemp(prefix="peak_odbc_")) / embedded.name
    shutil.copy2(embedded, dest)
    return dest


def _msiexec_args(msi: Path) -> list[str]:
    return [
        "/i",
        str(msi),
        "/qn",
        "/norestart",
        "IACCEPTMSODBCSQLLICENSETERMS=YES",
        "ADDLOCAL=ALL",
    ]


def _run_msiexec(msi: Path, *, elevated: bool) -> tuple[int, str]:
    args = _msiexec_args(msi)
    if elevated:
        quoted = ",".join(f"'{a}'" for a in args)
        ps = (
            f"$p = Start-Process -FilePath 'msiexec.exe' -ArgumentList @({quoted}) "
            f"-Verb RunAs -Wait -PassThru; if ($null -eq $p) {{ exit 1 }}; exit $p.ExitCode"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode, out

    proc = subprocess.run(
        ["msiexec.exe", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out


def _msi_success(code: int) -> bool:
    # 0 = success, 3010 = success reboot required, 1638 = already installed
    return code in {0, 3010, 1638}


def ensure_msodbcsql_driver() -> str:
    """
    If ODBC Driver 17/18 is present, skip.
    Otherwise extract the MSI embedded in this app and run it quietly.
    """
    present = installed_sql_odbc_driver()
    if present:
        return f"ODBC already installed — skipped MSI ({present})."

    embedded = find_embedded_msodbcsql_msi()
    if embedded is None:
        raise RuntimeError(
            "Microsoft ODBC Driver for SQL Server is not installed, and the "
            "embedded ODBC installer was not found inside this application.\n"
            "Install ODBC Driver 18 manually, then try Install again."
        )

    msi = materialize_msi_for_install(embedded)
    try:
        code, out = _run_msiexec(msi, elevated=False)
        if not _msi_success(code):
            code, out = _run_msiexec(msi, elevated=True)

        if not _msi_success(code):
            detail = out[-800:] if out else f"msiexec exit {code}"
            raise RuntimeError(
                "Failed to install Microsoft ODBC Driver for SQL Server.\n"
                f"{detail}\n"
                "Allow the UAC prompt, or install ODBC 18 manually."
            )

        present = installed_sql_odbc_driver()
        if present:
            reboot = " (reboot recommended)" if code == 3010 else ""
            return f"Installed {present} from embedded MSI{reboot}."
        if code == 3010:
            return "Installed ODBC from embedded MSI — reboot recommended before SQL use."
        if code == 1638:
            return "ODBC MSI reported already installed."
        return f"ODBC MSI finished (exit {code})."
    finally:
        try:
            shutil.rmtree(msi.parent, ignore_errors=True)
        except Exception:
            pass
