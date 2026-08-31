import os
import sys
import pandas as pd
from paths import CODE_ROOT
from infrastructure.secret_store import SecretStore
from infrastructure.google_drive_client import GoogleDriveClient
from infrastructure.sqlite_repository import SqliteRepository, CORRECTIVE_MAP

def run_migration(interactive=None):
    print("==========================================================")
    print("🚀  ALJ ESCALADE - MIGRATION DE L'EXCEL DRIVE VERS SQLITE")
    print("==========================================================")

    # 1. Vérifier si GOOGLE_DRIVE_DB_ID existe déjà
    db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
    if db_drive_id:
        print(f"ℹ️ Une base SQLite est déjà configurée sur le Drive avec l'ID : {db_drive_id}")
        
        # Sécurité : Si non interactif ou appelé depuis l'IHM GUI, on refuse de poser une question bloquante
        if interactive is False or not sys.stdin or not sys.stdin.isatty():
            print("Migration annulée (mode non-interactif détecté pour éviter le blocage de l'IHM).")
            return
            
        ans = input("Souhaitez-vous forcer une nouvelle migration et écraser/recréer la BDD ? (o/N) : ").strip().lower()
        if ans != 'o':
            print("Migration annulée.")
            return

    # 2. Récupérer l'ID du fichier Excel actuel
    excel_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_FILE_ID")
    if not excel_drive_id:
        print("❌ Erreur : 'GOOGLE_DRIVE_FILE_ID' n'est pas défini dans le fichier .env.")
        print("Impossible de localiser l'Excel d'origine pour la migration.")
        return

    print(f"🔗 ID Excel source détecté sur Google Drive : {excel_drive_id}")
    
    # 3. Télécharger le fichier Excel source
    temp_excel = os.path.join(CODE_ROOT, "migration_source_temp.xlsx")
    if os.path.exists(temp_excel):
        try:
            os.remove(temp_excel)
        except Exception:
            pass

    print("📥 Téléchargement de l'Excel de référence depuis Google Drive...")
    success = GoogleDriveClient.download_file(excel_drive_id, temp_excel)
    if not success or not os.path.exists(temp_excel):
        print("❌ Échec du téléchargement de l'Excel source.")
        return

    # 4. Charger et nettoyer les données avec pandas
    print("📖 Lecture et analyse du fichier Excel...")
    try:
        df = pd.read_excel(temp_excel)
        df = df.fillna("")
    except Exception as e:
        print(f"❌ Impossible de lire l'Excel temporaire : {e}")
        return

    # Mappage des lignes
    members_to_import = []
    for _, row in df.iterrows():
        row_dict = {}
        for excel_col, cache_key in CORRECTIVE_MAP.items():
            val = row.get(excel_col, "")
            row_dict[cache_key] = val

        # Nettoyage des références commandes
        ref = str(row_dict.get("order_ref", "")).strip()
        if ref.endswith(".0"):
            ref = ref[:-2]
        row_dict["order_ref"] = ref

        # Valeurs par défaut indispensables
        row_dict["is_modified"] = "Non"
        row_dict["commentaires_correctif"] = ""
        row_dict["badge_rouge"] = "Non"
        row_dict["autonomie_bloc"] = "Non"
        row_dict["raw_passports"] = ""
        row_dict["raw_diplomas"] = ""

        members_to_import.append(row_dict)

    print(f"📋 {len(members_to_import)} adhérents identifiés pour l'importation.")

    # 5. Initialiser et peupler la base SQLite locale
    db_local_path = SqliteRepository.get_db_path()
    if os.path.exists(db_local_path):
        try:
            os.remove(db_local_path)
        except Exception:
            pass

    SqliteRepository.setup_database()
    print("💾 Insertion des données dans la base de données SQLite locale...")
    SqliteRepository.upsert_members(members_to_import)

    # 6. Téléverser la nouvelle base de données SQLite sur Google Drive
    print("📤 Envoi de la base SQLite sur Google Drive...")
    new_db_name = "database.db"
    new_drive_id = GoogleDriveClient.create_file(new_db_name, db_local_path)

    if new_drive_id:
        print("💾 Enregistrement de la configuration dans le fichier .env...")
        SecretStore.set_secret("GOOGLE_DRIVE_DB_ID", new_drive_id)
        print("==========================================================")
        print("🎉 MIGRATION TERMINÉE AVEC SUCCÈS !")
        print(f"La base de données SQLite sur le Drive a pour ID : {new_drive_id}")
        print("Le fichier .env a été mis à jour automatiquement.")
        print("==========================================================")
    else:
        print("❌ Échec de la création du fichier SQLite sur Google Drive.")

    # Nettoyage
    try:
        os.remove(temp_excel)
    except Exception:
        pass

if __name__ == "__main__":
    run_migration()
