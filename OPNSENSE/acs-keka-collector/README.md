# Hikvision terminals → SQL → Keka

No iVMS, no HikCentral license. The DS-K1T342MFWX units at `10.80.100.11` (IN) and `10.80.100.12` (OUT) stay the terminals. This collector on the ACS PC reads their events and writes a table Keka already knows how to pull.

```
Entry .11  ─┐
            ├─ HTTP API (LAN) →  collector.py  →  PeakAttendance.dbo.AttendanceLogs
Exit  .12  ─┘                                         │
                                                      │ TCP 1433
                                                      ▼
                                                    Keka
```

## 1. Rebuild the ACS PC

1. Windows 10/11 Pro, static IP **`10.80.100.10`**, mask `/24`, gateway `10.80.100.1`, DNS `10.80.100.1`.
2. Time zone **India Standard Time**.
3. If this is a **new NIC**, update the Kea reservation MAC for `10.80.100.10` (old MAC was `50:81:40:9a:7a:a3`).
4. Install:
   - [SQL Server Express](https://www.microsoft.com/sql-server/sql-server-downloads) (mixed mode / SQL auth)
   - SSMS
   - [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
   - [Python 3.11+](https://www.python.org/downloads/) (tick **Add python.exe to PATH**)
5. SQL Server Configuration Manager:
   - **TCP/IP** = Enabled
   - IPAll **TCP Port** = **1433** (clear dynamic ports)
   - Restart SQL Server
6. Windows Firewall: allow inbound **TCP 1433** (OPNsense still restricts who can reach it from the internet).

Do **not** publish RDP 3389.

## 2. Create the database

In SSMS, edit passwords in `sql/01_create_database.sql`, then execute it.

Keka column mapping:

| SQL column | Keka field | Peak meaning |
| --- | --- | --- |
| `DeviceNumber` | Device Number | `1` entry, `2` exit |
| `UserID` | User ID | Must equal Keka **Attendance Number** |
| `LogTime` | Log Time | Punch datetime (IST) |
| `Status` | Status | `0` IN, `1` OUT |
| `LogIndex` | Log Index | Identity, optional |

Give Keka: public WAN IP, port **1433**, database **PeakAttendance**, login **keka_reader**, table **AttendanceLogs**.

## 3. Install the collector

Copy this folder to the ACS PC, e.g. `C:\acs-keka-collector`.

```powershell
cd C:\acs-keka-collector
copy config.example.json config.json
notepad config.json
```

Set:

- SQL password for `attendance_collector`
- Device admin passwords for `.11` and `.12`

Admin PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-task.ps1
```

That creates a venv, installs packages, and registers **Peak-ACS-Keka-Collector** (every 1 minute, as SYSTEM).

## 4. Test

```powershell
.\venv\Scripts\python.exe collector.py --probe
.\venv\Scripts\python.exe collector.py --dry-run
.\venv\Scripts\python.exe collector.py
```

`--probe` must show both terminals. `--dry-run` prints punches without writing SQL. A normal run inserts new rows only (duplicates are skipped).

Confirm in SSMS:

```sql
SELECT TOP 50 * FROM PeakAttendance.dbo.AttendanceLogs ORDER BY LogTime DESC;
```

Punch on entry, wait one minute, confirm Status `0`. Punch on exit, confirm Status `1`. Then ask Keka to sync.

Backfill (does not wipe existing rows):

```powershell
.\venv\Scripts\python.exe collector.py --since-hours 48
```

Logs: `logs\collector.log`.

## 5. Device rules

On each terminal (screen or `http://10.80.100.11`):

- Employee ID = Keka Attendance Number
- Time zone IST / NTP
- Faces stay on the device; rebuilding this PC does not un-enroll people

## 6. If something fails

| Symptom | Check |
| --- | --- |
| HTTP 401 / device locked | Wrong admin password, or too many failures — wait ~30 min |
| SQL driver error | Install ODBC 18, or set `driver` in config to `ODBC Driver 17 for SQL Server` |
| Keka connects but no new punches | Collector task running? `SELECT * FROM CollectorState`. Device IDs match Keka? |
| Keka cannot connect | SQL TCP 1433, mixed mode, `keka_reader` password, OPNsense NAT `:1433` → `.10` |
| New PC has no punches after format | Faces are on the terminals; run `--since-hours 24` once |

Task Scheduler: **Peak-ACS-Keka-Collector**. Disable it only when you intend to stop feeding Keka.
