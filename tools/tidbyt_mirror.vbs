' Opens the Tidbyt Mirror window without a console window. Double-click this file.
' It runs tidbyt_mirror.py (next to this file) with pythonw; see that file for details.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = fso.GetParentFolderName(here)
shell.Run "pythonw """ & here & "\tidbyt_mirror.py""", 0, False
