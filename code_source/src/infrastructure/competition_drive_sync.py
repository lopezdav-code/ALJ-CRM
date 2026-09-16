"""
Synchronisation Google Drive de la base dédiée aux compétitions (database_Competition.db).

Même mécanisme que la base d'adhérents : identifiant du fichier stocké dans les
secrets (GOOGLE_DRIVE_COMPETITION_DB_ID), contenu mis à jour en conservant l'ID
Drive (PATCH uploadType=media) pour préserver les liens de partage.
"""
import os

from infrastructure.google_drive_client import GoogleDriveClient
from infrastructure.competition_repository import CompetitionRepository, DB_FILENAME

SECRET_KEY = "GOOGLE_DRIVE_COMPETITION_DB_ID"


def get_drive_file_id() -> str:
    from infrastructure.secret_store import SecretStore
    return (SecretStore.get_secret(SECRET_KEY) or "").strip()


def set_drive_file_id(file_id: str) -> bool:
    from infrastructure.secret_store import SecretStore
    return SecretStore.set_secret(SECRET_KEY, (file_id or "").strip())


def download_competition_db() -> tuple:
    """Télécharge database_Competition.db depuis Drive vers le cache local.

    Retourne (success: bool, message: str)."""
    file_id = get_drive_file_id()
    if not file_id:
        return False, "Aucun identifiant Drive configuré pour la base compétitions (GOOGLE_DRIVE_COMPETITION_DB_ID)."
    dest = CompetitionRepository.get_db_path()
    ok = GoogleDriveClient.download_file(file_id, dest)
    if ok:
        # Le fichier téléchargé remplace le cache local : forcer la vérification du schéma.
        CompetitionRepository.setup_database(force=True)
        return True, "Base des compétitions téléchargée depuis Google Drive."
    return False, "Le téléchargement de database_Competition.db a échoué."


def upload_competition_db() -> tuple:
    """Envoie la base compétition locale vers Drive (mise à jour de contenu).

    Si aucun ID Drive n'existe encore, le fichier est créé sur le Drive puis son
    identifiant est mémorisé dans les secrets.
    Retourne (success: bool, message: str)."""
    local_path = CompetitionRepository.get_db_path()
    if not os.path.exists(local_path):
        return False, "Fichier database_Competition.db local introuvable."

    file_id = get_drive_file_id()
    if file_id:
        ok = GoogleDriveClient.upload_file(file_id, local_path)
        if ok:
            return True, "Base des compétitions sauvegardée sur Google Drive."
        return False, "Le téléversement de database_Competition.db a échoué."

    CompetitionRepository.setup_database()
    new_id = GoogleDriveClient.create_file(DB_FILENAME, local_path)
    if new_id:
        set_drive_file_id(new_id)
        return True, f"Base des compétitions créée sur Google Drive (ID {new_id})."
    return False, "La création du fichier database_Competition.db sur Drive a échoué."
