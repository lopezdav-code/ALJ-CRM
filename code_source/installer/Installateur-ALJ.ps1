# Installateur ALJ Escalade Manager
# ==============================================================================
# Assistant d'installation du pack portable :
#   1. Choix du dossier d'installation + zip ALJ_Portable_v*.zip local,
#      sinon téléchargement automatique depuis la dernière release GitHub
#   2. Saisie des accès obligatoires (HelloAsso, Google Drive, Gmail)
#   3. Extraction, écriture du .env local, raccourci bureau, lancement
# Le .env est créé SUR le poste de l'utilisateur : aucun secret n'est distribué
# dans le zip ni par mail.
# ==============================================================================
param(
    [string]$Dossier,      # mode silencieux : dossier d'installation cible
    [string]$Zip,          # mode silencieux : chemin du zip (sinon détection auto/téléchargement)
    [switch]$Silent        # sans interface : lit ALJCFG_<CLE> dans l'environnement
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ErrorActionPreference = "Stop"
$script:InstallerDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:GitHubRepo = "lopezdav-code/ALJ-CRM"

# --- Accès demandés à l'utilisateur -------------------------------------------
# label affiché | clé .env | masqué ? | obligatoire ?
$script:Champs = @(
    ,@("HelloAsso — Slug de l'association :",              "HELLOASSO_ORG_SLUG",            $false, $true)
    ,@("HelloAsso — Client ID :",                          "HELLOASSO_CLIENT_ID",           $false, $true)
    ,@("HelloAsso — Client Secret :",                      "HELLOASSO_CLIENT_SECRET",       $true,  $true)
    ,@("Google Drive — ID base adhérents (SQLite) :",      "GOOGLE_DRIVE_DB_ID",            $false, $true)
    ,@("Google Drive — ID base compétitions (SQLite) :",   "GOOGLE_DRIVE_COMPETITION_DB_ID", $false, $false)
    ,@("Google Cloud — Client ID :",                       "GMAIL_CLIENT_ID",               $false, $true)
    ,@("Adresse expéditeur Gmail :",                       "GMAIL_USER_EMAIL",              $false, $true)
)

$script:Inputs = @{}
$script:Valeurs = @{}
$script:TxtDossier = $null
$script:ChkLancer = $null
$script:LogBox = $null
$script:BtnInstaller = $null

function Find-PortableZip {
    param([string]$Dossier)
    $candidats = @(
        (Get-ChildItem -LiteralPath $script:InstallerDir -Filter "ALJ_Portable_v*.zip" -File -ErrorAction SilentlyContinue)
        (Get-ChildItem -LiteralPath $Dossier -Filter "ALJ_Portable_v*.zip" -File -ErrorAction SilentlyContinue)
    ) | Where-Object { $_ }
    return ($candidats | Sort-Object Name -Descending | Select-Object -First 1)
}

function Save-PortableZipDepuisGitHub {
    # Télécharge le pack portable depuis la dernière release GitHub (publique)
    # et vérifie son empreinte SHA256 (SHA256SUMS.txt de la release).
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $oldProgress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue" # accélère fortement Invoke-WebRequest
    try {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$script:GitHubRepo/releases/latest" -UseBasicParsing
        $asset = $release.assets | Where-Object { $_.name -like "ALJ_Portable_*.zip" } | Select-Object -First 1
        if (-not $asset) {
            Write-Log "❌ Aucun pack ALJ_Portable_*.zip trouvé dans la dernière release GitHub."
            return $null
        }
        $dossier = Join-Path $env:TEMP "ALJ_Install"
        New-Item -ItemType Directory -Force -Path $dossier | Out-Null
        $dest = Join-Path $dossier $asset.name
        if (Test-Path -LiteralPath $dest) {
            Write-Log "♻️ Pack déjà téléchargé : $($asset.name)"
        } else {
            Write-Log "⬇️ Téléchargement de $($asset.name) ($([Math]::Round($asset.size / 1MB, 1)) Mo)... cela peut prendre plusieurs minutes."
            Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dest -UseBasicParsing
            Write-Log "✅ Téléchargement terminé : $dest"
        }
        # Vérification de l'intégrité (SHA256SUMS.txt de la release)
        $sumsAsset = $release.assets | Where-Object { $_.name -eq "SHA256SUMS.txt" } | Select-Object -First 1
        if ($sumsAsset) {
            try {
                $resp = Invoke-WebRequest -Uri $sumsAsset.browser_download_url -UseBasicParsing
                $sums = if ($resp.Content -is [byte[]]) { [System.Text.Encoding]::UTF8.GetString($resp.Content) } else { [string]$resp.Content }
                $attendu = ($sums -split "`r?`n" | Where-Object {
                        $_ -match "^\s*([0-9a-fA-F]{64})\s+\*?$([regex]::Escape($asset.name))\s*$"
                    } | ForEach-Object { $Matches[1] } | Select-Object -First 1)
                if ($attendu) {
                    $reel = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
                    if ($reel -ne $attendu) {
                        Write-Log "❌ Empreinte SHA256 invalide : le pack téléchargé est corrompu."
                        return $null
                    }
                    Write-Log "✅ Intégrité du pack vérifiée (SHA256)."
                } else {
                    Write-Log "⚠️ Pack absent de SHA256SUMS.txt : intégrité non vérifiée."
                }
            } catch {
                Write-Log "⚠️ Vérification SHA256 impossible : $($_.Exception.Message)"
            }
        }
        return Get-Item -LiteralPath $dest
    } catch {
        Write-Log "❌ Échec du téléchargement depuis GitHub : $($_.Exception.Message)"
        return $null
    } finally {
        $ProgressPreference = $oldProgress
    }
}

function Write-Log {
    param([string]$Message)
    if ($script:LogBox) {
        $script:LogBox.AppendText("$Message`r`n")
        $script:LogBox.SelectionStart = $script:LogBox.TextLength
        $script:LogBox.ScrollToCaret()
        [System.Windows.Forms.Application]::DoEvents()
    }
}

function New-EnvFile {
    param([string]$CheminEnv, [string]$DossierCible)
    $lignes = @("# ALJ Escalade Manager — configuration locale (générée par l'installateur)")
    foreach ($c in $script:Champs) {
        $lignes += "$($c[1])=$($script:Valeurs[$c[1]])"
    }
    [System.IO.File]::WriteAllLines($CheminEnv, $lignes)
    Write-Log "✅ Configuration écrite : $CheminEnv"

    # Raccourci bureau
    try {
        $bureau = [Environment]::GetFolderPath("Desktop")
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut((Join-Path $bureau "ALJ Escalade Manager.lnk"))
        $lnk.TargetPath = Join-Path $DossierCible "Lancer-ALJ.bat"
        $lnk.WorkingDirectory = $DossierCible
        $ico = Join-Path $DossierCible "app\logo.ico"
        if (Test-Path -LiteralPath $ico) { $lnk.IconLocation = $ico }
        $lnk.Save()
        Write-Log "✅ Raccourci bureau créé : ALJ Escalade Manager.lnk"
    } catch {
        Write-Log "⚠️ Raccourci bureau non créé : $($_.Exception.Message)"
    }
}

function Install-ALJ {
    param([string]$DossierChoisi, [string]$ZipForcé)

    $zip = if ($ZipForcé -and (Test-Path -LiteralPath $ZipForcé)) {
        Get-Item -LiteralPath $ZipForcé
    } else {
        Find-PortableZip -Dossier $DossierChoisi
    }
    if (-not $zip) {
        Write-Log "🔍 Aucun pack local trouvé : téléchargement depuis GitHub..."
        $zip = Save-PortableZipDepuisGitHub
    }
    if (-not $zip) {
        if ($Silent) { Write-Error "Aucun fichier ALJ_Portable_v*.zip trouvé ni téléchargeable." }
        else {
            [System.Windows.Forms.MessageBox]::Show(
                "Aucun fichier ALJ_Portable_v*.zip trouvé et le téléchargement depuis GitHub a échoué.`nVérifiez la connexion Internet ou placez le zip à côté de l'installateur.",
                "Archive introuvable", "OK", "Warning") | Out-Null
        }
        return $false
    }

    $btn = $script:BtnInstaller
    if ($btn) { $btn.Enabled = $false }
    try {
        # 1. Extraction (le zip contient un dossier racine ALJ\)
        $cible = Join-Path $DossierChoisi "ALJ"
        if (Test-Path -LiteralPath $cible) {
            $rep = "Yes"
            if (-not $Silent) {
                $rep = [System.Windows.Forms.MessageBox]::Show(
                    "Le dossier $cible existe déjà.`nLe remplacer intégralement ? (votre .env et data\ sont préservés)",
                    "Dossier existant", "YesNo", "Question")
            }
            if ($rep -ne "Yes") { return $false }
            Get-ChildItem -LiteralPath $cible -Exclude ".env", "data" |
                Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        }
        Write-Log "📦 Extraction de $($zip.Name)..."
        $tmp = Join-Path $DossierChoisi "_alj_extract_tmp"
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Recurse -Force }
        Expand-Archive -LiteralPath $zip.FullName -DestinationPath $tmp -Force
        $source = Join-Path $tmp "ALJ"
        if (-not (Test-Path -LiteralPath $source)) { $source = $tmp }
        New-Item -ItemType Directory -Force -Path $cible | Out-Null
        Copy-Item -Path (Join-Path $source "*") -Destination $cible -Recurse -Force
        Remove-Item -LiteralPath $tmp -Recurse -Force
        Write-Log "✅ Application extraite dans $cible"

        # 2. Fichier de configuration .env (racine : préservé par les mises à jour)
        New-EnvFile -CheminEnv (Join-Path $cible ".env") -DossierCible $cible

        # 3. Déblocage SmartScreen des fichiers extraits
        Get-ChildItem -LiteralPath $cible -Recurse -File -ErrorAction SilentlyContinue |
            Unblock-File -ErrorAction SilentlyContinue

        # 4. Connexion automatique Google et téléchargement des bases de données
        Write-Log "🌐 Lancement de l'assistant de connexion Google et de téléchargement des bases de données de référence..."
        $pythonExe = Join-Path $cible "runtime\python.exe"
        $appDir = Join-Path $cible "app"
        if (Test-Path -LiteralPath $pythonExe) {
            # On lance le script de bootstrap de première installation.
            $p = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "src.install_bootstrap") -WorkingDirectory $appDir -Wait -PassThru
            if ($p.ExitCode -ne 0) {
                Write-Log "⚠️ L'initialisation automatique de première installation a échoué ou a été fermée prématurément (Code : $($p.ExitCode))."
            } else {
                Write-Log "✅ Initialisation réussie : Authentification Google complétée et bases de données synchronisées !"
            }
        } else {
            Write-Log "⚠️ Impossible de localiser le runtime Python embarqué ($pythonExe)."
        }

        Write-Log "✅ Installation terminée."

        if ($script:ChkLancer -and $script:ChkLancer.Checked) {
            Start-Process -FilePath (Join-Path $cible "Lancer-ALJ.bat") -WorkingDirectory $cible
        }
        return $true
    } catch {
        if ($Silent) { throw }
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Erreur d'installation",
            "OK", "Error") | Out-Null
        return $false
    } finally {
        if ($btn) { $btn.Enabled = $true }
    }
}

