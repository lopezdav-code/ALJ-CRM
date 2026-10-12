@echo off
title ALJ Escalade - Serveur Web Local
chcp 65001 > nul
cd /d "%~dp0"

echo ====================================================
echo   LANCEMENT DU SERVEUR WEB LOCAL ALJ ESCALADE
echo ====================================================
echo.
echo URL du portail Bureau : http://127.0.0.1:8000/bureau/
echo URL Compétitions     : http://127.0.0.1:8000/competitions
echo URL Annuaire         : http://127.0.0.1:8000/index
echo Documentation API    : http://127.0.0.1:8000/docs
echo.

start "" "http://127.0.0.1:8000/bureau/"

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -m uvicorn server:app --app-dir src --host 127.0.0.1 --port 8000 --reload
) else if exist "..\venv\Scripts\python.exe" (
    ..\venv\Scripts\python.exe -m uvicorn server:app --app-dir src --host 127.0.0.1 --port 8000 --reload
) else (
    python -m uvicorn server:app --app-dir src --host 127.0.0.1 --port 8000 --reload
)

pause
