# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Peak Attendance (one-file exe)."""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    ("appsettings.example.json", "."),
    ("sql/02_atteninfo.sql", "sql"),
]

hiddenimports = [
    "pyodbc",
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "collector",
    "ui_app",
    "paths",
]

# Ensure pystray / pillow extras are bundled
tmp_ret = collect_all("pystray")
datas += tmp_ret[0]
hiddenimports += tmp_ret[1]

a = Analysis(
    ["peak_attendance.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PeakAttendance",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # no CMD window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
