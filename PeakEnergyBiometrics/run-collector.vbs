' Run collector with no console window (used by Task Scheduler)
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Environment("PROCESS")("PYTHONUTF8") = "1"
sh.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
sh.Run """" & dir & "\venv\Scripts\pythonw.exe"" """ & dir & "\collector.py""", 0, False
