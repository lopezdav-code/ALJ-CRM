import os
import sys
import shutil
import subprocess

print("====================================================")
print("   ALJ ESCALADE MANAGER - PACKAGING (.EXE) v1.5.0   ")
print("====================================================")
print()

# Chemins de travail
CODE_SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(CODE_SOURCE_DIR)

# Résoudre le chemin de pyinstaller.exe de manière dynamique
pyinstaller_path = os.path.join(WORKSPACE_DIR, "venv", "Scripts", "pyinstaller.exe")
if not os.path.exists(pyinstaller_path):
    pyinstaller_path = os.path.join(CODE_SOURCE_DIR, "venv", "Scripts", "pyinstaller.exe")

if not os.path.exists(pyinstaller_path):
    print("❌ Erreur : pyinstaller.exe est introuvable. Veuillez d'abord l'installer.")
    sys.exit(1)

# 1. Compilation via PyInstaller
print("⚡ Étape 1 : Compilation de l'exécutable avec PyInstaller...")
cmd = [
    pyinstaller_path,
    "--onefile",
    "--windowed",
    "--name=ALJ_Escalade_Manager",
    f"--icon=logo.ico",
    "--paths=src",
    "--add-data=.env;.",
    "src/app.py"
]

print(f"Exécution de la commande : {' '.join(cmd)}")
try:
    subprocess.run(cmd, check=True)
    print("✅ Compilation PyInstaller terminée avec succès !")
except subprocess.CalledProcessError as e:
    print(f"❌ Échec de la compilation PyInstaller : {e}")
    sys.exit(1)

# 2. Création du dossier de livraison autonome
print()
print("📁 Étape 2 : Création du dossier de livraison autonome...")
PARENT_DIR = os.path.dirname(WORKSPACE_DIR)  # Au-dessus de la racine du projet
release_dir = os.path.join(PARENT_DIR, "ALJ_Escalade_Manager_v1.5.0")

try:
    if os.path.exists(release_dir):
        # Essayer de nettoyer, mais ne pas crasher si des fichiers de doc sont verrouillés
        try:
            shutil.rmtree(release_dir)
            os.makedirs(release_dir)
        except Exception as rmtree_err:
            print(f"⚠️ [WARNING] Impossible de supprimer complètement le dossier existant (fichiers verrouillés) : {rmtree_err}")
            print("  -> Nous allons surcharger directement l'exécutable et les fichiers de configuration.")
    else:
        os.makedirs(release_dir)
except Exception as mkdir_err:
    print(f"⚠️ Erreur de création du dossier : {mkdir_err}")

# Copie de l'exécutable
src_exe = os.path.join(CODE_SOURCE_DIR, "dist", "ALJ_Escalade_Manager.exe")
dst_exe = os.path.join(release_dir, "ALJ_Escalade_Manager.exe")
try:
    shutil.copy2(src_exe, dst_exe)
    print(f"  -> Exécutable copié dans : {dst_exe}")
except Exception as exe_err:
    print(f"❌ Impossible de copier l'exécutable (il est probablement en cours d'exécution !) : {exe_err}")
    print("Veuillez fermer ALJ Escalade Manager puis relancer le script de packaging.")
    sys.exit(1)

# Copie du dossier 'doc'
src_doc = os.path.join(WORKSPACE_DIR, "doc")
dst_doc = os.path.join(release_dir, "doc")
if os.path.exists(src_doc):
    try:
        shutil.copytree(src_doc, dst_doc, dirs_exist_ok=True)
        print("  -> Dossier des modèles 'doc' copié.")
    except Exception as doc_err:
        print(f"⚠️ Impossible de copier le dossier 'doc' : {doc_err}")

# Copie des icônes (le modèle Excel de présence est inclus via le dossier 'doc/template')
files_to_copy = [
    "logo.png",
    "logo.ico"
]

for filename in files_to_copy:
    src_file = os.path.join(WORKSPACE_DIR, filename)
    if os.path.exists(src_file):
        shutil.copy2(src_file, os.path.join(release_dir, filename))
        print(f"  -> Fichier de configuration '{filename}' copié.")

# Créer un fichier de configuration .env de base pour l'utilisateur
src_env = os.path.join(CODE_SOURCE_DIR, ".env")
dst_env = os.path.join(release_dir, ".env")
if os.path.exists(src_env):
    shutil.copy2(src_env, dst_env)
    print("  -> Fichier de configuration de secours '.env' copié.")

print()
print("====================================================")
print(" 🎉 PACKAGING EN EXÉCUTABLE TERMINÉ AVEC SUCCÈS !")
print(f" Dossier de livraison prêt dans : {release_dir}")
print("====================================================")
