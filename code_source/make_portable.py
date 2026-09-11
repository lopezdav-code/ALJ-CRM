"""Assemblage du paquet portable ALJ Escalade Manager.

Produit ALJ_Portable_v<VERSION>.zip : un dossier autoportant à extraire n'importe où
(clé USB, Documents...) contenant :
    ALJ/
      runtime/        Python embarqué + dépendances préinstallées (option --no-runtime)
      app/            code applicatif (swappé par le launcher lors des mises à jour)
      data/           données locales (créé vide)
      launcher/       launcher + logique de mise à jour
      Lancer-ALJ.bat, Restaurer-version-precedente.bat, updater.json, updater_state.json

Usage :
    python make_portable.py --out dist_release
    python make_portable.py --no-runtime      # sans Python embarqué (test rapide)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile

import requests

from build_release_assets import (
    DEFAULT_REPO, read_version, sha256_of, stage_source_tree, write_sha256_sums,
)

PYTHON_EMBED_VERSION = "3.13.7"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_EMBED_VERSION}/"
    f"python-{PYTHON_EMBED_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
PORTABLE_DIRNAME = "ALJ"


def download_to_cache(url: str, cache_dir: str, filename: str = None) -> str:
    """Télécharge un fichier dans le cache local (reprise inutile : fichiers petits)."""
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, filename or os.path.basename(url))
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    print(f"⬇️  [PORTABLE] Téléchargement : {url}")
    with requests.get(url, stream=True, timeout=120, headers={"User-Agent": "ALJ-Packaging"}) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    return dest


def _find_free_drive():
    for letter in "ZYXWVUTSRQPONMLKJIHGF":
        if not os.path.exists(f"{letter}:\\"):
            return letter
    return None


class short_path_mount:
    """Mappe temporairement un dossier sur une lettre de lecteur libre (subst) pour
    contourner la limite de 260 caractères de Windows : pip installe PySide6 dont
    certains fichiers QML ont des chemins internes très profonds. Sans droits admin.
    Repli silencieux : si subst échoue, on construit au chemin d'origine."""

    def __init__(self, target: str):
        self.target = os.path.abspath(target)
        self.drive = None

    def __enter__(self):
        if os.name != "nt" or len(self.target) < 50:
            return self.target
        drive = _find_free_drive()
        if not drive:
            return self.target
        try:
            subprocess.run(["subst", f"{drive}:", self.target], check=True, capture_output=True, timeout=30)
            self.drive = drive
            return f"{drive}:\\"
        except Exception:
            self.drive = None
            return self.target

    def __exit__(self, *exc):
        if self.drive:
            try:
                subprocess.run(["subst", f"{self.drive}:", "/D"], capture_output=True, timeout=30)
            except Exception:
                pass
        return False


