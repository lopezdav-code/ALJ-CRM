@echo off
title ALJ Escalade Manager
chcp 65001 > nul
cd /d "%~dp0"

echo ====================================================
echo   LANCEMENT DE ALJ ESCALADE MANAGER (PySide6)
echo ====================================================
echo.

if exist "venv\Scripts\python.exe" (
    echo [Info] Lancement via l'environnement virtuel local...
    venv\Scripts\python.exe src/app.py
) else if exist "..\venv\Scripts\python.exe" (
    echo [Info] Lancement via l'environnement virtuel parent...
    ..\venv\Scripts\python.exe src/app.py
) else (
    echo [Info] Lancement via le Python système...
    python src/app.py
)

echo.
echo ====================================================
echo Appuyez sur une touche pour fermer cette fenetre...
pause > nul
