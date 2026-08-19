Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
pythonwPath = "pythonw.exe"
appScript = scriptDir & "\app_native.py"

WshShell.CurrentDirectory = scriptDir
WshShell.Run pythonwPath & " """ & appScript & """", 0, False
Set WshShell = Nothing
