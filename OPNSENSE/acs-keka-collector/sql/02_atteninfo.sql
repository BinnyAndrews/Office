/*
  Peak Keka attendance database (legacy column layout for Keka).

  Database: atteninfo
  Login:    sa / cctv@2025  (set by setup script; mixed mode required)
*/

IF DB_ID(N'atteninfo') IS NULL
BEGIN
    CREATE DATABASE atteninfo;
END;
GO

USE atteninfo;
GO

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF OBJECT_ID(N'dbo.AccessEvents', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AccessEvents (
        RowId                 BIGINT IDENTITY(1, 1) NOT NULL
            CONSTRAINT PK_AccessEvents PRIMARY KEY,
        ID                    VARCHAR(50)  NOT NULL,
        [datetime]            VARCHAR(50)  NOT NULL,
        [date]                VARCHAR(50)  NOT NULL,
        [time]                VARCHAR(50)  NOT NULL,
        authenticationresult  VARCHAR(50)  NULL,
        authenticationtype    VARCHAR(50)  NULL,
        device                VARCHAR(50)  NULL,
        firstname             VARCHAR(50)  NULL,
        lastname              VARCHAR(50)  NULL,
        personname            VARCHAR(50)  NULL,
        persongroup           VARCHAR(50)  NULL,
        direction             VARCHAR(50)  NOT NULL,
        DeviceIP              NVARCHAR(64) NULL,
        SerialNo              BIGINT       NULL,
        InsertedAt            DATETIME2(0) NOT NULL
            CONSTRAINT DF_AccessEvents_InsertedAt DEFAULT (SYSUTCDATETIME())
    );
END;
GO

SET QUOTED_IDENTIFIER ON;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'UX_AccessEvents_DeviceSerial'
      AND object_id = OBJECT_ID(N'dbo.AccessEvents')
)
BEGIN
    CREATE UNIQUE INDEX UX_AccessEvents_DeviceSerial
        ON dbo.AccessEvents (DeviceIP, SerialNo)
        WHERE SerialNo IS NOT NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'UX_AccessEvents_Punch'
      AND object_id = OBJECT_ID(N'dbo.AccessEvents')
)
BEGIN
    CREATE UNIQUE INDEX UX_AccessEvents_Punch
        ON dbo.AccessEvents (ID, [datetime], direction, device);
END;
GO

IF OBJECT_ID(N'dbo.CollectorState', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CollectorState (
        DeviceIP        NVARCHAR(64)  NOT NULL
            CONSTRAINT PK_CollectorState PRIMARY KEY,
        LastEventTime   DATETIME2(0)  NULL,
        LastSerialNo    BIGINT        NULL,
        LastSuccessUtc  DATETIME2(0)  NULL,
        LastError       NVARCHAR(400) NULL
    );
END;
GO

IF OBJECT_ID(N'dbo.DeviceConfig', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.DeviceConfig (
        DeviceKey    VARCHAR(32)   NOT NULL
            CONSTRAINT PK_DeviceConfig PRIMARY KEY,
        DisplayName  NVARCHAR(64)  NOT NULL,
        IpAddress    VARCHAR(64)   NOT NULL,
        Port         INT           NOT NULL
            CONSTRAINT DF_DeviceConfig_Port DEFAULT (80),
        Username     NVARCHAR(64)  NOT NULL,
        Password     NVARCHAR(128) NOT NULL,
        Direction    VARCHAR(10)   NOT NULL,
        Https        BIT           NOT NULL
            CONSTRAINT DF_DeviceConfig_Https DEFAULT (0),
        Enabled      BIT           NOT NULL
            CONSTRAINT DF_DeviceConfig_Enabled DEFAULT (1),
        UpdatedAt    DATETIME2(0)  NOT NULL
            CONSTRAINT DF_DeviceConfig_UpdatedAt DEFAULT (SYSUTCDATETIME())
    );
END;
GO

IF OBJECT_ID(N'dbo.AppConfig', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.AppConfig (
        ConfigKey    VARCHAR(64)    NOT NULL
            CONSTRAINT PK_AppConfig PRIMARY KEY,
        ConfigValue  NVARCHAR(512)  NOT NULL,
        UpdatedAt    DATETIME2(0)   NOT NULL
            CONSTRAINT DF_AppConfig_UpdatedAt DEFAULT (SYSUTCDATETIME())
    );
END;
GO

/* Seed devices if empty */
IF NOT EXISTS (SELECT 1 FROM dbo.DeviceConfig)
BEGIN
    INSERT INTO dbo.DeviceConfig (DeviceKey, DisplayName, IpAddress, Port, Username, Password, Direction, Https, Enabled)
    VALUES
        ('entry', N'Entry Reader', '10.80.100.11', 80, N'admin', N'CHANGE_ME', 'In',  0, 1),
        ('exit',  N'Exit Reader',  '10.80.100.12', 80, N'admin', N'CHANGE_ME', 'Out', 0, 1);
END;
GO

/* Seed app settings if empty */
IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'SyncIntervalMinutes')
    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'SyncIntervalMinutes', N'1');
IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'MaxResults')
    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'MaxResults', N'30');
IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'OverlapSeconds')
    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'OverlapSeconds', N'120');
IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'FirstLookbackHours')
    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'FirstLookbackHours', N'24');
IF NOT EXISTS (SELECT 1 FROM dbo.AppConfig WHERE ConfigKey = N'TimeoutSeconds')
    INSERT INTO dbo.AppConfig (ConfigKey, ConfigValue) VALUES (N'TimeoutSeconds', N'20');
GO

PRINT 'atteninfo ready.';
GO
