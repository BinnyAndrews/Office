# Peak Energy Biometrics

Single-file Windows app that:

- Syncs Hikvision **Entry / Exit** terminals with SQL Server for Peak Energy / Keka
- Manages **employees** (people + face photo) with SQL as master and sync to both readers
- Can leave punch writing **off** while another collector is still in use

Branding uses the **Peak Energy** logo (exe icon, window icon, system tray).

## What you give an employee / ACS PC

Only this file (plus optional `appsettings.json` next to it after first save):

```text
PeakEnergyBiometrics.exe
```

No Python install, no project folder, no `venv`.

### Still required on the PC / network

| Requirement | Notes |
|---|---|
| Network to door readers | e.g. `10.80.100.11` (entry), `10.80.100.12` (exit) |
| SQL Server reachable | On ACS PC: `localhost`. From another PC: `10.80.100.10,1433` |
| ODBC Driver 17 or 18 for SQL Server | Usually present if SQL tools were installed |

## Help in the app

| Action | Result |
|---|---|
| **Help** button | Short in-app guide |
| **F1** | Same guide |
| Tray → **Help** | Opens UI + guide |
| **Open full guide** | Opens this Markdown file (bundled) |

## First run (existing ACS / Keka SQL)

Typical Peak site already has punches in **`master.dbo.atteninfo`**.

1. Set **Server** = `10.80.100.10,1433` (or `localhost` on the ACS PC).
2. **Database** = `master`, **Punch table** = `atteninfo`.
3. **Create / Repair database** — creates helper tables only; does **not** wipe `atteninfo`.
4. Configure Entry / Exit → **Save** → **Test devices**.
5. Keep **Enable punch collector** **OFF** while another collector writes punches.
6. Use **Employees** for people / faces (SQL `dbo.Employees`).
7. When ready to take over punches, turn the collector **ON** and Save.

## Helper tables (in `master` on ACS)

| Table | Purpose |
|---|---|
| `dbo.atteninfo` | Existing punch table for Keka (**do not drop**) |
| `dbo.Employees` | Employee master (first/last name, face, access) |
| `dbo.EmployeeDeviceSync` | Per-device sync status |
| `dbo.DeviceConfig` | Entry / Exit reader settings |
| `dbo.AppConfig` | Collector options (`CollectorEnabled`, intervals, …) |
| `dbo.CollectorState` | Last success / watermark / error |

## Punch collector switch

- **OFF** — scheduled `--collect` and **Run collector now** do not write punches.
- **ON** — writes compatible rows into `atteninfo` (direction `1`/`2`, device serial, reader name, card no when present).

## Install / Start with Windows

Registers tray at logon + `Peak-Energy-Biometrics-Collector` (every 1 minute). The task still runs when installed, but skips writing while the collector switch is OFF.

## Build

```bat
build-exe.cmd
```

Output: `dist\PeakEnergyBiometrics.exe`
