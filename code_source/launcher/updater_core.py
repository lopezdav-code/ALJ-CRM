"""Logique de mise à jour automatique de l'application ALJ Escalade Manager (mode portable).

Le launcher vérifie la dernière release GitHub du projet, télécharge le zip des
sources (alj_source_vX.Y.Z.zip), vérifie son empreinte SHA256, remplace le dossier
app/ de manière réversible (swap atomique + rollback), resynchronise les dépendances
pip si requirements.txt a changé, puis lance l'application.

Ce module est volontairement autonome (stdlib + requests uniquement) : il ne doit
JAMAIS importer le code applicatif (src/) qu'il est chargé de mettre à jour.
"""
import hashlib
import json
import os
import shutil
import zipfile

import requests

GITHUB_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
SOURCE_ASSET_PREFIX = "alj_source_v"
SUMS_ASSET_NAME = "SHA256SUMS.txt"
APP_DIRNAME = "app"
APP_OLD_DIRNAME = "app_old"
APP_NEW_DIRNAME = "app_new"
STATE_FILENAME = "updater_state.json"
CONFIG_FILENAME = "updater.json"
DEFAULT_CONFIG = {"repo": "lopezdav-code/ALJ-CRM"}
REQUEST_TIMEOUT = 30
DOWNLOAD_CHUNK = 1 << 16


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
def parse_version(text):
    """Convertit 'v2.0.10', '2.0.10' ou '2.0' en tuple d'entiers (None si illisible)."""
    raw = str(text or "").strip().lower().lstrip("v")
    parts = raw.split(".")
    try:
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return None


def is_newer(candidate, current):
    """True si la version candidate est strictement plus récente que la version courante."""
    c, k = parse_version(candidate), parse_version(current)
    if c is None or k is None:
        return False
    size = max(len(c), len(k))
    c += (0,) * (size - len(c))
    k += (0,) * (size - len(k))
    return c > k


