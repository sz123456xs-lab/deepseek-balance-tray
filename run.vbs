' DeepSeek 余额查询 - 静默启动脚本 (无任何窗口)
' 双击此文件，后台启动托盘图标

Dim shell, fso, scriptPath, pythonw, mainPy
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(scriptPath, "venv\Scripts\pythonw.exe")
mainPy = fso.BuildPath(scriptPath, "main.py")

If Not fso.FileExists(pythonw) Then
    MsgBox "未找到虚拟环境 pythonw.exe！" & vbCrLf & _
           "请先打开命令行执行:" & vbCrLf & _
           "cd /d " & scriptPath & vbCrLf & _
           "uv venv venv && uv pip install pystray Pillow requests", _
           vbExclamation, "DeepSeek 余额查询 - 启动失败"
    WScript.Quit 1
End If

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = scriptPath
shell.Run """" & pythonw & """ """ & mainPy & """", 0, False
