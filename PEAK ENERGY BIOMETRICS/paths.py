"""Shared path helpers for source and frozen PeakEnergyBiometrics.exe."""

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


def logo_png_path() -> Path | None:
    """Peak Energy logo PNG for window/tray icons."""
    for base in (resource_dir(), app_dir()):
        path = base / "PeakEnergyLogo.png"
        if path.exists():
            return path
    return None


def logo_ico_path() -> Path | None:
    """Windows .ico used for exe / window iconbitmap."""
    for base in (resource_dir(), app_dir()):
        path = base / "PeakEnergyBiometrics.ico"
        if path.exists():
            return path
    return None