# ==============================================================================
# Mode silencieux (tests / déploiement scripté) : pas d'interface.
# Valeurs lues dans l'environnement : ALJCFG_<CLE> (ex : ALJCFG_HELLOASSO_CLIENT_ID)
# ==============================================================================
if ($Silent) {
    if (-not $Dossier) { Write-Error "Mode -Silent : -Dossier est obligatoire." }
    foreach ($c in $script:Champs) {
        $script:Valeurs[$c[1]] = [Environment]::GetEnvironmentVariable("ALJCFG_" + $c[1])
    }
    $ok = Install-ALJ -DossierChoisi $Dossier -ZipForcé $Zip
    if ($ok) { exit 0 } else { exit 1 }
}

# ==============================================================================
# Interface (assistant une seule fenêtre)
# ==============================================================================
$form = New-Object System.Windows.Forms.Form
$form.Text = "Installateur — ALJ Escalade Manager"
$form.Size = New-Object System.Drawing.Size(640, 640)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false

$title = New-Object System.Windows.Forms.Label
$title.Text = "Installation d'ALJ Escalade Manager"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
$title.Location = New-Object System.Drawing.Point(20, 15)
$title.Size = New-Object System.Drawing.Size(580, 30)
$form.Controls.Add($title)

# --- Dossier d'installation ----------------------------------------------------
$lblDossier = New-Object System.Windows.Forms.Label
$lblDossier.Text = "1. Dossier d'installation :"
$lblDossier.Location = New-Object System.Drawing.Point(20, 55)
$lblDossier.Size = New-Object System.Drawing.Size(400, 20)
$form.Controls.Add($lblDossier)

