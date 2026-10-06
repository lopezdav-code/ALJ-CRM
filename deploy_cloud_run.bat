@echo off
chcp 65001 >nul
cd /d "%~dp0code_source"
call deploy_cloud_run.bat
