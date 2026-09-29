# Peak Attendance

Single-file Windows app that:

- Reads punches from Hikvision **Entry / Exit** terminals into SQL Server (`atteninfo`) for **Keka**
- Manages **employees** (people + face photo) with SQL as master and sync to both readers

Branding uses the **Peak Energy** logo (exe icon, window icon, system tray).

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

## Help in the app

| Action | Result |
|---|---|
| **Help** button | Short in-app guide |
| **F1** | Same guide |
| Tray → **Help** | Opens UI + guide |
| **Open full guide** | Opens this Markdown file (bundled) |

## First run

1. Double-click `PeakAttendance.exe`.
2. It starts **in the system tray** (Peak Energy icon).
3. Double-click the tray icon (or **Open Peak Attendance**) to open the UI.
4. Set SQL Server (example: `localhost\SQLEXPRESS`), database `atteninfo`, user/password.
5. Click **Create / Repair database** — creates `atteninfo` and all tables if SQL is already installed.
6. Set Entry / Exit device IP, username, password; optional **Enabled** / **HTTPS**.
7. Per device: **Open device**, **Test this device**, or **Reset watermark**.
8. Under Collector: sync interval, lookback, timeout, overlap, max results.
9. Click **Save configuration**.
10. **Test devices** — should show SUCCESS for both.
11. **Run collector now** — inserts into `atteninfo.dbo.AccessEvents` (status lines update).
12. **Employees** → **Pull from devices** — merge people from both readers into SQL.
13. Optional: **Install / Start with Windows** — tray at logon + hidden collect every 1 minute.
14. Optional: **Uninstall / Stop with Windows** — removes tasks + shortcuts (keeps exe and database).

On first run, `appsettings.json` is created **next to the exe** (SQL bootstrap). Device and collector settings live in SQL.

## Main screen reference

### SQL Server

Bootstrap connection used to reach `atteninfo` (saved in `appsettings.json`).

### Collector

| Setting | Meaning |
|---|---|
| Sync interval (min) | How often the Windows collector task should run (used when registering Install) |
| First lookback (hrs) | Hours to pull when a device has no watermark yet |
| Timeout (sec) | HTTP timeout to each reader |
| Overlap (sec) | Re-read this many seconds before the last watermark |
| Max results / page | Hikvision AcsEvent page size |

### Entry / Exit device

| Control | Meaning |
|---|---|
| Display name, IP, port, user, password, direction | Reader connection |
| **Enabled** | Collect from this reader |
| **HTTPS** | Use HTTPS for Open / API |
| Last success / last event / last error | From `dbo.CollectorState` (read-only) |
| **Open device** | Opens web UI using on-screen username/password (password also copied to clipboard) |
| **Test this device** | Probe this reader only (works even if Enabled is off) |
| **Reset watermark** | Clears sync position; next collect uses First lookback (punches are not deleted) |

### Footer actions

| Button | Action |
|---|---|
| Save configuration | Writes `appsettings.json` + SQL device/collector settings |
| Create / Repair database | Creates/repairs `atteninfo` and tables |
| Test devices | Probe both enabled readers |
| Run collector now | One punch collect cycle |
| Employees | Open employee management window |
| Reload | Reload config + status from SQL |
| Install / Start with Windows | Register tray startup + minute collector + shortcuts |
| Uninstall / Stop with Windows | Remove those tasks/shortcuts |
| Help | In-app help (F1) |
| Minimize to tray | Hide window; collector task keeps running if installed |

**Install vs Uninstall:** only one is enabled. If the `Peak-Attendance-Collector` task exists, Install is disabled and Uninstall is enabled (and the reverse).

## Employees

SQL is the **master**. Changes are pushed to **both** Entry and Exit readers.

| Action | Behaviour |
|---|---|
| **Pull from devices** | Read UserInfo from Entry + Exit, merge by Employee No into `dbo.Employees`; pull face JPEG when available |
| **New** | Blank form for a new person |
| **Save + Push to devices** | Save SQL, then create/update UserInfo on both readers; enroll face if a photo is present |
| **Delete on devices + SQL** | Delete person on both readers, then remove SQL row |
| Load photo / Clear photo | Face image stored in `Employees.FaceImage` |