# ---------------------------------------------------------------------------
# Configuration et état
# ---------------------------------------------------------------------------
def load_config(portable_root):
    """Charge updater.json à la racine du dossier portable (repli : config par défaut)."""
    config = dict(DEFAULT_CONFIG)
    path = os.path.join(portable_root, CONFIG_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            config.update(user)
    except Exception:
        pass
    return config


def read_app_version(app_dir):
    """Lit le fichier VERSION du dossier app/ (ou '0.0.0' si absent)."""
    try:
        with open(os.path.join(app_dir, "VERSION"), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"


def state_path(portable_root):
    return os.path.join(portable_root, STATE_FILENAME)


def load_state(portable_root):
    try:
        with open(state_path(portable_root), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(portable_root, state):
    try:
        with open(state_path(portable_root), "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ [UPDATER] Impossible d'écrire l'état : {e}")


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------
def fetch_latest_release(repo):
    """Interroge l'API GitHub 'latest release' et retourne le payload JSON."""
    url = GITHUB_API_LATEST.format(repo=repo)
    response = requests.get(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ALJ-Escalade-Updater"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"API GitHub HTTP {response.status_code} pour {url}")
    return response.json()


def release_version(release):
    """Extrait la version d'un payload release ('v2.0.9' -> '2.0.9')."""
    return str((release or {}).get("tag_name") or "").strip().lstrip("v")


def pick_source_asset(release, version):
    """Sélectionne l'asset du zip de sources : nom exact attendu, sinon préfixe."""
    assets = (release or {}).get("assets") or []
    exact = f"{SOURCE_ASSET_PREFIX}{version}.zip"
    for asset in assets:
        if asset.get("name") == exact:
            return asset
    for asset in assets:
        if str(asset.get("name") or "").startswith(SOURCE_ASSET_PREFIX) and asset.get("name").endswith(".zip"):
            return asset
    return None


# ---------------------------------------------------------------------------
# Téléchargement / vérification / extraction
# ---------------------------------------------------------------------------
def download_file(url, dest_path, timeout=120):
    """Télécharge un fichier en flux (robuste pour de gros fichiers)."""
    response = requests.get(url, stream=True, timeout=timeout,
                            headers={"User-Agent": "ALJ-Escalade-Updater"})
    if response.status_code != 200:
        raise RuntimeError(f"Téléchargement HTTP {response.status_code} : {url}")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK):
            if chunk:
                f.write(chunk)
    return dest_path


def sha256_of(path):
    """Calcule l'empreinte SHA-256 d'un fichier."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256sums(text):
    """Analyse un fichier SHA256SUMS ('<hash>  <nom>' par ligne) -> {nom: hash}."""
    sums = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            sums[parts[1].strip().lstrip("*")] = parts[0].strip().lower()
    return sums


def verify_download(zip_path, sums_text):
    """Vérifie l'empreinte du zip contre SHA256SUMS (True si la somme est absente)."""
    sums = parse_sha256sums(sums_text)
    if not sums:
        return True
    expected = sums.get(os.path.basename(zip_path))
    if not expected:
        return True
    return sha256_of(zip_path).lower() == expected


def extract_zip_flat(zip_path, dest_dir):
    """Extrait un zip en aplatissant un éventuel dossier racine unique."""
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        top_levels = {n.split("/")[0] for n in names if n.strip()}
        single_root = len(top_levels) == 1 and all(
            n == list(top_levels)[0] or n.startswith(list(top_levels)[0] + "/") for n in names
        )
        if single_root:
            prefix = list(top_levels)[0] + "/"
            for info in zf.infolist():
                if info.filename == list(top_levels)[0]:
                    continue
                target = os.path.join(dest_dir, info.filename[len(prefix):])
                if info.is_dir() or info.filename.endswith("/"):
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        else:
            zf.extractall(dest_dir)


# ---------------------------------------------------------------------------
# Installation (swap réversible)
# ---------------------------------------------------------------------------
def sanity_check_app(app_dir):
    """Vérifications rapides avant bascule : VERSION présent + sources compilables."""
    if not os.path.isfile(os.path.join(app_dir, "VERSION")):
        raise RuntimeError("Le paquet téléchargé ne contient pas de fichier VERSION.")
    import compileall
    src_dir = os.path.join(app_dir, "src")
    if os.path.isdir(src_dir) and not compileall.compile_dir(src_dir, quiet=2, force=True):
        raise RuntimeError("Des fichiers Python du paquet sont invalides (échec de compilation).")


def swap_app_folders(portable_root):
    """Bascule app_new/ -> app/ en conservant l'ancienne version dans app_old/.
    En cas d'échec de la bascule, l'ancienne version est restaurée (rollback)."""
    app_dir = os.path.join(portable_root, APP_DIRNAME)
    old_dir = os.path.join(portable_root, APP_OLD_DIRNAME)
    new_dir = os.path.join(portable_root, APP_NEW_DIRNAME)

    if not os.path.isdir(new_dir):
        raise RuntimeError("Aucun dossier app_new/ à installer.")

    if os.path.isdir(old_dir):
        shutil.rmtree(old_dir, ignore_errors=True)

    had_previous = os.path.isdir(app_dir)
    if had_previous:
        os.rename(app_dir, old_dir)
    try:
        os.rename(new_dir, app_dir)
    except Exception:
        # Rollback : restaurer l'ancienne version telle quelle
        if had_previous and os.path.isdir(old_dir) and not os.path.isdir(app_dir):
            os.rename(old_dir, app_dir)
        raise


def rollback_to_previous(portable_root):
    """Restaure app_old/ comme version active (l'app actuelle est mise de côté)."""
    app_dir = os.path.join(portable_root, APP_DIRNAME)
    old_dir = os.path.join(portable_root, APP_OLD_DIRNAME)
    if not os.path.isdir(old_dir):
        raise RuntimeError("Aucune version précédente (app_old/) disponible.")
    broken_dir = os.path.join(portable_root, APP_DIRNAME + "_broken")
    if os.path.isdir(broken_dir):
        shutil.rmtree(broken_dir, ignore_errors=True)
    if os.path.isdir(app_dir):
        os.rename(app_dir, broken_dir)
    os.rename(old_dir, app_dir)


# ---------------------------------------------------------------------------
# Dépendances
# ---------------------------------------------------------------------------
def requirements_sha256(app_dir):
    """Empreinte du requirements.txt du dossier app/ ('' si absent)."""
    req = os.path.join(app_dir, "requirements.txt")
    return sha256_of(req) if os.path.isfile(req) else ""


def pip_sync(runtime_python, app_dir, portable_root):
    """Installe les dépendances si requirements.txt a changé depuis le dernier passage.
    Retourne True si l'environnement est considéré à jour (échec pip = non bloquant)."""
    current_hash = requirements_sha256(app_dir)
    state = load_state(portable_root)
    if current_hash and state.get("requirements_sha256") == current_hash:
        return True  # Rien n'a changé depuis la dernière installation
    if not current_hash:
        return True
    print("📦 [UPDATER] requirements.txt a changé : synchronisation des dépendances (peut prendre quelques minutes)...")
    import subprocess
    try:
        result = subprocess.run(
            [runtime_python, "-m", "pip", "install", "-r", os.path.join(app_dir, "requirements.txt"),
             "--quiet", "--disable-pip-version-check"],
            timeout=1800,
        )
    except Exception as pe:
        print(f"⚠️ [UPDATER] Impossible de lancer pip ({pe}). L'application va tenter de démarrer.")
        return False
    if result.returncode != 0:
        print(f"⚠️ [UPDATER] pip a signalé un problème (code {result.returncode}). L'application va tenter de démarrer.")
        return False
    state["requirements_sha256"] = current_hash
    save_state(portable_root, state)
    print("✅ [UPDATER] Dépendances synchronisées.")
    return True


def find_runtime_python(portable_root, windowed=False):
    """Chemin du Python embarqué (runtime/python[w].exe), repli : Python courant."""
    name = "pythonw.exe" if windowed else "python.exe"
    candidate = os.path.join(portable_root, "runtime", name)
    return candidate if os.path.isfile(candidate) else sys_executable(windowed)


def sys_executable(windowed=False):
    import sys
    exe = sys.executable
    if windowed and exe.lower().endswith("python.exe"):
        candidate = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(candidate):
            return candidate
    return exe