$script:TxtDossier = New-Object System.Windows.Forms.TextBox
$script:TxtDossier.Text = Join-Path $env:USERPROFILE "Desktop\ALJ"
$script:TxtDossier.Location = New-Object System.Drawing.Point(20, 78)
$script:TxtDossier.Size = New-Object System.Drawing.Size(510, 24)
$form.Controls.Add($script:TxtDossier)

$btnParcourir = New-Object System.Windows.Forms.Button
$btnParcourir.Text = "Parcourir…"
$btnParcourir.Location = New-Object System.Drawing.Point(538, 76)
$btnParcourir.Size = New-Object System.Drawing.Size(80, 27)
$form.Controls.Add($btnParcourir)

# --- Champs de configuration ---------------------------------------------------
$lblAcces = New-Object System.Windows.Forms.Label
$lblAcces.Text = "2. Accès obligatoires (stockés uniquement sur ce poste dans ALJ\.env) :"
$lblAcces.Location = New-Object System.Drawing.Point(20, 112)
$lblAcces.Size = New-Object System.Drawing.Size(590, 20)
$form.Controls.Add($lblAcces)

$y = 138
foreach ($c in $script:Champs) {
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = if ($c[3]) { $c[0].Replace(" :", " * :") } else { $c[0] }
    $lbl.Location = New-Object System.Drawing.Point(20, $y)
    $lbl.Size = New-Object System.Drawing.Size(360, 20)
    $form.Controls.Add($lbl)

    $inp = New-Object System.Windows.Forms.TextBox
    $inp.Location = New-Object System.Drawing.Point(385, ($y - 2))
    $inp.Size = New-Object System.Drawing.Size(233, 24)
    if ($c[2]) { $inp.UseSystemPasswordChar = $true }
    $script:Inputs[$c[1]] = $inp
    $form.Controls.Add($inp)

    $y += 30
}

