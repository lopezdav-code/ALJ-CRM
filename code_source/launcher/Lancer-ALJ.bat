@echo off
rem ============================================================
rem  ALJ Escalade Manager - Lanceur (avec mise a jour au demarrage)
rem  Dossier portable : ce fichier reste a la racine du dossier ALJ
rem ============================================================
cd /d "%~dp0"

if not exist "runtime\python.exe" (
    echo [ERREUR] Le runtime Python embarque est introuvable ^(dossier runtime^).
    echo Reinstallez le dossier portable complet depuis la page des releases.
    pause
    exit /b 1
)

rem Leve eventuel marquage de telechargement Windows (SmartScreen) sur les fichiers applicatifs
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path 'app','launcher' -Recurse -File -ErrorAction SilentlyContinue | Unblock-File" >nul 2>&1

"runtime\python.exe" "launcher\launcher.py"
