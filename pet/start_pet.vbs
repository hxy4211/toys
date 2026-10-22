' Double-click to start the Xiaomian pet watchdog (no console window).
' The watchdog keeps running; it launches the pet when DSH is open and
' the pet exits by itself when DSH closes.
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
    MsgBox "Cannot find watchdog.py next to this script.", 48, "Xiaomian Pet"
    WScript.Quit 1
End If

' 0 = hide console, False = do not wait
sh.Run """" & exe & """ """ & py & """", 0, False
