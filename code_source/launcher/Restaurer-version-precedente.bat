@echo off
rem ============================================================
rem  ALJ Escalade Manager - Restauration de la version precedente
rem  A utiliser si l'application ne demarre plus apres une mise a jour
rem ============================================================
cd /d "%~dp0"

if not exist "runtime\python.exe" (
    echo [ERREUR] Le runtime Python embarque est introuvable ^(dossier runtime^).
    pause
    exit /b 1
)

"runtime\python.exe" "launcher\launcher.py" --rollback
pause
