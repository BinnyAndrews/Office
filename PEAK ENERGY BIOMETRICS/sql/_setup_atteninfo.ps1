#Requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$Log = Join-Path $PSScriptRoot "_atteninfo_setup.log"
function Log([string]$m) { Add-Content -Path $Log -Value "$(Get-Date -Format o) $m"; Write-Host $m }

Remove-Item $Log -ErrorAction SilentlyContinue
Log "Elevated atteninfo setup. User=$(whoami)"

$sqlcmd = "C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\SQLCMD.EXE"
if (-not (Test-Path $sqlcmd)) { throw "sqlcmd not found at $sqlcmd" }

$inst = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL"
$instanceId = $inst.SQLEXPRESS
$loginModeKey = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceId\MSSQLServer"
Set-ItemProperty -Path $loginModeKey -Name LoginMode -Value 2 -Type DWord
Log "LoginMode=2 ($loginModeKey)"

& $sqlcmd -S "localhost\SQLEXPRESS" -E -C -Q "ALTER LOGIN sa WITH PASSWORD = N'cctv@2025', CHECK_POLICY = OFF, CHECK_EXPIRATION = OFF; ALTER LOGIN sa ENABLE;"
Log "sa enable exit=$LASTEXITCODE"

Restart-Service -Name 'MSSQL$SQLEXPRESS' -Force
Start-Sleep -Seconds 8
Log "SQL restarted"

$schema = Join-Path $PSScriptRoot "02_atteninfo.sql"
& $sqlcmd -S "localhost\SQLEXPRESS" -U sa -P "cctv@2025" -C -i $schema
Log "schema exit=$LASTEXITCODE"

& $sqlcmd -S "localhost\SQLEXPRESS" -U sa -P "cctv@2025" -C -d atteninfo -Q "UPDATE dbo.DeviceConfig SET Password = N'poli44557', UpdatedAt = SYSUTCDATETIME() WHERE Password = N'CHANGE_ME'; SELECT DeviceKey, IpAddress, Username, Direction FROM dbo.DeviceConfig; SELECT ConfigKey, ConfigValue FROM dbo.AppConfig;"
Log "seed exit=$LASTEXITCODE"
Log "DONE"
