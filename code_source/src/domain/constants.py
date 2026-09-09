import os
from dotenv import load_dotenv
from paths import CODE_ROOT, ROOT_DIR

# Charger le .env embarqué (dans sys._MEIPASS si gelé)
load_dotenv(os.path.join(CODE_ROOT, ".env"))
# Surcharger avec le .env local à côté de l'exécutable s'il existe
load_dotenv(os.path.join(ROOT_DIR, ".env"), override=True)

# Saison active par défaut
DEFAULT_SEASON = "2026-2027"
APP_VERSION = "2.0.8"

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

# Phase 3 — Mapping canonique unique colonnes Excel <-> clés cache (source de vérité unique).
# Importé par sqlite_repository, excel_repository et create_excel (fin de la triplication).
CORRECTIVE_MAP = {
    "Référence commande": "order_ref",
    "Date de la commande": "order_date",
    "Statut de la commande": "status",
    "Tarif": "tarif_name",
    "Montant tarif": "amount",
    "Nom adhérent": "user_lastName",
    "Prénom adhérent": "user_firstName",
    "Nom payeur": "payer_lastName",
    "Prénom payeur": "payer_firstName",
    "Email payeur": "payer_email",
    "Date de naissance de l'adhérent": "champ_Date de naissance de l'adhérent",
    "Sexe": "champ_Sexe",
    "Nationalité": "champ_Nationalité",
    "Adresse : numéro et nom de rue": "champ_Adresse : numéro et nom de rue",
    "Code postal": "champ_Code postal",
    "Ville": "champ_Ville",
    "Pays": "champ_Pays",
    "Téléphone ": "champ_Téléphone ",
    "Adresse mail pour la réception des informations du club": "champ_Adresse mail pour la réception des informations du club",
    "Deuxième adresse mail pour la réception des informations du club": "champ_Deuxième adresse mail pour la réception des informations du club",
    "Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule": "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule",
    "Personne à prévenir en cas d'urgence - Téléphone": "champ_Personne à prévenir en cas d'urgence - Téléphone",
    "Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)": "champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)",
    "Parent 2 - Numéro de téléphone portable": "champ_Parent 2 - Numéro de téléphone portable",
    "En cas de prise de vue (Photo ou vidéo), j'autorise à ce que l'image de mon enfant (cours enfants) ou la mienne (créneau adultes) puisse être utilisée par l'Amicale Laïque de Jonage à des fins non commerciales": "champ_En cas de prise de vue (Photo ou vidéo), j'autorise à ce que l'image de mon enfant (cours enfants) ou la mienne (créneau adultes) puisse être utilisée par l'Amicale Laïque de Jonage à des fins non commerciales",
    "Je m'engage à compléter mon questionnaire de santé ou téléverser mon certificat médical sur le site  https://www.myffme.fr à réception du mail de confirmation d'adhésion, pour mon enfant (cours enfants) ou moi-même (créneau adultes)": "champ_Je m'engage à compléter mon questionnaire de santé ou téléverser mon certificat médical sur le site  https://www.myffme.fr à réception du mail de confirmation d'adhésion, pour mon enfant (cours enfants) ou moi-même (créneau adultes)",
    "Famille : nous sommes une tribu de 3 ou plus inscrits ce qui permet un code de réduction : FAMILLE": "champ_Famille : nous sommes une tribu de 3 ou plus inscrits ce qui permet un code de réduction : FAMILLE",
    "Numéro de Licence FFME (6 chiffres)": "champ_Numéro de Licence FFME (6 chiffres)",
    "Assurance Base ": "opt_Assurance Base",
    "Montant Assurance Base ": "opt_Montant Assurance Base",
    "Assurance Base +": "opt_Assurance Base +",
    "Montant Assurance Base +": "opt_Montant Assurance Base +",
    "Assurance Base ++": "opt_Assurance Base ++",
    "Montant Assurance Base ++": "opt_Montant Assurance Base ++",
    "Assurance Option ski de piste ": "opt_Assurance Option ski de piste",
    "Montant Assurance Option ski de piste ": "opt_Montant Assurance Option ski de piste",
    "Assurance Option VTT": "opt_Assurance Option VTT",
    "Montant Assurance Option VTT": "opt_Montant Assurance Option VTT",
    "Assurance Option Trail": "opt_Assurance Option Trail",
    "Montant Assurance Option Trail": "opt_Montant Assurance Option Trail",
    "Date d'envoi de l'email": "email_sent_date",
}
