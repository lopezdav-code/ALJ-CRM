import os
import sys

if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    CODE_ROOT = sys._MEIPASS
    ROOT_DIR = os.path.dirname(sys.executable)
else:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(_script_dir) == "src":
        CODE_ROOT = os.path.dirname(_script_dir)
    else:
        CODE_ROOT = _script_dir
    ROOT_DIR = os.path.dirname(CODE_ROOT)

# Dossier de données locales (stable) : cache SQLite, exports, fichiers utilisateur.
# Ne doit JAMAIS être écrasé par une mise à jour du code (l'updater ne swappe que app/).
# Surchargable via la variable d'environnement ALJ_DATA_DIR (utile en mode portable).
DATA_ROOT = os.environ.get("ALJ_DATA_DIR") or os.path.join(ROOT_DIR, "data")
os.makedirs(DATA_ROOT, exist_ok=True)

# Ancien emplacement du cache SQLite (racine du projet), conservé pour la migration
# automatique vers data/ lors du premier démarrage suivant cette évolution.
LEGACY_DB_PATH = os.path.join(ROOT_DIR, "database.db")


def find_doc_template(filename: str) -> str:
    """Chemin d'un modèle du dossier doc/template.

    Les modèles sont des ressources du code : en dev ils vivent sous CODE_ROOT
    (code_source/doc/template) ; en version packagée, doc/ est copié à côté de
    l'exécutable (ROOT_DIR/doc/template) et CODE_ROOT (PyInstaller) ne les contient pas.
    """
    for base in (CODE_ROOT, ROOT_DIR):
        path = os.path.join(base, "doc", "template", filename)
        if os.path.exists(path):
            return path
    return os.path.join(CODE_ROOT, "doc", "template", filename)
