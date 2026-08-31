"""Logging structuré de l'application ALJ Escalade Manager.

- Fichier : app_activity.log avec rotation (2 Mo x 3), encodage UTF-8 — lu par la page Logs.
- Console : StreamHandler vers la console d'origine.
- Les print() existants sont interceptés par PrintToLogInterceptor (app.py) et routés
  dans ce pipeline : stdout -> INFO, stderr -> ERROR.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from paths import ROOT_DIR

LOG_PATH = os.path.join(ROOT_DIR, "app_activity.log")

_configured = False
_ORIGINAL_STDOUT = None
_ORIGINAL_STDERR = None


def setup_logging():
    """Configure le logger racine 'alj' (idempotent)."""
    global _configured
    if _configured:
        return
    global _ORIGINAL_STDOUT, _ORIGINAL_STDERR
    _ORIGINAL_STDOUT = sys.__stdout__ or sys.stdout
    _ORIGINAL_STDERR = sys.__stderr__ or sys.stderr

    root = logging.getLogger("alj")
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] - %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(_ORIGINAL_STDOUT)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    root.propagate = False
    _configured = True


class PrintToLogInterceptor:
    """Intercepte les écritures stdout/stderr et les route dans le logging.

    Permet de conserver les print() du code existant tout en bénéficiant de
    l'horodatage, des niveaux et de la rotation de fichiers.
    """

    def __init__(self, level=logging.INFO):
        setup_logging()
        self.logger = logging.getLogger("alj")
        self.level = level
        self._console = _ORIGINAL_STDOUT if level <= logging.INFO else _ORIGINAL_STDERR

    def write(self, s):
        try:
            self._console.write(s)
            self._console.flush()
        except Exception:
            pass
        try:
            if isinstance(s, bytes):
                s = s.decode("utf-8", "replace")
            if s and s.strip():
                self.logger.log(self.level, s.strip())
        except Exception:
            pass

    def flush(self):
        try:
            self._console.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self._console, name)