def patch_embedded_pth(runtime_dir: str):
    """Active site-packages dans le Python embarqué (fichier pythonXXX._pth)."""
    import glob
    pth_files = glob.glob(os.path.join(runtime_dir, "python*._pth"))
    if not pth_files:
        raise RuntimeError("Fichier python*._pth introuvable dans le runtime embarqué.")
    path = pth_files[0]
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    lines = [("#import site" if ln.strip() == "#import site" else ln) for ln in lines]
    if not any(ln.strip().lower() == "import site" for ln in lines):
        lines.append("import site")
    if not any("site-packages" in ln for ln in lines):
        lines.append(os.path.join("Lib", "site-packages"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def prepare_runtime(staging_root: str, cache_dir: str, requirements_path: str):
    """Construit runtime/ : Python embarqué + pip + dépendances préinstallées."""
    runtime_dir = os.path.join(staging_root, "runtime")
    if os.path.exists(runtime_dir):
        shutil.rmtree(runtime_dir)
    os.makedirs(runtime_dir, exist_ok=True)

    embed_zip = download_to_cache(PYTHON_EMBED_URL, cache_dir)
    with zipfile.ZipFile(embed_zip, "r") as zf:
        zf.extractall(runtime_dir)
    patch_embedded_pth(runtime_dir)

    python_exe = os.path.join(runtime_dir, "python.exe")
    get_pip = download_to_cache(GET_PIP_URL, cache_dir)
    print("🧰 [PORTABLE] Installation de pip dans le runtime embarqué...")
    subprocess.run([python_exe, get_pip, "--no-warn-script-location", "--quiet"], check=True, timeout=600)

    print("📚 [PORTABLE] Installation des dépendances dans le runtime (plusieurs minutes)...")
    subprocess.run(
        [python_exe, "-m", "pip", "install", "-r", requirements_path,
         "--quiet", "--disable-pip-version-check"],
        check=True, timeout=3600,
    )
    return runtime_dir


def assemble(code_source_dir: str, out_dir: str, cache_dir: str,
             with_runtime: bool = True, sums_path: str = None) -> str:
    """Assemble le dossier portable complet et le compresse. Retourne le chemin du zip."""
    version = read_version(code_source_dir)
    build_root = os.path.join(code_source_dir, "build", "portable_staging")
    if os.path.exists(build_root):
        shutil.rmtree(build_root, ignore_errors=True)
    os.makedirs(build_root, exist_ok=True)  # doit exister pour le montage subst

    # 1..4 via un chemin court (subst) : les dépendances PySide6/QML dépassent la
    # limite de 260 caractères de Windows depuis une arborescence profonde.
    with short_path_mount(build_root) as short_build_root:
        staging = os.path.join(short_build_root, PORTABLE_DIRNAME)

        # 1. Application (code + doc + modèles, sans tests/secret/données locales)
        app_dir = os.path.join(staging, "app")
        stage_source_tree(code_source_dir, app_dir)

        # 2. Launcher (jamais mis à jour automatiquement : volontairement stable)
        launcher_src = os.path.join(code_source_dir, "launcher")
        launcher_dst = os.path.join(staging, "launcher")
        os.makedirs(launcher_dst, exist_ok=True)
        for name in os.listdir(launcher_src):
            if name.endswith(".py"):
                shutil.copy2(os.path.join(launcher_src, name), os.path.join(launcher_dst, name))
        for name in ("Lancer-ALJ.bat", "Restaurer-version-precedente.bat"):
            shutil.copy2(os.path.join(launcher_src, name), os.path.join(staging, name))

        # 3. Données locales (vide) + configuration de l'updater
        os.makedirs(os.path.join(staging, "data"), exist_ok=True)
        with open(os.path.join(staging, "updater.json"), "w", encoding="utf-8") as f:
            json.dump({"repo": DEFAULT_REPO}, f, ensure_ascii=False, indent=2)
        req_hash = sha256_of(os.path.join(app_dir, "requirements.txt"))
        with open(os.path.join(staging, "updater_state.json"), "w", encoding="utf-8") as f:
            json.dump({"requirements_sha256": req_hash}, f, ensure_ascii=False, indent=2)

        # 4. Runtime Python embarqué
        if with_runtime:
            prepare_runtime(staging, cache_dir, os.path.join(app_dir, "requirements.txt"))

        # 5. Compression (dans le montage : les chemins PySide6/QML dépassent sinon 260)
        out_dir_abs = os.path.abspath(out_dir)
        os.makedirs(out_dir_abs, exist_ok=True)
        zip_path = os.path.join(out_dir_abs, f"ALJ_Portable_v{version}.zip")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        print(f"🗜️  [PORTABLE] Compression de {staging}...")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(staging):
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, staging)
                    zf.write(full, os.path.join(PORTABLE_DIRNAME, rel))
        print(f"✅ [PORTABLE] {zip_path} ({os.path.getsize(zip_path) // (1024 * 1024)} Mo)")

    if sums_path:
        zips = sorted(
            os.path.join(out_dir, n) for n in os.listdir(out_dir)
            if n.endswith(".zip")
        )
        write_sha256_sums(zips, sums_path)
        print(f"✅ [PORTABLE] {sums_path}")

    shutil.rmtree(build_root, ignore_errors=True)
    return zip_path


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Assemblage du paquet portable ALJ Escalade Manager")
    parser.add_argument("--code-source", default=here)
    parser.add_argument("--out", default=os.path.join(here, "dist_release"))
    parser.add_argument("--cache", default=os.path.join(here, "build", "downloads"))
    parser.add_argument("--sums", default=None, help="Chemin du SHA256SUMS.txt à (re)générer")
    parser.add_argument("--no-runtime", action="store_true", help="Sans Python embarqué (assemblage rapide)")
    args = parser.parse_args(argv)

    zip_path = assemble(
        args.code_source, args.out, args.cache,
        with_runtime=not args.no_runtime, sums_path=args.sums,
    )
    return 0 if os.path.exists(zip_path) else 1


if __name__ == "__main__":
    sys.exit(main())
