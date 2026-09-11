"""Launcher / updater de l'application ALJ Escalade Manager (mode portable).

Point d'entrée utilisateur : vérifie la disponibilité d'une nouvelle version sur
GitHub, applique la mise à jour (sources uniquement) puis lance l'application.
Sans réseau ou en cas d'erreur, l'application locale démarre quand même.

Usage :
    python launcher.py            # vérification + lancement
    python launcher.py --skip-update   # lancement direct sans vérification
    python launcher.py --rollback      # restaurer la version précédente (app_old)
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import updater_core as uc

APP_LAUNCH_RELPATH = os.path.join("app", "src", "app.py")


def portable_root():
    """Racine du dossier portable : parent du dossier launcher/ (indépendant du CWD)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def launch_app(root):
    """Démarre l'application (pythonw : aucune console) et retourne immédiatement."""
    app_script = os.path.join(root, APP_LAUNCH_RELPATH)
    if not os.path.isfile(app_script):
        print(f"❌ [LAUNCHER] Application introuvable : {app_script}")
        return False
    pythonw = uc.find_runtime_python(root, windowed=True)
    subprocess.Popen([pythonw, app_script], cwd=root, close_fds=True)
    return True


def do_rollback(root):
    print("↩️  [LAUNCHER] Restauration de la version précédente (app_old)...")
    uc.rollback_to_previous(root)
    print("✅ [LAUNCHER] Version précédente restaurée. Vous pouvez relancer l'application.")


def run_update_if_available(root):
    """Vérifie et applique la mise à jour. Ne lève jamais : retourne un message d'état."""
    config = uc.load_config(root)
    repo = config.get("repo") or uc.DEFAULT_CONFIG["repo"]
    app_dir = os.path.join(root, uc.APP_DIRNAME)
    current = uc.read_app_version(app_dir)
    print(f"🔍 [LAUNCHER] Version installée : {current} — vérification des mises à jour ({repo})...")

    release = uc.fetch_latest_release(repo)
    latest = uc.release_version(release)
    if not uc.is_newer(latest, current):
        print(f"✅ [LAUNCHER] Application déjà à jour (dernière version publiée : {latest or '?'}).")
        return

    asset = uc.pick_source_asset(release, latest)
    if not asset:
        print(f"⚠️ [LAUNCHER] Release {latest} publiée sans paquet de sources : mise à jour ignorée.")
        return

    tmp_dir = os.path.join(root, "updates_tmp")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)
    zip_path = os.path.join(tmp_dir, asset["name"])
    print(f"⬇️  [LAUNCHER] Téléchargement de {asset['name']} ({asset.get('size', 0) // 1024} Ko)...")
    uc.download_file(asset["browser_download_url"], zip_path)

    # Vérification de l'empreinte si un fichier SHA256SUMS.txt accompagne la release
    sums_asset = next((a for a in release.get("assets", []) if a.get("name") == uc.SUMS_ASSET_NAME), None)
    if sums_asset:
        sums_path = os.path.join(tmp_dir, uc.SUMS_ASSET_NAME)
        uc.download_file(sums_asset["browser_download_url"], sums_path)
        with open(sums_path, "r", encoding="utf-8", errors="replace") as f:
            if not uc.verify_download(zip_path, f.read()):
                raise RuntimeError("Empreinte SHA-256 du paquet invalide (téléchargement corrompu ?).")
        print("🔒 [LAUNCHER] Empreinte SHA-256 vérifiée.")

    new_dir = os.path.join(root, uc.APP_NEW_DIRNAME)
    print("📦 [LAUNCHER] Extraction du paquet...")
    uc.extract_zip_flat(zip_path, new_dir)
    uc.sanity_check_app(new_dir)
    if uc.read_app_version(new_dir) != latest:
        print(f"⚠️ [LAUNCHER] Version du paquet inattendue ({uc.read_app_version(new_dir)} != {latest}), mise à jour ignorée.")
        return

    print("🔁 [LAUNCHER] Bascule vers la nouvelle version...")
    uc.swap_app_folders(root)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    runtime_python = uc.find_runtime_python(root)
    uc.pip_sync(runtime_python, app_dir, root)
    print(f"🎉 [LAUNCHER] Mise à jour appliquée : {current} -> {latest}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = portable_root()

    if "--rollback" in argv:
        try:
            do_rollback(root)
        except Exception as e:
            print(f"❌ [LAUNCHER] Échec de la restauration : {e}")
        return 0

    try:
        if "--skip-update" not in argv:
            run_update_if_available(root)
    except Exception as e:
        print(f"⚠️ [LAUNCHER] Mise à jour impossible ({e}) — lancement de la version installée.")

    if not launch_app(root):
        print("❌ [LAUNCHER] Lancement impossible. Utilisez 'Restaurer-version-precedente.bat' si le problème persiste.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
