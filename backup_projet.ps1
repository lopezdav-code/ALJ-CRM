# ============================================================
#  Sauvegarde ZIP du projet ALJ-CRM
#  - Exclut les environnements virtuels (venv), caches et builds
#  - Conserve : code, BDD, .env, logs, imports, exports, docs, .git
#  Usage :
#    .\backup_projet.ps1                        -> zip sur le Bureau
#    .\backup_projet.ps1 -Destination "E:\"     -> zip sur la cle USB
# ============================================================
param(
    [string]$Destination = [Environment]::GetFolderPath('Desktop')
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- Verification de la destination ---
if (-not (Test-Path -LiteralPath $Destination)) {
    Write-Host "Destination introuvable : $Destination" -ForegroundColor Red
    exit 1
}

$ZipName = "ALJ-CRM_backup_{0}.zip" -f (Get-Date -Format 'yyyyMMdd_HHmm')
$ZipPath = Join-Path $Destination $ZipName
$Stage   = Join-Path $env:TEMP ("alj_backup_stage_" + (Get-Date -Format 'HHmmss'))

# --- Repertoires exclus (par nom, partout dans l'arborescence) ---
$ExcludedDirs = @('venv', 'node_modules', '__pycache__', '.pytest_cache', '.ruff_cache', '.tox', 'dist', 'build')
# --- Fichiers exclus ---
$ExcludedFiles = @('*.zip', '*.pyc')

Write-Host "Projet   : $ProjectRoot"
Write-Host "Exclusion: $($ExcludedDirs -join ', ')"
Write-Host "Copie en cours..."

# --- Copie vers un repertoire temporaire avec exclusions (robocopy) ---
robocopy $ProjectRoot $Stage /E /XD $ExcludedDirs /XF $ExcludedFiles /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "Echec de la copie (robocopy code $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

# --- Creation du zip ---
Write-Host "Compression en cours..."
$Items = Get-ChildItem -LiteralPath $Stage -Force
Compress-Archive -Path $Items.FullName -DestinationPath $ZipPath -CompressionLevel Optimal

# --- Nettoyage ---
Remove-Item -LiteralPath $Stage -Recurse -Force

# --- Rapport ---
$ZipKo   = [math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1KB)
$TotalMo = [math]::Round($ZipKo / 1024, 1)
Write-Host ""
Write-Host "Sauvegarde terminee : $ZipPath" -ForegroundColor Green
Write-Host ("Taille du zip : {0:N0} Ko ({1} Mo)" -f $ZipKo, $TotalMo)
