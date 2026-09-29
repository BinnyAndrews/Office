# Peak Attendance — database schema (`atteninfo`)

SQL Server database used by Peak Attendance for Keka sync.

| Item | Value |
|---|---|
| Database | `atteninfo` |
| Typical login | `sa` (mixed mode) |
| Schema script | `sql/02_atteninfo.sql` |
| Punch table (Keka) | `dbo.AccessEvents` |

Connect example (SSMS): server `localhost\SQLEXPRESS` or `10.80.100.10\SQLEXPRESS`, database `atteninfo`, Trust server certificate.

---

## 1. `dbo.AccessEvents` — attendance punches (Keka source)

Legacy-style **varchar** columns for Keka mapping. Helper columns support de-dupe and diagnostics.

### Columns

| Column | Type | Null | Description | Example |
|---|---|---|---|---|
| `RowId` | `BIGINT` IDENTITY | NOT NULL | Internal primary key (not for Keka) | `1` |
| `ID` | `VARCHAR(50)` | NOT NULL | Employee / Attendance Number from terminal | `114`, `C002` |
| `datetime` | `VARCHAR(50)` | NOT NULL | Full punch timestamp (local IST) | `2026-09-28 09:15:45` |
| `date` | `VARCHAR(50)` | NOT NULL | Date part | `2026-09-28` |
| `time` | `VARCHAR(50)` | NOT NULL | Time part | `09:15:45` |
| `authenticationresult` | `VARCHAR(50)` | NULL | Auth outcome | `Succeeded` |
| `authenticationtype` | `VARCHAR(50)` | NULL | Verify mode from device | face / card / etc. |
| `device` | `VARCHAR(50)` | NULL | Device display name | `Entry Reader` |
| `firstname` | `VARCHAR(50)` | NULL | First word of person name (best effort) | `John` |
| `lastname` | `VARCHAR(50)` | NULL | Remainder of person name | `Doe` |
| `personname` | `VARCHAR(50)` | NULL | Full name from terminal | `John Doe` |
| `persongroup` | `VARCHAR(50)` | NULL | Reserved (usually empty) | |
| `direction` | `VARCHAR(50)` | NOT NULL | `In` or `Out` | `In` |
| `DeviceIP` | `NVARCHAR(64)` | NULL | Terminal IP (helper) | `10.80.100.11` |
| `SerialNo` | `BIGINT` | NULL | Device event serial (helper, de-dupe) | `160306` |
| `InsertedAt` | `DATETIME2(0)` | NOT NULL | UTC insert time (default `SYSUTCDATETIME()`) | |

Note: `datetime`, `date`, and `time` are reserved words in T-SQL — always quote as `[datetime]`, `[date]`, `[time]`.

### Indexes

| Index | Definition | Purpose |
|---|---|---|
| `PK_AccessEvents` | `RowId` | Primary key |
| `UX_AccessEvents_DeviceSerial` | unique `(DeviceIP, SerialNo)` where `SerialNo IS NOT NULL` | Skip duplicate device events |
| `UX_AccessEvents_Punch` | unique `(ID, [datetime], direction, device)` | Skip duplicate logical punches |

### Sample query

```sql
SELECT TOP 100
    ID,
    [datetime],
    [date],
    [time],
    direction,
    device,
    personname,
    authenticationresult,
    authenticationtype
FROM atteninfo.dbo.AccessEvents
ORDER BY [datetime] DESC;
```

### Keka-oriented mapping (typical)

| SQL column | Typical Keka use |
|---|---|
| `ID` | Employee attendance / badge number |
| `datetime` or `date` + `time` | Punch time |
| `direction` | In / Out |
| `device` | Device name (optional) |

Exact Keka field mapping depends on their connector setup.

---

## 2. `dbo.DeviceConfig` — door reader settings (UI-editable)

| Column | Type | Null | Description | Example |
|---|---|---|---|---|
| `DeviceKey` | `VARCHAR(32)` | NOT NULL | PK: `entry` or `exit` | `entry` |
| `DisplayName` | `NVARCHAR(64)` | NOT NULL | Shown in UI / `AccessEvents.device` | `Entry Reader` |
| `IpAddress` | `VARCHAR(64)` | NOT NULL | Terminal IP | `10.80.100.11` |
| `Port` | `INT` | NOT NULL | HTTP port (default `80`) | `80` |
| `Username` | `NVARCHAR(64)` | NOT NULL | Device admin user | `admin` |
| `Password` | `NVARCHAR(128)` | NOT NULL | Device admin password | |
| `Direction` | `VARCHAR(10)` | NOT NULL | `In` or `Out` | `In` |
| `Https` | `BIT` | NOT NULL | Use HTTPS (default `0`) | `0` |
| `Enabled` | `BIT` | NOT NULL | Collect from this device (default `1`) | `1` |
| `UpdatedAt` | `DATETIME2(0)` | NOT NULL | Last change (UTC) | |

Default seed rows: `entry` → `10.80.100.11` / In, `exit` → `10.80.100.12` / Out.

---

