# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Peak Energy Dashboard (one-file exe)."""

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    ("appsettings.example.json", "."),
    ("PeakEnergyLogo.png", "."),
    ("PeakEnergyBiometrics.ico", "."),
]

hiddenimports = [
    "pyodbc",
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageTk",
    "tkcalendar",
    "babel",
    "babel.numbers",
    "collector",
    "punches",
    "punches_ui",
    "dashboard_ui",
    "ui_dashboard_app",
    "paths",
    "theme",
]

tmp_ret = collect_all("pystray")
datas += tmp_ret[0]
hiddenimports += tmp_ret[1]
tmp_ret = collect_all("tkcalendar")
datas += tmp_ret[0]
hiddenimports += tmp_ret[1]
tmp_ret = collect_all("babel")
datas += tmp_ret[0]
hiddenimports += tmp_ret[1]

a = Analysis(
    ["peak_dashboard.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["employees", "employees_ui", "ui_app", "acs_copy", "odbc_install"],
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
    name="PeakEnergyDashboard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="PeakEnergyBiometrics.ico",
)
