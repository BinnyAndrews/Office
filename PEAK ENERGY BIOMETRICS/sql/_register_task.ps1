$ErrorActionPreference = "Stop"
$taskName = "Peak-ACS-Keka-Collector"
$tr = "C:\DEV\OFFICE\PEAK ENERGY BIOMETRICS\run.cmd"
schtasks /Create /TN $taskName /SC MINUTE /MO 1 /RU SYSTEM /RL HIGHEST /F /TR "`"$tr`""
schtasks /Run /TN $taskName
schtasks /Query /TN $taskName /V /FO LIST | Select-String -Pattern "TaskName|Status|Next Run|Last Run|Task To Run|Schedule Type|Repeat"
