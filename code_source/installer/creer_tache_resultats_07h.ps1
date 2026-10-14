# Script PowerShell pour planifier l'exécution quotidienne du batch résultats à 07h00
# Sous Windows Task Scheduler (Planificateur de tâches)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CodeSourceDir = Resolve-Path "$ScriptDir\.."
$BatchPath = Join-Path $CodeSourceDir "run_batch_resultats.bat"
$TaskName = "ALJ_Escalade_Batch_Resultats_07h"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Planification Batch Résultats MyCompet ALJ Escalade (07h)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $BatchPath)) {
    Write-Host "Erreur : Fichier batch introuvable : $BatchPath" -ForegroundColor Red
    Exit 1
}

Write-Host "Cible : $BatchPath" -ForegroundColor White
Write-Host "Nom de la tâche : $TaskName" -ForegroundColor White
Write-Host "Fréquence : Tous les jours à 07h00" -ForegroundColor White
Write-Host ""

try {
    # 1. Action : lancer le fichier .bat
    $Action = New-ScheduledTaskAction -Execute $BatchPath -WorkingDirectory $CodeSourceDir

    # 2. Déclencheur : Quotidien à 07h00
    $Trigger = New-ScheduledTaskTrigger -Daily -At 7:00am

    # 3. Paramètres : réveil si possible, redémarrage en cas d'échec
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

    # 4. Enregistrement de la tâche pour l'utilisateur courant
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Batch quotidien ALJ Escalade : recherche des résultats MyCompet FFME et envoi d'e-mail récapitulatif." -Force | Out-Null

    Write-Host "Succès : La tâche planifiée « $TaskName » a été configurée avec succès !" -ForegroundColor Green
    Write-Host "Elle s'exécutera automatiquement chaque matin à 07h00." -ForegroundColor Green
} catch {
    Write-Host "Erreur lors de l'enregistrement de la tâche planifiée : $_" -ForegroundColor Red
}
