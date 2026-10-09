$ErrorActionPreference = "Continue"
$log = "C:\DEV\OFFICE\OPNSENSE\wireguard\deploy\Fix-PeakWG-NoUAC.log"
function W($m){ $m | Tee-Object -FilePath $log -Append }
"" | Set-Content $log
try {
  & "C:\DEV\OFFICE\OPNSENSE\wireguard\deploy\Fix-PeakWG-NoUAC.ps1" *>&1 | ForEach-Object { W "$_" }
  W "EXIT=0"
} catch {
  W "ERR: $($_.Exception.Message)"
  W "EXIT=1"
  exit 1
}
