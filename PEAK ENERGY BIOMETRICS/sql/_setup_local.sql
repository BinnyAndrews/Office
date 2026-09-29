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
    CREATE LOGIN attendance_collector WITH PASSWORD = N'PkCol_4FDOP3fJQz!', CHECK_POLICY = ON;
END
ELSE
BEGIN
    ALTER LOGIN attendance_collector WITH PASSWORD = N'PkCol_4FDOP3fJQz!';
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
    CREATE LOGIN keka_reader WITH PASSWORD = N'PkKeka_X9c7CjYoAR!', CHECK_POLICY = ON;
END
ELSE
BEGIN
    ALTER LOGIN keka_reader WITH PASSWORD = N'PkKeka_X9c7CjYoAR!';
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
