' 双击我启动小面宝宝桌宠（不弹黑框）
Option Explicit
Dim fso, sh, base, py, exe
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base

exe = "D:\python\pythonw.exe"
If Not fso.FileExists(exe) Then exe = "pythonw.exe"

py = base & "\pet.py"
If Not fso.FileExists(py) Then
    MsgBox "找不到 pet.py，请确认脚本和 pet.py 在同一目录", 48, "小面宝宝"
    WScript.Quit 1
End If

' 0 = 隐藏控制台窗口, False = 不等待退出
sh.Run """" & exe & """ """ & py & """", 0, False
