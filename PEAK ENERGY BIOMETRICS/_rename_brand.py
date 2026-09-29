#!/usr/bin/env python3
"""Rename Peak Energy Biometrics → Peak Energy Biometrics across project files."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\DEV\OFFICE\PEAK ENERGY BIOMETRICS")

# Order matters: longer / more specific first
REPLACEMENTS = [
    ("C:\\DEV\\OFFICE\\PEAK ENERGY BIOMETRICS\\", "C:\\DEV\\OFFICE\\PEAK ENERGY BIOMETRICS\\"),
    ("C:/DEV/OFFICE/PEAK ENERGY BIOMETRICS/", "C:/DEV/OFFICE/PEAK ENERGY BIOMETRICS/"),
    ("Peak-Energy-Biometrics-Collector", "Peak-Energy-Biometrics-Collector"),
    ("Peak-Energy-Biometrics-UI", "Peak-Energy-Biometrics-UI"),
    ("PeakEnergyBiometricsUI_SingleInstance", "PeakEnergyBiometricsUI_SingleInstance"),
    ("PeakEnergyBiometrics.exe", "PeakEnergyBiometrics.exe"),
    ("PeakEnergyBiometrics.ico", "PeakEnergyBiometrics.ico"),
    ("PeakEnergyBiometrics.spec", "PeakEnergyBiometrics.spec"),
    ("PeakEnergyBiometrics", "PeakEnergyBiometrics"),
    ("Peak Energy Biometrics", "Peak Energy Biometrics"),
    ("PEAK ENERGY BIOMETRICS", "PEAK ENERGY BIOMETRICS"),
]

SKIP_DIRS = {".git", "venv", "__pycache__", "build", "dist"}
TEXT_SUFFIXES = {
    ".py", ".ps1", ".cmd", ".spec", ".md", ".sql", ".json", ".txt", ".vbs", ".gitignore",
}

changed = 0
for path in ROOT.rglob("*"):
    if not path.is_file():
        continue
    if any(part in SKIP_DIRS for part in path.parts):
        continue
    if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile"}:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        continue
    new = text
    for old, repl in REPLACEMENTS:
        new = new.replace(old, repl)
    if new != text:
        path.write_text(new, encoding="utf-8")
        changed += 1
        print(f"updated {path.relative_to(ROOT)}")

# Rename ico / spec files
for src_name, dst_name in (
    ("PeakEnergyBiometrics.ico", "PeakEnergyBiometrics.ico"),
    ("PeakEnergyBiometrics.spec", "PeakEnergyBiometrics.spec"),
):
    src = ROOT / src_name
    dst = ROOT / dst_name
    if src.exists():
        if dst.exists():
            dst.unlink()
        src.rename(dst)
        print(f"renamed {src_name} -> {dst_name}")
    elif not dst.exists() and src_name.endswith(".ico"):
        # fallback copy from PeakAttendance.ico if present
        alt = ROOT / "PeakAttendance.ico"
        if alt.exists():
            import shutil
            shutil.copy2(alt, dst)
            print(f"copied {alt.name} -> {dst_name}")

print(f"files_changed={changed}")