## 3. `dbo.AppConfig` — collector settings (UI-editable)

Key/value store.

| Column | Type | Null | Description |
|---|---|---|---|
| `ConfigKey` | `VARCHAR(64)` | NOT NULL | Setting name (PK) |
| `ConfigValue` | `NVARCHAR(512)` | NOT NULL | Setting value as text |
| `UpdatedAt` | `DATETIME2(0)` | NOT NULL | Last change (UTC) |

### Seeded keys

| ConfigKey | Default | Meaning |
|---|---|---|
| `SyncIntervalMinutes` | `1` | How often the scheduled collector should run (task registration) |
| `MaxResults` | `30` | Page size for Hikvision AcsEvent API |
| `OverlapSeconds` | `120` | Re-read this many seconds before last watermark |
| `FirstLookbackHours` | `24` | Hours to pull when no watermark exists |
| `TimeoutSeconds` | `20` | HTTP timeout to each terminal |

---

## 4. `dbo.CollectorState` — per-device watermarks

| Column | Type | Null | Description |
|---|---|---|---|
| `DeviceIP` | `NVARCHAR(64)` | NOT NULL | PK — terminal IP |
| `LastEventTime` | `DATETIME2(0)` | NULL | Latest punch time collected |
| `LastSerialNo` | `BIGINT` | NULL | Latest device serial collected |
| `LastSuccessUtc` | `DATETIME2(0)` | NULL | Last successful collect (UTC) |
| `LastError` | `NVARCHAR(400)` | NULL | Last error message (if any) |

---

## 5. Bootstrap file (not a SQL table)

`appsettings.json` next to `PeakAttendance.exe`:

```json
{
  "sql": {
    "server": "localhost\\SQLEXPRESS",
    "database": "atteninfo",
    "username": "sa",
    "password": "cctv@2025",
    "driver": "ODBC Driver 18 for SQL Server"
  }
}
```

Used only to **reach SQL**. Device IPs and sync options are then loaded from `DeviceConfig` / `AppConfig`.

---

## VARCHAR size summary (Keka-facing)

All of these are **`VARCHAR(50)`** unless noted:

| Column | Size |
|---|---|
| `ID` | 50 |
| `datetime` | 50 |
| `date` | 50 |
| `time` | 50 |
| `authenticationresult` | 50 |
| `authenticationtype` | 50 |
| `device` | 50 |
| `firstname` | 50 |
| `lastname` | 50 |
| `personname` | 50 |
| `persongroup` | 50 |
| `direction` | 50 |

Other string sizes used by the app:

| Column | Table | Size |
|---|---|---|
| `DeviceIP` | AccessEvents / CollectorState | `NVARCHAR(64)` |
| `DeviceKey` | DeviceConfig | `VARCHAR(32)` |
| `DisplayName` | DeviceConfig | `NVARCHAR(64)` |
| `IpAddress` | DeviceConfig | `VARCHAR(64)` |
| `Username` | DeviceConfig | `NVARCHAR(64)` |
| `Password` | DeviceConfig | `NVARCHAR(128)` |
| `Direction` | DeviceConfig | `VARCHAR(10)` |
| `ConfigKey` | AppConfig | `VARCHAR(64)` |
| `ConfigValue` | AppConfig | `NVARCHAR(512)` |
| `LastError` | CollectorState | `NVARCHAR(400)` |

---

## 6. `dbo.Employees` — person master (SQL source of truth)

Pulled from Entry/Exit Hikvision readers and editable in the **Employees** UI. Create/Edit/Delete is pushed to **both** devices.

| Column | Type | Description |
|---|---|---|
| `EmployeeNo` | `VARCHAR(32)` PK | Same ID used in `AccessEvents.ID` |
| `Name` | `NVARCHAR(128)` | Display name |
| `Gender` | `VARCHAR(16)` | Optional |
| `UserType` | `VARCHAR(32)` | e.g. `normal` |
| `CardNo` | `VARCHAR(64)` | Optional card |
| `ValidEnabled` | `BIT` | Access enabled |
| `ValidFrom` / `ValidTo` | `DATETIME2(0)` | Validity window |
| `FaceImage` | `VARBINARY(MAX)` | JPEG face photo (max 200 KB; see face photo limits in Peak-Attendance.md) |
| `HasFace` | `BIT` | Photo / enroll present |
| `Notes` | `NVARCHAR(256)` | Optional |
| `SourceDevices` | `NVARCHAR(64)` | e.g. `entry,exit` from last pull |
| `CreatedAt` / `UpdatedAt` | `DATETIME2(0)` | UTC |

## 7. `dbo.EmployeeDeviceSync` — per-device sync status

| Column | Type | Description |
|---|---|---|
| `EmployeeNo` + `DeviceKey` | PK | Links to Employees / DeviceConfig |
| `LastSyncUtc` | `DATETIME2(0)` | Last push/pull touch |
| `Status` | `VARCHAR(32)` | `OK`, `Missing`, `Error`, `Partial`, `Pending` |
| `Error` | `NVARCHAR(400)` | Last error text |

