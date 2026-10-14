@echo off
chcp 65001 >nul
title ALJ Escalade - Batch Quotidien Resultats MyCompet

cd /d "%~dp0"

echo ========================================================
echo   ALJ ESCALADE - BATCH QUOTIDIEN RESULTATS MYCOMPET
echo ========================================================
echo.

if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, 'src'); from infrastructure.competition_results_batch_service import CompetitionResultsBatchService; res = CompetitionResultsBatchService.run_daily_batch(); print('\nStatut final :', res.get('status'))"

echo.
echo Batch termine.
