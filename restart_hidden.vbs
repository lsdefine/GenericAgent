Option Explicit

Dim shell, wmi, processes
Dim appDir, pythonPath, pythonwPath, tuiPath, schedPath, wechatPath

appDir = "E:\Work\Python\GenericAgent"
pythonPath = "C:\ProgramData\anaconda3\python.exe"
pythonwPath = "C:\ProgramData\anaconda3\pythonw.exe"
tuiPath = appDir & "\frontends\tuiapp_v2.py"
schedPath = appDir & "\agentmain.py"
wechatPath = appDir & "\frontends\wechatapp.py"

Set shell = CreateObject("WScript.Shell")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")

TerminateMatches Array( _
    "E:\Work\Python\GenericAgent\launch.pyw", _
    "E:\Work\Python\GenericAgent\frontends\tuiapp_v2.py", _
    "E:\Work\Python\GenericAgent\frontends\tuiapp.py", _
    "E:\Work\Python\GenericAgent\frontends\stapp.py", _
    "E:\Work\Python\GenericAgent\frontends\wechatapp.py", _
    "webview-exe-name=pythonw.exe", _
    "reflect\scheduler.py")

WScript.Sleep 2000

shell.CurrentDirectory = appDir
shell.Run """" & pythonPath & """ """ & tuiPath & """", 1, False
shell.Run """" & pythonwPath & """ """ & schedPath & """ --reflect """ & appDir & "\reflect\scheduler.py""", 0, False
shell.Run """" & pythonwPath & """ """ & wechatPath & """", 0, False

Sub TerminateMatches(patterns)
    Dim process, cmd, pattern
    Set processes = wmi.ExecQuery("SELECT ProcessId, Name, CommandLine FROM Win32_Process")
    For Each process In processes
        If Not IsNull(process.CommandLine) Then
            cmd = process.CommandLine
            For Each pattern In patterns
                If InStr(1, cmd, pattern, vbTextCompare) > 0 Then
                    process.Terminate()
                    Exit For
                End If
            Next
        End If
    Next
End Sub
