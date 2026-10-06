@echo off
chcp 65001 >nul
title Déploiement ALJ Escalade API sur Google Cloud Run

echo ==============================================================================
echo 🚀 ALJ ESCALADE — Déploiement Cloud Run (0 € / mois)
echo ==============================================================================
echo.

where gcloud >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ ERREUR : La commande 'gcloud' est introuvable sur votre système.
    echo.
    echo Pour déployer sur Google Cloud Run, deux options s'offrent à vous :
    echo   1. Déployer directement depuis le navigateur via Google Cloud Shell
    echo      (Recommandé : 0 installation locale requise, gcloud pré-installé).
    echo      Consultez la documentation : docs/guide_deploiement_cloud_run_helloasso.md
    echo   2. Installer le Google Cloud SDK sur votre PC :
    echo      https://cloud.google.com/sdk/docs/install
    echo.
    pause
    exit /b 1
)

set SERVICE_NAME=alj-escalade-api
set REGION=europe-west1

echo 🔍 Récupération du projet Google Cloud actif...
for /f "tokens=*" %%i in ('gcloud config get-value project 2^>nul') do set CURRENT_PROJECT=%%i

if "%CURRENT_PROJECT%"=="" (
    set CURRENT_PROJECT=alj-2027
)
if "%CURRENT_PROJECT%"=="(unset)" (
    set CURRENT_PROJECT=alj-2027
)

echo.
echo Configuration détectée :
echo   - Projet Google Cloud : %CURRENT_PROJECT%
echo   - Service             : %SERVICE_NAME%
echo   - Région              : %REGION%
echo   - Instances min/max   : 0 min (0€ au repos) / 2 max
echo   - Mémoire             : 512 MiB (Free Tier)
echo.

set /p CONFIRM="Lancer le déploiement sur ce projet ? (O/n) : "
if /i "%CONFIRM%"=="n" (
    echo Déploiement annulé.
    exit /b 0
)

echo.
echo 📦 Envoi du code source et construction de l'image conteneur (Cloud Build)...
echo Cette opération prend généralement 1 à 2 minutes lors du premier déploiement.
echo.

call gcloud run deploy %SERVICE_NAME% ^
    --source . ^
    --project %CURRENT_PROJECT% ^
    --region %REGION% ^
    --platform managed ^
    --allow-unauthenticated ^
    --memory 512Mi ^
    --cpu 1 ^
    --min-instances 0 ^
    --max-instances 2 ^
    --timeout 60

if %errorlevel% neq 0 (
    echo.
    echo ❌ Échec du déploiement Cloud Run.
    echo Vérifiez les droits GCP et l'activation des API requises :
    echo   gcloud services enable run.googleapis.com cloudbuild.googleapis.com
    pause
    exit /b %errorlevel%
)

echo.
echo ==============================================================================
echo ✅ DÉPLOIEMENT RÉUSSI SUR GOOGLE CLOUD RUN !
echo ==============================================================================

for /f "tokens=*" %%u in ('gcloud run services describe %SERVICE_NAME% --project %CURRENT_PROJECT% --region %REGION% --format="value(status.url)" 2^>nul') do set SERVICE_URL=%%u

echo.
echo 🌐 URL publique du service :
echo    %SERVICE_URL%
echo.
echo 📱 Application PWA Mobile Coachs :
echo    %SERVICE_URL%/competitions
echo.
echo 🔔 URL du Webhook à copier dans HelloAsso :
echo    %SERVICE_URL%/webhooks/helloasso
echo.
echo 🏥 Sonde de santé :
echo    %SERVICE_URL%/health
echo.
echo ==============================================================================
echo ⚙️ Pour injecter ou mettre à jour vos identifiants d'API en production :
echo    gcloud run services update %SERVICE_NAME% --region %REGION% --update-env-vars CLIENT_ID=xxx,CLIENT_SECRET=yyy
echo ==============================================================================
echo.
pause
