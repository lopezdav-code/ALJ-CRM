Set FSO = CreateObject("Scripting.FileSystemObject") 
scriptPath = FSO.GetParentFolderName(WScript.ScriptFullName) 
If FSO.FileExists(scriptPath & "\run_app.bat") Then 
    workDir = scriptPath 
ElseIf FSO.FileExists(scriptPath & "\code_source\run_app.bat") Then 
    workDir = scriptPath & "\code_source" 
Else 
    workDir = scriptPath 
End If 
Set WshShell = CreateObject("WScript.Shell") 
WshShell.CurrentDirectory = workDir 
WshShell.Run "cmd.exe /c run_app.bat", 0, False 
