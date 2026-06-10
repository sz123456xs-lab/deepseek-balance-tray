' DeepSeek Balance Tray - silent launch
Dim shell, fso, scriptPath, pythonw, mainPy
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(scriptPath, "venv\Scripts\pythonw.exe")
mainPy = fso.BuildPath(scriptPath, "main.py")

If Not fso.FileExists(pythonw) Then
    MsgBox "venv not found", vbExclamation, "Launch Failed"
    WScript.Quit 1
End If

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = scriptPath
shell.Run """" & pythonw & """ """ & mainPy & """", 0, False
