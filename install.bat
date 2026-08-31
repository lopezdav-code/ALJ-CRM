@echo off
title Installateur ALJ Escalade Manager
chcp 65001 > nul
cd /d "%~dp0"

echo ====================================================
echo    INSTALLATION DU PIPELINE HELLOASSO FFME
echo ====================================================
echo.

:: 1. Vérifier si Python est installé
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ ERREUR : Python n'est pas installé sur ce PC !
    echo.
    echo 👉 Veuillez installer Python, version 3.10 ou supérieure recommandée.
    echo 👉 IMPORTANT : Cochez impérativement la case Add Python.exe to PATH lors de l'installation de Python !
    echo 👉 Téléchargement direct : https://www.python.org/downloads/
    echo.
    echo Appuyez sur une touche pour quitter...
    pause > nul
    exit /b 1
)

:: 2. Création de l'environnement virtuel venv
echo 📦 1. Création de l'environnement virtuel local (venv)...
if exist "venv" (
    echo [Note] Un dossier venv existe déjà. Mise à jour des dépendances...
) else (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo ❌ ERREUR : Impossible de créer l'environnement virtuel.
        echo Assurez-vous d'avoir les permissions nécessaires.
        pause
        exit /b 1
    )
    echo ✅ Environnement virtuel venv créé avec succès.
)
echo.

:: 3. Installation des dépendances
echo 📥 2. Installation des paquets requis depuis requirements.txt...
echo    (Cela peut prendre une minute ou deux, veuillez patienter...)
echo.
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r code_source\requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ❌ ERREUR : L'installation des paquets a échoué.
    echo Vérifiez votre connexion internet et que le fichier 'code_source\requirements.txt' est présent.
    pause
    exit /b 1
)
echo.
echo ✅ Toutes les bibliothèques ont été installées avec succès !
echo.

:: 4. Génération de l'icône de l'application (.ico) à partir du logo
echo 🎨 3. Génération de l'icône de l'application...
venv\Scripts\python.exe -c "from PIL import Image; import os; logo_path = os.path.abspath('logo.png') if os.path.exists('logo.png') else os.path.abspath('code_source/logo.png') if os.path.exists('code_source/logo.png') else None; (Image.open(logo_path).save('logo.ico', format='ICO', sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)]) if logo_path else print('⚠️ Logo non trouvé, l\'icône par défaut sera utilisée.'))" 2>nul
if exist "logo.ico" (
    echo ✅ Icône 'logo.ico' générée avec succès à partir du logo !
) else (
    echo ⚠️ Impossible de générer l'icône, le raccourci utilisera l'icône standard de Python.
)
echo.

:: 5. Création du raccourci sur le Bureau Windows via Python COM
echo 🖥️ 4. Création du raccourci sur le Bureau...
echo Set FSO = CreateObject("Scripting.FileSystemObject") > Lancer_ALJ.vbs
echo scriptPath = FSO.GetParentFolderName(WScript.ScriptFullName) >> Lancer_ALJ.vbs
echo Set WshShell = CreateObject("WScript.Shell") >> Lancer_ALJ.vbs
echo WshShell.CurrentDirectory = scriptPath ^& "\code_source" >> Lancer_ALJ.vbs
echo WshShell.Run "cmd.exe /c run_app.bat", 0, False >> Lancer_ALJ.vbs

echo import os > create_lnk.py
echo import win32com.client >> create_lnk.py
echo current_dir = os.getcwd() >> create_lnk.py
echo desktop = win32com.client.Dispatch("WScript.Shell").SpecialFolders("Desktop") >> create_lnk.py
echo shortcut_path = os.path.join(desktop, "ALJ Escalade Manager.lnk") >> create_lnk.py
echo launcher = os.path.join(current_dir, "Lancer_ALJ.vbs") >> create_lnk.py
echo icon = os.path.join(current_dir, "logo.ico") >> create_lnk.py
echo shell = win32com.client.Dispatch("WScript.Shell") >> create_lnk.py
echo shortcut = shell.CreateShortcut(shortcut_path) >> create_lnk.py
echo shortcut.TargetPath = launcher >> create_lnk.py
echo shortcut.WorkingDirectory = current_dir >> create_lnk.py
echo if os.path.exists(icon): shortcut.IconLocation = icon >> create_lnk.py
echo shortcut.Save() >> create_lnk.py

venv\Scripts\python.exe create_lnk.py >nul 2>&1
if exist "create_lnk.py" del create_lnk.py

echo ✅ Raccourci 'ALJ Escalade Manager' créé sur votre bureau avec l'icône personnalisée du club !
echo 👉 Note : Ce raccourci utilise 'pythonw.exe', ce qui permet de l'épingler à la barre des tâches de Windows.
echo.

:: 6. Succès
echo ====================================================
echo    INSTALLATION TERMINÉE ET RÉUSSIE ! 🎉
echo ====================================================
echo.
echo 👉 Vous pouvez double-cliquer sur le raccourci 'ALJ Escalade Manager' sur votre bureau pour lancer l'application.
echo 👉 L'application s'exécute de façon fluide et moderne, sans ouvrir de console noire en arrière-plan.
echo.
echo Appuyez sur une touche pour fermer cette fenêtre...
pause > nul
