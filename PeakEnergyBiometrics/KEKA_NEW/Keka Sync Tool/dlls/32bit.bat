ECHO OFF 
setlocal
cd /d %~dp0
XCOPY /s/y/o/r "32bit" "%windir%\system32"
cd %windir%\system32
regsvr32 zkemkeeper.dll
regsvr32 sbxpc.ocx
regsvr32 FP_CLOCK.ocx
regsvr32 FKAttend.ocx
sc failure "KekaAttendanceSync"  actions= restart/180000/restart/180000/restart/180000 reset= 86400 