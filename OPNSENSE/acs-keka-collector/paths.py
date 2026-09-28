"""Shared path helpers for source and frozen PeakAttendance.exe."""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Writable install folder (next to the .exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    """Bundled read-only resources (PyInstaller _MEIPASS or project root)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent
