' Launch Peak Attendance in system tray (no CMD, no window until user opens it)
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run """" & dir & "\venv\Scripts\pythonw.exe"" """ & dir & "\ui_app.py""", 0, False
