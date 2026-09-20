@echo off
rem ============================================================
rem  ALJ Escalade Manager - Installateur (assistant graphique)
rem  Extrait le pack portable et configure les acces locaux (.env)
rem ============================================================
cd /d "%~dp0"

rem Neutraliser le marquage "telecharge du web" de l'assistant (SmartScreen)
powershell -NoProfile -Command "Unblock-File -LiteralPath '%~dp0Installateur-ALJ.ps1' -ErrorAction SilentlyContinue" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Installateur-ALJ.ps1"
