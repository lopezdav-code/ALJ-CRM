import os
from dotenv import load_dotenv
from paths import CODE_ROOT, ROOT_DIR

# Charger le .env embarqué (dans sys._MEIPASS si gelé)
load_dotenv(os.path.join(CODE_ROOT, ".env"))
# Surcharger avec le .env local à côté de l'exécutable s'il existe
load_dotenv(os.path.join(ROOT_DIR, ".env"), override=True)

# Saison active par défaut
DEFAULT_SEASON = "2026-2027"
APP_VERSION = "1.9.6"

def get_active_season() -> str:
    """
    Récupère la saison active configurée dans le fichier .env (ACTIVE_SEASON)
    ou retourne la saison par défaut '2026-2027'.
    """
    val = os.getenv("ACTIVE_SEASON")
    if not val or not val.strip():
        return DEFAULT_SEASON
    return val.strip()

def get_drive_temp_filename() -> str:
    """Génère le nom de fichier Excel temporaire pour la saison active."""
    season = get_active_season()
    return f"Adhésions escalade-{season}-amicale-laique-de-jonage-DRIVE_TEMP.xlsx"

def get_corrective_files_pattern() -> str:
    """Génère le motif de recherche (glob) pour les fichiers d'adhésion de la saison active."""
    season = get_active_season()
    return f"Adhésions escalade-{season}-amicale-laique-de-jonage*.xlsx"

def get_save_filename_template(timestamp: str) -> str:
    """Génère le nom de fichier final pour la sauvegarde après synchronisation."""
    season = get_active_season()
    return f"Adhésions escalade-{season}-amicale-laique-de-jonage-{timestamp}.xlsx"

# Palette visuelle officielle Qt (Hexadécimal et QColor compatible)
COLOR_PRIMARY = "#163A5F"        # Bleu profond principal
COLOR_ACTION = "#2563EB"         # Bleu d'action principal
COLOR_SUCCESS = "#16A34A"        # Vert de succès
COLOR_WARNING = "#D97706"        # Ambre d'avertissement
COLOR_ERROR = "#DC2626"          # Rouge d'erreur
COLOR_BACKGROUND = "#F8FAFC"     # Gris de fond clair
COLOR_SURFACE = "#FFFFFF"        # Surfaces d'écriture
COLOR_TEXT_MAIN = "#1E293B"      # Texte principal
COLOR_TEXT_MUTED = "#64748B"     # Texte secondaire amorti
