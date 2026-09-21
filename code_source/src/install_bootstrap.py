"""
Script d'initialisation post-extraction lors de la première installation.
1. Lance l'authentification Google via redirection (OAuth2).
2. Télécharge database.db depuis Google Drive (ID : GOOGLE_DRIVE_DB_ID).
3. Télécharge database_Competition.db depuis Google Drive (ID : GOOGLE_DRIVE_COMPETITION_DB_ID).
"""
import os
import sys

# S'assurer que src/ est dans le sys.path
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

# Importer les modules locaux
try:
    from paths import CODE_ROOT, ROOT_DIR, DATA_ROOT
    from infrastructure.secret_store import SecretStore
    from infrastructure.google_drive_client import GoogleDriveClient
    from infrastructure.sqlite_repository import SqliteRepository
    from infrastructure.competition_repository import CompetitionRepository
    import gmail_auth_helper
except ImportError as ie:
    print(f"❌ Erreur lors du chargement des modules d'ALJ : {ie}")
    sys.exit(1)

def run_bootstrap():
    print("\n==========================================================")
    print(" 🎯 ÉTAPE 1 : CONNEXION À GOOGLE (EMAIL & GOOGLE DRIVE) ")
    print("==========================================================")
    try:
        # Lancer l'assistant d'authentification Google
        gmail_auth_helper.run_helper()
    except Exception as e:
        print(f"❌ Échec de l'authentification Google : {e}")
        print("Veuillez vérifier vos identifiants Google Client ID et retenter.")
        input("\nAppuyez sur Entrée pour continuer...")
        sys.exit(1)

    # Vérifier que la connexion a réussi
    refresh_token = SecretStore.get_secret("GMAIL_REFRESH_TOKEN")
    if not refresh_token:
        print("⚠️ Attention : Aucun jeton de connexion Google n'a été détecté.")
        print("L'authentification Google semble avoir été ignorée ou a échoué.")
        print("Le téléchargement des bases de données de référence va être tenté, mais risque d'échouer.")
    else:
        print("✅ Connexion Google détectée et validée.")

    print("\n==========================================================")
    print(" 🎯 ÉTAPE 2 : TÉLÉCHARGEMENT DES BASES DE DONNÉES ")
    print("==========================================================")

    # 1. Base d'adhérents (database.db)
    db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
    db_local_path = SqliteRepository.get_db_path()
    
    if db_drive_id:
        print(f"📥 Téléchargement de database.db (ID Drive : {db_drive_id})...")
        os.makedirs(os.path.dirname(db_local_path), exist_ok=True)
        try:
            if GoogleDriveClient.download_file(db_drive_id, db_local_path):
                print("✅ Base de données principale 'database.db' téléchargée avec succès.")
                # Initialiser le schéma de la BDD
                SqliteRepository.setup_database()
                print("✅ Schéma de la base d'adhérents vérifié et initialisé.")
            else:
                print("❌ Échec du téléchargement de 'database.db'. Vérifiez l'ID Drive et les accès.")
        except Exception as ex:
            print(f"❌ Erreur lors du traitement de 'database.db' : {ex}")
    else:
        print("⚠️ Aucun ID configuré pour la base d'adhérents (GOOGLE_DRIVE_DB_ID).")

    # 2. Base de compétitions (database_Competition.db)
    comp_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_COMPETITION_DB_ID")
    comp_db_local_path = CompetitionRepository.get_db_path()
    
    if comp_drive_id:
        print(f"📥 Téléchargement de database_Competition.db (ID Drive : {comp_drive_id})...")
        os.makedirs(os.path.dirname(comp_db_local_path), exist_ok=True)
        try:
            if GoogleDriveClient.download_file(comp_drive_id, comp_db_local_path):
                print("✅ Base de données des compétitions 'database_Competition.db' téléchargée avec succès.")
                # Initialiser le schéma de la base de compétitions
                CompetitionRepository.setup_database(force=True)
                print("✅ Schéma de la base de compétitions vérifié et initialisé.")
            else:
                print("❌ Échec du téléchargement de 'database_Competition.db'. Vérifiez l'ID Drive.")
        except Exception as ex:
            print(f"❌ Erreur lors du traitement de 'database_Competition.db' : {ex}")
    else:
        print("💡 Aucun ID de base de compétitions configuré (GOOGLE_DRIVE_COMPETITION_DB_ID).")

    print("\n==========================================================")
    print(" 🎉 PROCESSUS DE PREMIÈRE INSTALLATION TERMINÉ ! ")
    print("==========================================================")
    print("L'authentification est prête et vos bases ont été récupérées.")
    print("Vous pouvez maintenant utiliser l'application en toute sérénité.")
    print("==========================================================\n")
    
    input("Appuyez sur Entrée pour fermer cette fenêtre...")

if __name__ == "__main__":
    run_bootstrap()
