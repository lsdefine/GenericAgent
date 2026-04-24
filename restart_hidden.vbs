Option Explicit

Dim shell, wmi, fso, logFile, processes
Dim appDir, pythonwPath, launchPath, wechatPath
Dim logPath

appDir = "E:\Work\Python\GenericAgent"
pythonwPath = "C:\ProgramData\anaconda3\pythonw.exe"
launchPath = appDir & "\launch.pyw"
wechatPath = appDir & "\frontends\wechatapp.py"
logPath = appDir & "\restart.log"

Set shell = CreateObject("WScript.Shell")
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set fso = CreateObject("Scripting.FileSystemObject")

' 写日志函数
Sub WriteLog(msg)
    Dim ts
    Set ts = fso.OpenTextFile(logPath, 8, True)
    ts.WriteLine Now() & " " & msg
    ts.Close
End Sub

WriteLog "=== Restart script started ==="

' 1. 先杀子进程（streamlit/stapp），再杀父进程（launch.pyw）
' 2. 使用 taskkill /F /T 强制杀进程树，确保子进程也被杀死
' 3. 增加等待时间到 5 秒，确保端口释放

Dim patterns, pattern, process, cmd
Dim killedPids, pid
killedPids = ""

patterns = Array( _
    "frontends\stapp.py", _
    "reflect\scheduler.py", _
    "webview-exe-name=pythonw.exe", _
    "\launch.pyw", _
    "frontends\wechatapp.py" _
)

' 第一轮：收集所有匹配的 PID
Dim pidsToKill(100), pidCount
pidCount = 0

Set processes = wmi.ExecQuery("SELECT ProcessId, Name, CommandLine FROM Win32_Process WHERE Name='pythonw.exe' OR Name='python.exe'")
For Each process In processes
    If Not IsNull(process.CommandLine) Then
        cmd = process.CommandLine
        For Each pattern In patterns
            If InStr(1, cmd, pattern, vbTextCompare) > 0 Then
                If pidCount < 100 Then
                    pidsToKill(pidCount) = process.ProcessId
                    pidCount = pidCount + 1
                    WriteLog "Found process to kill: PID=" & process.ProcessId & " CMD=" & Left(cmd, 100)
                End If
                Exit For
            End If
        Next
    End If
Next

' 第二轮：按 PID 降序杀死（先杀子进程，通常子进程 PID 更大）
Dim i, j, tempPid
For i = 0 To pidCount - 2
    For j = i + 1 To pidCount - 1
        If CLng(pidsToKill(i)) < CLng(pidsToKill(j)) Then
            tempPid = pidsToKill(i)
            pidsToKill(i) = pidsToKill(j)
            pidsToKill(j) = tempPid
        End If
    Next
Next

' 使用 taskkill /F /T 强制杀进程树
For i = 0 To pidCount - 1
    pid = pidsToKill(i)
    WriteLog "Killing PID=" & pid & " with taskkill /F /T"
    shell.Run "cmd /c taskkill /F /T /PID " & pid & " 2>nul", 0, True
Next

' 额外：通过 taskkill 按镜像名杀死所有 pythonw.exe（保险措施）
shell.Run "cmd /c taskkill /F /IM pythonw.exe /FI ""WINDOWTITLE eq GenericAgent"" 2>nul", 0, True

WriteLog "Killed " & pidCount & " processes, waiting 5 seconds for port release..."

' 等待 5 秒让端口完全释放
WScript.Sleep 5000

' 验证端口是否释放
Dim portFree, portCheck, portCheckFile
portFree = False
portCheckFile = appDir & "\portcheck.tmp"
shell.Run "cmd /c netstat -an | findstr ""18505"" | findstr LISTENING > """ & portCheckFile & """ 2>nul", 0, True
If fso.FileExists(portCheckFile) Then
    Set portCheck = fso.OpenTextFile(portCheckFile, 1)
    If portCheck.ReadAll() = "" Then
        portFree = True
        WriteLog "Port 18505 is free"
    Else
        WriteLog "WARNING: Port 18505 still in use after kill!"
    End If
    portCheck.Close
    fso.DeleteFile portCheckFile
Else
    portFree = True
    WriteLog "Port 18505 is free"
End If

' 启动新实例
shell.CurrentDirectory = appDir
WriteLog "Starting launch.pyw --sched"
shell.Run """" & pythonwPath & """ """ & launchPath & """ --sched", 0, False

WriteLog "Starting wechatapp.py"
shell.Run """" & pythonwPath & """ """ & wechatPath & """", 0, False

WriteLog "=== Restart script completed ==="

Set shell = Nothing
Set wmi = Nothing
Set fso = Nothing
