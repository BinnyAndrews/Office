$ErrorActionPreference = "Stop"
$log = "C:\DEV\OFFICE\PEAK ENERGY BIOMETRICS\sql\_admin_setup.log"
function Log($m) { Add-Content -Path $log -Value "$(Get-Date -Format o) $m" }

try {
  Log "Elevated start. User=$(whoami)"
  $sqlcmd = "C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\SQLCMD.EXE"
  $creds = Get-Content "C:\DEV\OFFICE\PEAK ENERGY BIOMETRICS\sql\_local_passwords.json" | ConvertFrom-Json
  $collector = $creds.attendance_collector
  $keka = $creds.keka_reader

  # Mixed mode via registry for this instance
  $inst = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL"
  $instanceId = $inst.SQLEXPRESS
  $loginModeKey = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceId\MSSQLServer"
  Set-ItemProperty -Path $loginModeKey -Name LoginMode -Value 2 -Type DWord
  Log "Set LoginMode=2 at $loginModeKey"

  Restart-Service -Name 'MSSQL$SQLEXPRESS' -Force
  Start-Sleep -Seconds 8
  Log "SQL restarted"

  # Ensure current machine admins / AzureAD user can administer
  & $sqlcmd -S "localhost\SQLEXPRESS" -E -C -Q @"
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'AzureAD\BinnyAndrews')
BEGIN
  CREATE LOGIN [AzureAD\BinnyAndrews] FROM WINDOWS;
END
ALTER SERVER ROLE sysadmin ADD MEMBER [AzureAD\BinnyAndrews];
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'BUILTIN\Administrators')
BEGIN
  CREATE LOGIN [BUILTIN\Administrators] FROM WINDOWS;
END
ALTER SERVER ROLE sysadmin ADD MEMBER [BUILTIN\Administrators];
SELECT SUSER_SNAME() AS me, IS_SRVROLEMEMBER('sysadmin') AS is_sysadmin;
SELECT CASE SERVERPROPERTY('IsIntegratedSecurityOnly') WHEN 1 THEN 'WindowsOnly' ELSE 'Mixed' END AS AuthMode;
"@
  Log "sysadmin grant exit=$LASTEXITCODE"

  $setupPath = "C:\DEV\OFFICE\PEAK ENERGY BIOMETRICS\sql\_setup_local.sql"
  # Refresh setup SQL with passwords
  $sql = @"
IF DB_ID(N'PeakAttendance') IS NULL
BEGIN
    CREATE DATABASE PeakAttendance;
END;
GO
USE PeakAttendance;
GO
IF OBJECT_ID(N'dbo.AttendanceLogs', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AttendanceLogs (
        LogIndex      INT IDENTITY(1, 1) NOT NULL CONSTRAINT PK_AttendanceLogs PRIMARY KEY,
        DeviceNumber  INT            NOT NULL,
        UserID        NVARCHAR(32)   NOT NULL,
        LogTime       DATETIME2(0)   NOT NULL,
        Status        TINYINT        NOT NULL CONSTRAINT CK_AttendanceLogs_Status CHECK (Status IN (0, 1)),
        DeviceIP      NVARCHAR(64)   NOT NULL,
        SerialNo      BIGINT         NULL,
        EmployeeName  NVARCHAR(128)  NULL,
        VerifyMode    NVARCHAR(64)   NULL,
        MinorCode     INT            NULL,
        InsertedAt    DATETIME2(0)   NOT NULL CONSTRAINT DF_AttendanceLogs_InsertedAt DEFAULT (SYSUTCDATETIME())
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_AttendanceLogs_DeviceSerial' AND object_id = OBJECT_ID(N'dbo.AttendanceLogs'))
BEGIN
    CREATE UNIQUE INDEX UX_AttendanceLogs_DeviceSerial ON dbo.AttendanceLogs (DeviceIP, SerialNo) WHERE SerialNo IS NOT NULL;
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_AttendanceLogs_Punch' AND object_id = OBJECT_ID(N'dbo.AttendanceLogs'))
BEGIN
    CREATE UNIQUE INDEX UX_AttendanceLogs_Punch ON dbo.AttendanceLogs (DeviceNumber, UserID, LogTime, Status);
END;
GO
IF OBJECT_ID(N'dbo.CollectorState', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CollectorState (
        DeviceIP        NVARCHAR(64)  NOT NULL CONSTRAINT PK_CollectorState PRIMARY KEY,
        LastEventTime   DATETIME2(0)  NULL,
        LastSerialNo    BIGINT        NULL,
        LastSuccessUtc  DATETIME2(0)  NULL,
        LastError       NVARCHAR(400) NULL
    );
END;
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'attendance_collector')
BEGIN
    CREATE LOGIN attendance_collector WITH PASSWORD = N'$collector', CHECK_POLICY = ON;
END
ELSE
BEGIN
    ALTER LOGIN attendance_collector WITH PASSWORD = N'$collector';
END;
GO
USE PeakAttendance;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'attendance_collector')
BEGIN
    CREATE USER attendance_collector FOR LOGIN attendance_collector;
END;
GO
GRANT SELECT, INSERT, UPDATE ON dbo.AttendanceLogs TO attendance_collector;
GRANT SELECT, INSERT, UPDATE ON dbo.CollectorState TO attendance_collector;
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'keka_reader')
BEGIN
    CREATE LOGIN keka_reader WITH PASSWORD = N'$keka', CHECK_POLICY = ON;
END
ELSE
BEGIN
    ALTER LOGIN keka_reader WITH PASSWORD = N'$keka';
END;
GO
USE PeakAttendance;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'keka_reader')
BEGIN
    CREATE USER keka_reader FOR LOGIN keka_reader;
END;
GO
GRANT SELECT ON dbo.AttendanceLogs TO keka_reader;
GO
PRINT 'PeakAttendance ready.';
GO
"@
  Set-Content -Path $setupPath -Value $sql -Encoding UTF8
  & $sqlcmd -S "localhost\SQLEXPRESS" -E -C -i $setupPath
  Log "DB setup exit=$LASTEXITCODE"

  # Verify SQL auth works
  & $sqlcmd -S "localhost\SQLEXPRESS" -U attendance_collector -P $collector -C -Q "SELECT DB_NAME() AS db, SUSER_SNAME() AS login; SELECT COUNT(*) AS tables FROM PeakAttendance.INFORMATION_SCHEMA.TABLES;"
  Log "SQL auth test exit=$LASTEXITCODE"
  Log "DONE"
} catch {
  Log "ERROR: $_"
  exit 1
}
