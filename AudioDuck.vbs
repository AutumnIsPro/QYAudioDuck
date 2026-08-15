Option Explicit
Dim shell, fso, dir
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = dir

' 1) check run environment
If Not fso.FolderExists(dir & "\.venv") Then
    MsgBox "Run environment (.venv) not found." & vbCrLf & "Please double-click run.bat once to initialize.", vbExclamation, "Audio Duck"
    WScript.Quit
End If

' 2) launch the GUI immediately, without any console window
shell.Run ".venv\Scripts\pythonw.exe main.py", 0, False
