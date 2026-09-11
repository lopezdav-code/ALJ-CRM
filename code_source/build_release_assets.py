"""Construction des livrables de release ALJ Escalade Manager.

Produit, à partir de code_source/ :
  - alj_source_v<VERSION>.zip  : les sources applicatives (mise à jour par le launcher)
  - SHA256SUMS.txt             : empreintes des paquets publiés

Utilisé par la CI (.github/workflows) à chaque tag v*, et localement pour préparer
une release. Le zip de sources contient l'arborescence applicative à plat
(src/, doc/, requirements.txt, VERSION...) — l'updater sait aplatir un éventuel
dossier racine unique.

Usage :
    python build_release_assets.py --out dist_release
    python build_release_assets.py --check-tag v2.0.8
"""
import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile

DEFAULT_REPO = "lopezdav-code/ALJ-CRM"

# Dossiers exclus du paquet de sources (tests/outils de dev/artefacts locaux)
EXCLUDED_DIRS = {
    "tests", "__pycache__", "venv", ".venv", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "build", "dist", "archive", "attestation", "node_modules",
    ".git", ".github", "downloads",
}
# Fichiers exclus (secrets, données locales, journaux, artefacts générés)
EXCLUDED_FILE_SUFFIXES = (
    ".env", ".db", ".db-wal", ".db-shm", ".log", ".pyc",
)
EXCLUDED_FILE_NAMES = {
    ".env", "client_secret_google.json", "check_icon.png", ".gitignore",
}


def _is_excluded_dir(dirname: str) -> bool:
    return dirname in EXCLUDED_DIRS


def _is_excluded_file(filename: str) -> bool:
    if filename in EXCLUDED_FILE_NAMES:
        return True
    return any(filename.endswith(suffix) for suffix in EXCLUDED_FILE_SUFFIXES if suffix.startswith("."))


def stage_source_tree(code_source_dir: str, staging_dir: str) -> str:
    """Copie l'arborescence applicative (code + doc + modèles) en excluant
    tests, secrets, données locales et artefacts. Retourne le chemin de staging."""
    code_source_dir = os.path.abspath(code_source_dir)
    staging_dir = os.path.abspath(staging_dir)
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)
    os.makedirs(staging_dir, exist_ok=True)

    for root, dirs, files in os.walk(code_source_dir):
        rel_root = os.path.relpath(root, code_source_dir)
        # Filtrer les dossiers exclus (en place pour que os.walk ne descende pas)
        dirs[:] = [d for d in dirs if not _is_excluded_dir(d) and not d.startswith(".")]
        for name in files:
            if _is_excluded_file(name):
                continue
            src = os.path.join(root, name)
            dest_dir = staging_dir if rel_root == "." else os.path.join(staging_dir, rel_root)
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(src, os.path.join(dest_dir, name))
    return staging_dir


def build_source_zip(code_source_dir: str, out_dir: str, version: str) -> str:
    """Crée alj_source_v<version>.zip (contenu à plat) et retourne son chemin."""
    if not version:
        raise ValueError("Version vide : impossible de nommer le paquet.")
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f"alj_source_v{version}.zip")
    staging = os.path.join(tempfile.gettempdir(), f"alj_release_staging_{version}")
    try:
        stage_source_tree(code_source_dir, staging)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(staging):
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, staging)
                    zf.write(full, rel)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return zip_path


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sha256_sums(asset_paths, out_path: str) -> str:
    """Écrit SHA256SUMS.txt ('<hash>  <nom>') pour la liste des paquets."""
    lines = []
    for path in asset_paths:
        lines.append(f"{sha256_of(path)}  {os.path.basename(path)}")
    content = "\n".join(lines) + "\n"
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return out_path


def read_version(code_source_dir: str) -> str:
    with open(os.path.join(code_source_dir, "VERSION"), "r", encoding="utf-8") as f:
        return f.read().strip()


def check_tag(tag: str, code_source_dir: str) -> None:
    """Contrôle de cohérence CI : tag ('vX.Y.Z') == VERSION == APP_VERSION."""
    version_file = read_version(code_source_dir)
    sys.path.insert(0, os.path.join(code_source_dir, "src"))
    from domain.constants import APP_VERSION
    problems = []
    tag_version = str(tag or "").lstrip("v")
    if tag_version != version_file:
        problems.append(f"tag '{tag}' != VERSION '{version_file}'")
    if version_file != APP_VERSION:
        problems.append(f"VERSION '{version_file}' != APP_VERSION '{APP_VERSION}'")
    if problems:
        print("❌ Incohérence de version : " + " | ".join(problems))
        print("   Alignez domain/constants.py APP_VERSION, code_source/VERSION et le tag git.")
        sys.exit(1)
    print(f"✅ Cohérence de version vérifiée : {tag} == VERSION == APP_VERSION ({version_file})")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Assets de release ALJ Escalade Manager")
    parser.add_argument("--code-source", default=os.path.dirname(os.path.abspath(__file__)))
    parser.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist_release"))
    parser.add_argument("--check-tag", default=None, help="Vérifie la cohérence tag/VERSION/APP_VERSION puis s'arrête")
    args = parser.parse_args(argv)

    if args.check_tag:
        check_tag(args.check_tag, args.code_source)
        return 0

    version = read_version(args.code_source)
    print(f"📦 [RELEASE] Version {version} — construction du paquet de sources...")
    zip_path = build_source_zip(args.code_source, args.out, version)
    sums_path = write_sha256_sums([zip_path], os.path.join(args.out, "SHA256SUMS.txt"))
    print(f"✅ [RELEASE] {zip_path}")
    print(f"✅ [RELEASE] {sums_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