### Face photo limits

| Rule | Limit |
|---|---|
| Format | JPEG preferred (PNG/BMP/WebP auto-converted to JPEG) |
| Max file size | **200 KB** (hard — Hikvision face enroll) |
| Soft minimum size | 60 KB (warning if smaller) |
| Min resolution | **80 × 80** |
| Recommended resolution | **≥ 640 × 480** |
| Max before compress | 1920 × 1080 |

On **Load photo**, oversized images are auto-resized/compressed to fit 200 KB. If the file still exceeds the limit (or is below 80×80), an alert blocks the load. Soft warnings (under 60 KB or under 640×480) ask Continue / Cancel.

Per-device status is in `dbo.EmployeeDeviceSync` (shown as Entry / Exit columns: OK, Missing, Error, Partial).

Adding someone on one reader and then **Pull** merges them into SQL so you can **Save + Push** to the other reader.

## Changing settings later

No rebuild needed for config. Use the UI (or edit `appsettings.json` / SQL tables).

| Setting | Stored in |
|---|---|
| SQL server / login | `appsettings.json` beside the exe |
| Device IPs / passwords / Enabled / HTTPS | SQL `dbo.DeviceConfig` |
| Sync / lookback / timeout / overlap / max results | SQL `dbo.AppConfig` |
| Last success / last event / last error | SQL `dbo.CollectorState` (read-only in UI) |
| Employees + face photo | SQL `dbo.Employees` |
| Employee sync per device | SQL `dbo.EmployeeDeviceSync` |

Rebuild the exe only when application **code** changes.

## Behaviour

- **Single instance** — launching again focuses the existing tray app.
- **Close window** — returns to tray (does not quit).
- **Quit** — tray menu → Quit.
- **Collector task** — independent of the tray UI. If installed, it keeps collecting even when the window/tray app is closed (`PeakAttendance.exe --collect` every minute).
- **Logs** — `logs\collector.log` next to the exe (rotates at ~5 MB × 5 files).
- **Icon** — Peak Energy logo on the exe, windows, and tray.

## Database

- Name: `atteninfo`
- Punch table: `dbo.AccessEvents` (legacy Keka-style **varchar(50)** columns)
- People: `dbo.Employees` + `dbo.EmployeeDeviceSync`
- Default SQL login (as commonly configured): `sa` / `cctv@2025`

**Full table and varchar documentation:** [Database-Schema.md](Database-Schema.md)

Schema script (for admins): `sql\02_atteninfo.sql` (also bundled inside the exe).

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

Uses `PeakEnergyLogo.png` → `PeakAttendance.ico` for the Windows icon.

Output:

```text
dist\PeakAttendance.exe
```

### Modes

```bat
PeakAttendance.exe              rem tray UI (default)
PeakAttendance.exe --window     rem open UI window immediately
PeakAttendance.exe --collect    rem one collector run (Task Scheduler)
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Test devices → Connectivity | VPN / LAN to device subnet, correct IPs/ports |
| Wrong password / auth | Device admin user/password; wait if lockout |
| SQL login failed | Server name, `sa` password, Trust server certificate in SSMS, ODBC 18 |
| No tray icon | Check notification area overflow; run once with `--window` |
| CMD window every minute | Re-run **Install / Start with Windows** so the task uses `--collect` (hidden) |
| Employee push / face fail | Test devices first; check Entry/Exit status; retry Save + Push with JPEG |
| Collector stopped after closing UI | Normal for tray-only; Install registers a separate scheduled task that keeps running |

## Source layout (developers)

```text
peak_attendance.py     entry (UI or --collect)
ui_app.py              desktop + tray + Help text
employees.py           employee SQL + Hikvision UserInfo/face sync
employees_ui.py        Employees window
collector.py           Hikvision punches → AccessEvents
paths.py               frozen vs source paths + logo helpers
PeakEnergyLogo.png     brand logo
PeakAttendance.ico     Windows exe icon (built from logo)
appsettings*.json      SQL bootstrap
sql\02_atteninfo.sql   database schema
docs\                  Peak-Attendance.md, Database-Schema.md
install.ps1            source-tree installer
build-exe.cmd          build PeakAttendance.exe
```
