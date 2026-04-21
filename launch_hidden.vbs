Option Explicit

Dim shell, wmi, processes
Dim appDir, pythonwPath, launchPath, wechatPath

appDir = "E:\Work\Python\GenericAgent"
pythonwPath = "C:\ProgramData\anaconda3\pythonw.exe"
launchPath = appDir & "\launch.pyw"
wechatPath = appDir & "\frontends\wechatapp.py"

Set shell = CreateObject("WScript.Shell")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set processes = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name = 'python.exe' OR Name = 'pythonw.exe'")

shell.CurrentDirectory = appDir

If Not IsRunning("E:\Work\Python\GenericAgent\launch.pyw", "E:\Work\Python\GenericAgent\frontends\stapp.py") Then
    shell.Run """" & pythonwPath & """ """ & launchPath & """ --sched", 0, False
End If

If Not IsRunning("E:\Work\Python\GenericAgent\frontends\wechatapp.py", "") Then
    shell.Run """" & pythonwPath & """ """ & wechatPath & """", 0, False
End If

Function IsRunning(primaryPattern, secondaryPattern)
    Dim process, cmd
    IsRunning = False
    For Each process In processes
        If Not IsNull(process.CommandLine) Then
            cmd = process.CommandLine
            If InStr(1, cmd, primaryPattern, vbTextCompare) > 0 Then
                IsRunning = True
                Exit Function
            End If
            If secondaryPattern <> "" Then
                If InStr(1, cmd, secondaryPattern, vbTextCompare) > 0 Then
                    IsRunning = True
                    Exit Function
                End If
            End If
        End If
    Next
End Function
