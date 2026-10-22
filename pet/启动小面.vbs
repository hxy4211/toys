' 双击我：启动小面宝宝的守护进程（无黑框）
' 守护进程常驻后台，检测到 DSH 打开就拉起桌宠；DSH 关闭时桌宠自己退出
Option Explicit
Dim fso, sh, base, py, exe
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base

exe = "D:\python\pythonw.exe"
If Not fso.FileExists(exe) Then exe = "pythonw.exe"

py = base & "\watchdog.py"
If Not fso.FileExists(py) Then
    MsgBox "找不到 watchdog.py，请确认它和本脚本在同一目录", 48, "小面宝宝"
    WScript.Quit 1
End If

' 0 = 隐藏控制台窗口, False = 不等待退出
sh.Run """" & exe & """ """ & py & """", 0, False
