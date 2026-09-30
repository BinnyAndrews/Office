#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Enable SQL authentication (Mixed Mode) and the sa login for Peak Energy Biometrics.

.DESCRIPTION
  Run on the SQL Server PC (ACS). Leaves master.dbo.atteninfo untouched.
  Uses password from appsettings.json (or -SaPassword).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\sql\enable_sql_auth.ps1
#>
param(
    [string]$AppRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$SaPassword = ""
)

$ErrorActionPreference = "Stop"
$Log = Join-Path $PSScriptRoot "_enable_sql_auth.log"
function Log([string]$m) {
    $line = "$(Get-Date -Format o) $m"
    Add-Content -Path $Log -Value $line
    Write-Host $m
}

Remove-Item $Log -ErrorAction SilentlyContinue
Log "Elevated SQL auth setup. User=$(whoami)"

$settings = Join-Path $AppRoot "appsettings.json"
if (-not $SaPassword -and (Test-Path $settings)) {
    $json = Get-Content $settings -Raw | ConvertFrom-Json
    $SaPassword = [string]$json.sql.password
}
if (-not $SaPassword) {
    throw "Provide -SaPassword or set sql.password in appsettings.json"
}

$sqlcmdCandidates = @(
    "C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\SQLCMD.EXE",
    "C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\SQLCMD.EXE"
)
$sqlcmd = $sqlcmdCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $sqlcmd) {
    $cmd = Get-Command sqlcmd -ErrorAction SilentlyContinue
    if ($cmd) { $sqlcmd = $cmd.Source }
}
if (-not $sqlcmd) { throw "sqlcmd.exe not found" }

# Mixed Mode for every installed instance
$instKey = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL"
if (-not (Test-Path $instKey)) { throw "No SQL Server instances found in registry." }
$inst = Get-ItemProperty $instKey
$props = $inst.PSObject.Properties | Where-Object { $_.Name -notmatch '^PS' }
foreach ($p in $props) {
    $instanceId = [string]$p.Value
    $loginModeKey = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceId\MSSQLServer"
    if (Test-Path $loginModeKey) {
        Set-ItemProperty -Path $loginModeKey -Name LoginMode -Value 2 -Type DWord
        Log "LoginMode=2 at $loginModeKey (instance $($p.Name))"
    }
}

# Restart SQL services
Get-Service | Where-Object { $_.Name -eq "MSSQLSERVER" -or $_.Name -like "MSSQL$*" } | ForEach-Object {
    Log "Restarting $($_.Name)..."
    Restart-Service -Name $_.Name -Force
}
Start-Sleep -Seconds 8

# Prefer default instance, then named instances
$servers = @("localhost,1433", "localhost", "localhost\SQLEXPRESS")
$ok = $false
foreach ($s in $servers) {
    try {
        & $sqlcmd -S $s -E -C -Q "SELECT @@SERVERNAME AS ServerName;" | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $server = $s
            $ok = $true
            break
        }
    } catch { }
}
if (-not $ok) { throw "Could not connect with Windows auth to local SQL Server." }

$pwdEsc = $SaPassword.Replace("'", "''")
& $sqlcmd -S $server -E -C -Q @"
ALTER LOGIN [sa] ENABLE;
ALTER LOGIN [sa] WITH PASSWORD = N'$pwdEsc', CHECK_POLICY = OFF, CHECK_EXPIRATION = OFF;
SELECT CASE SERVERPROPERTY('IsIntegratedSecurityOnly') WHEN 1 THEN 'WindowsOnly' ELSE 'Mixed' END AS AuthMode;
SELECT name, is_disabled FROM sys.sql_logins WHERE name = N'sa';
"@
Log "sa enable via $server exit=$LASTEXITCODE"

& $sqlcmd -S $server -U sa -P $SaPassword -C -d master -Q @"
SELECT DB_NAME() AS db, SUSER_SNAME() AS login;
SELECT name FROM master.sys.tables
WHERE name IN (N'atteninfo', N'Employees', N'DeviceConfig', N'AppConfig', N'CollectorState', N'EmployeeDeviceSync')
ORDER BY name;
"@
Log "sa SQL-auth test exit=$LASTEXITCODE"
Log "DONE — master.dbo.atteninfo unchanged; sa + Mixed Mode ready."