$note = New-Object System.Windows.Forms.Label
$note.Text = "La connexion Gmail (jeton OAuth2) se fait ensuite dans l'application : Réglages → « Connexion Google (OAuth2) »."
$note.ForeColor = [System.Drawing.Color]::DimGray
$note.Location = New-Object System.Drawing.Point(20, ($y + 2))
$note.Size = New-Object System.Drawing.Size(590, 34)
$form.Controls.Add($note)
$y += 40

# --- Journal -------------------------------------------------------------------
$script:LogBox = New-Object System.Windows.Forms.TextBox
$script:LogBox.Multiline = $true
$script:LogBox.ReadOnly = $true
$script:LogBox.ScrollBars = "Vertical"
$script:LogBox.Font = New-Object System.Drawing.Font("Consolas", 9)
$script:LogBox.Location = New-Object System.Drawing.Point(20, $y)
$script:LogBox.Size = New-Object System.Drawing.Size(598, 150)
$form.Controls.Add($script:LogBox)
$y += 160

# --- Options + bouton ----------------------------------------------------------
$script:ChkLancer = New-Object System.Windows.Forms.CheckBox
$script:ChkLancer.Text = "Lancer l'application après l'installation"
$script:ChkLancer.Checked = $true
$script:ChkLancer.Location = New-Object System.Drawing.Point(20, $y)
$script:ChkLancer.Size = New-Object System.Drawing.Size(340, 24)
$form.Controls.Add($script:ChkLancer)

$script:BtnInstaller = New-Object System.Windows.Forms.Button
$script:BtnInstaller.Text = "Installer"
$script:BtnInstaller.Location = New-Object System.Drawing.Point(460, ($y - 4))
$script:BtnInstaller.Size = New-Object System.Drawing.Size(158, 34)
$script:BtnInstaller.BackColor = [System.Drawing.Color]::FromArgb(16, 185, 129)
$script:BtnInstaller.ForeColor = [System.Drawing.Color]::White
$script:BtnInstaller.FlatStyle = "Flat"
$form.Controls.Add($script:BtnInstaller)

$btnParcourir.Add_Click({
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "Choisissez le dossier d'installation (le sous-dossier ALJ y sera créé)."
    if ($dlg.ShowDialog() -eq "OK") { $script:TxtDossier.Text = $dlg.SelectedPath }
})

$script:BtnInstaller.Add_Click({
    $dossier = $script:TxtDossier.Text.Trim()
    if (-not $dossier) {
        [System.Windows.Forms.MessageBox]::Show("Indiquez le dossier d'installation.", "Dossier manquant",
            "OK", "Warning") | Out-Null
        return
    }
    $manquants = @()
    foreach ($c in $script:Champs) {
        $valeur = $script:Inputs[$c[1]].Text.Trim()
        if ($c[3] -and -not $valeur) { $manquants += $c[1] }
        $script:Valeurs[$c[1]] = $valeur
    }
    if ($manquants) {
        [System.Windows.Forms.MessageBox]::Show(
            "Champs obligatoires vides :`n" + ($manquants -join "`n"),
            "Configuration incomplète", "OK", "Warning") | Out-Null
        return
    }
    try { New-Item -ItemType Directory -Force -Path $dossier | Out-Null } catch {}
    $ok = Install-ALJ -DossierChoisi $dossier
    if ($ok) {
        [System.Windows.Forms.MessageBox]::Show(
            "Installation terminée avec succès !`n`nLa connexion Google (OAuth2) est configurée et vos bases de données ont été téléchargées.",
            "Succès d'installation", "OK", "Information") | Out-Null
        $form.Close()
    }
})

$form.Topmost = $true
$form.Add_Shown({ $form.Activate() })
[void]$form.ShowDialog()
