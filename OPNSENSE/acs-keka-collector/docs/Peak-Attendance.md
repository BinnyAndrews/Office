# Peak Attendance

Single-file Windows app that reads punches from Hikvision entry/exit terminals and writes them to SQL Server (`atteninfo`) for Keka.

## What you give an employee

Only this file:

```text
PeakAttendance.exe
```

No Python install, no project folder, no `venv`.

### Still required on the PC / network

| Requirement | Notes |
|---|---|
| Network to door readers | e.g. `10.80.100.11` (entry), `10.80.100.12` (exit) |
| SQL Server reachable | Local Express **or** remote ACS SQL (e.g. `10.80.100.10\SQLEXPRESS`) |
| ODBC Driver 17 or 18 for SQL Server | Usually already present if SQL tools were installed |

The exe cannot embed SQL Server itself.

## First run

1. Double-click `PeakAttendance.exe`.
2. It starts **in the system tray** (no window).
3. Double-click the tray icon (or **Open Peak Attendance**) to open the UI.
4. Set SQL Server (example: `localhost\SQLEXPRESS`), database `atteninfo`, user/password.
5. Click **Create / Repair database** — creates `atteninfo` + tables if SQL is already installed.
6. Set Entry / Exit device IP, username, password; optional **Enabled** / **HTTPS**.
7. Per device: **Open device**, **Test this device**, or **Reset watermark** (re-pull from lookback).
8. Under Collector: sync interval, lookback, timeout, overlap, max results.
9. Click **Save configuration**.
10. **Test devices** — should show SUCCESS for both.
11. **Run collector now** — inserts into `atteninfo.dbo.AccessEvents` (status lines update).
12. Optional: **Install / Start with Windows** — tray at logon + hidden collect every 1 minute.
13. Optional: **Uninstall / Stop with Windows** — removes tasks + shortcuts (keeps exe and database).

**Help:** click **Help** in the UI (or press **F1**, or tray → Help). **Open full guide** opens this file.

On first run, `appsettings.json` is created **next to the exe** (editable SQL bootstrap). Device settings live in SQL (`DeviceConfig` / `AppConfig`).

## Changing settings later

Yes — no rebuild needed. Use the UI (or edit `appsettings.json` / SQL tables).

| Setting | Stored in |
|---|---|
| SQL server / login | `appsettings.json` beside the exe |
| Device IPs / passwords / Enabled / HTTPS | SQL `dbo.DeviceConfig` |
| Sync / lookback / timeout / overlap / max results | SQL `dbo.AppConfig` |
| Last success / last event / last error | SQL `dbo.CollectorState` (read-only in UI) |

Rebuild the exe only when application **code** changes.

## Behaviour

- **Single instance** — launching again focuses the existing tray app.
- **Close window** — returns to tray (does not quit).
- **Quit** — tray menu → Quit.
- **Collector task** — every 1 minute, hidden (`PeakAttendance.exe --collect`).
- **Logs** — `logs\collector.log` next to the exe (rotates at ~5 MB × 5 files).

## Database

- Name: `atteninfo`
- Punch table: `dbo.AccessEvents` (legacy Keka-style **varchar(50)** columns)
- Default SQL login (as configured): `sa` / `cctv@2025`

**Full table and varchar documentation:** [Database-Schema.md](Database-Schema.md)

Schema script (for admins): `sql\02_atteninfo.sql` (also bundled inside the exe for reference).

## Building the exe (developers)

From the project folder (with venv already set up):

```bat
build-exe.cmd
```

Or:

```bat
venv\Scripts\pip install pyinstaller
venv\Scripts\pyinstaller --noconfirm --clean PeakAttendance.spec
```

Output:

```text
dist\PeakAttendance.exe
```

Copy that single file to the employee PC.

### Modes

```bat
PeakAttendance.exe              rem tray UI (default)
PeakAttendance.exe --window     rem open UI window immediately
PeakAttendance.exe --collect    rem one collector run (Task Scheduler)
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Test devices → Connectivity | VPN / LAN to `10.80.100.x`, correct IPs |
| Wrong password / auth | Device admin user/password; wait if lockout |
| SQL login failed | Server name, `sa` password, Trust server certificate in SSMS, ODBC 18 |
| No tray icon | Check notification area overflow; run once with `--window` |
| CMD window every minute | Re-run **Install / Start with Windows** so the task uses `--collect` (hidden) |

## Source layout (developers)

```text
peak_attendance.py   entry (UI or --collect)
ui_app.py            desktop + tray
collector.py         Hikvision → SQL
paths.py             frozen vs source paths
appsettings*.json    SQL bootstrap
sql\02_atteninfo.sql database schema
install.ps1          source-tree installer
build-exe.cmd        build PeakAttendance.exe
```
