import win32com.client
import json
import os
import sys
import glob
import pandas as pd
import datetime
import csv
import time
import requests
from attestation_generator import generate_all_attestations
from presence_sheet_generator import generate_presence_sheets
from urgency_contact_generator import generate_urgency_contacts_sheet

from paths import CODE_ROOT, ROOT_DIR
from domain.constants import (
    get_active_season,
    get_drive_temp_filename,
    get_corrective_files_pattern,
    get_save_filename_template
)
from infrastructure.secret_store import SecretStore
from infrastructure.google_drive_client import GoogleDriveClient
from domain.utils import normalize_string, normalize_name

# S'assurer que le répertoire de travail et le répertoire du script sont dans le chemin de recherche
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)
if CODE_ROOT not in sys.path:
    sys.path.append(CODE_ROOT)

excel_app = None
current_corrective_file_path = None

# Mapping between corrective Excel columns and cache keys
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

def download_file_from_drive(file_id, dest_path):
    """Télécharge le fichier Excel d'adhésion depuis Google Drive."""
    return GoogleDriveClient.download_file(file_id, dest_path)

def upload_file_to_drive(file_id, src_path):
    """Met à jour le contenu du fichier existant sur Google Drive (sans changer d'ID ni de lien)."""
    return GoogleDriveClient.upload_file(file_id, src_path)

def get_file_hash(file_path):
    """Calcule le hash SHA-256 d'un fichier."""
    import hashlib
    if not os.path.exists(file_path):
        return None
    sha = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()
    except Exception:
        return None

def is_different(cache_val, corr_val):
    c_str = str(cache_val).strip()
    co_str = str(corr_val).strip()
    
    # Variations de chaînes vides
    if c_str in ("", "nan", "none", "nat") and co_str in ("", "nan", "none", "nat"):
        return False
        
    # Variations de formats numériques (ex: 30 vs 30.0)
    try:
        if float(c_str) == float(co_str):
            return False
    except ValueError:
        pass
        
    # Variations de booléens / Oui-Non
    c_norm = c_str.lower()
    co_norm = co_str.lower()
    if c_norm in ("oui", "vrai", "true", "1"): c_norm = "oui"
    if co_norm in ("oui", "vrai", "true", "1"): co_norm = "oui"
    if c_norm in ("non", "faux", "false", "0", ""): c_norm = "non"
    if co_norm in ("non", "faux", "false", "0", ""): co_norm = "non"
    
    if c_norm == co_norm:
        return False
        
    return c_str != co_str

def prompt_user(msg, default_val):
    try:
        ans = input(msg).strip()
        if not ans:
            return default_val
        return ans
    except (EOFError, KeyboardInterrupt):
        return default_val

def load_env_variables():
    keys = [
        "HELLOASSO_CLIENT_ID", "HELLOASSO_CLIENT_SECRET", "HELLOASSO_ORG_SLUG",
        "CAMPAIGN_TYPE", "CAMPAIGN_SLUG", "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
        "SMTP_PASSWORD", "SMTP_FROM_EMAIL", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN", "GMAIL_USER_EMAIL", "GOOGLE_DRIVE_FILE_ID",
        "EMAIL_SUBJECT", "EMAIL_BODY"
    ]
    vars_dict = {k: SecretStore.get_secret(k) for k in keys}
    
    if not vars_dict.get("EMAIL_SUBJECT"):
        vars_dict["EMAIL_SUBJECT"] = f"Attestation de paiement escalade - Saison {get_active_season()}"
    if not vars_dict.get("EMAIL_BODY"):
        vars_dict["EMAIL_BODY"] = (
            "Bonjour,\n\n"
            f"Veuillez trouver ci-joint l’attestation de paiement relative à la licence d’escalade pour la saison {get_active_season()} au sein de L’Amicale Laïque de Jonage.\n\n"
            "Cette attestation peut être utilisée dans le cadre d’une demande de remboursement auprès du comité d’entreprise (CE).\n\n"
            "Nous vous remercions de bien vouloir la conserver."
        )
    else:
        vars_dict["EMAIL_BODY"] = vars_dict["EMAIL_BODY"].replace("\\n", "\n")
        
    return vars_dict

def save_env_variables(vars_dict):
    for k, v in vars_dict.items():
        SecretStore.set_secret(k, v)

def manage_credentials_menu():
    while True:
        vars_dict = load_env_variables()
        print("\n====================================================")
        print("    CONFIGURATION DES IDENTIFIANTS HELLOASSO        ")
        print("====================================================")
        print(f"1. HELLOASSO_CLIENT_ID     : {vars_dict['HELLOASSO_CLIENT_ID'] if vars_dict['HELLOASSO_CLIENT_ID'] else '(non configuré)'}")
        print(f"2. HELLOASSO_CLIENT_SECRET : {vars_dict['HELLOASSO_CLIENT_SECRET'] if vars_dict['HELLOASSO_CLIENT_SECRET'] else '(non configuré)'}")
        print(f"3. HELLOASSO_ORG_SLUG      : {vars_dict['HELLOASSO_ORG_SLUG'] if vars_dict['HELLOASSO_ORG_SLUG'] else '(non configuré)'}")
        print(f"4. CAMPAIGN_TYPE           : {vars_dict['CAMPAIGN_TYPE'] if vars_dict['CAMPAIGN_TYPE'] else '(non configuré)'}")
        print(f"5. CAMPAIGN_SLUG           : {vars_dict['CAMPAIGN_SLUG'] if vars_dict['CAMPAIGN_SLUG'] else '(non configuré)'}")
        print("6. Retour au menu principal")
        
        choice = prompt_user("Choisissez un numéro à modifier (1-6, par défaut 6) : ", "6")
        
        if choice == "1":
            val = input("Entrez HELLOASSO_CLIENT_ID : ").strip()
            if val: vars_dict["HELLOASSO_CLIENT_ID"] = val
        elif choice == "2":
            val = input("Entrez HELLOASSO_CLIENT_SECRET : ").strip()
            if val: vars_dict["HELLOASSO_CLIENT_SECRET"] = val
        elif choice == "3":
            val = input("Entrez HELLOASSO_ORG_SLUG : ").strip()
            if val: vars_dict["HELLOASSO_ORG_SLUG"] = val
        elif choice == "4":
            val = input("Entrez CAMPAIGN_TYPE (ex: Membership) : ").strip()
            if val: vars_dict["CAMPAIGN_TYPE"] = val
        elif choice == "5":
            val = input("Entrez CAMPAIGN_SLUG : ").strip()
            if val: vars_dict["CAMPAIGN_SLUG"] = val
        elif choice == "6" or choice == "":
            break
        else:
            print("Choix invalide. Veuillez entrer un numéro de 1 à 6.")
            continue
            
        save_env_variables(vars_dict)
        print("\nIdentifiants sauvegardés avec succès dans le fichier .env !")

def create_excel_app():
    global excel_app
    import pythoncom
    pythoncom.CoInitialize()
    try:
        excel_app = win32com.client.Dispatch("Excel.Application")
        excel_app.Visible = False
        excel_app.DisplayAlerts = False
    except Exception as e:
        print(f"⚠️ [COM_EXCEL] Blocage de l'accès OLE Excel ({e}). Tentative de libération des processus d'arrière-plan...")
        import os
        try:
            os.system("taskkill /f /im excel.exe >nul 2>&1")
            import time
            time.sleep(1)
        except Exception:
            pass
        # Réessayer avec un Dispatch propre
        excel_app = win32com.client.Dispatch("Excel.Application")
        excel_app.Visible = False
        excel_app.DisplayAlerts = False
    return excel_app

def get_helloasso_data():
    print("\n================================================================================")
    print("🔄 [PIPELINE SYNC] ÉTAPE 2/8 : Connexion et Authentification API HelloAsso...")
    print("================================================================================")
    print("🔑 Validation des secrets de connexion OAuth2...")
    try:
        import server
        # Force la mise à jour complète de l'API
        print("\n================================================================================")
        print("🔄 [PIPELINE SYNC] ÉTAPE 3/8 : Récupération des adhésions de la campagne...")
        print("================================================================================")
        print("📥 Interrogation en direct et en temps réel de l'API HelloAsso (veuillez patienter)...")
        data = server.get_dashboard_data(force_refresh=True)
        if isinstance(data, dict) and "participants" in data:
            print(f"✅ {len(data['participants'])} inscriptions récupérées avec succès depuis HelloAsso.")
            return data["participants"]
        else:
            print("❌ Format de données HelloAsso invalide ou vide.")
    except Exception as e:
        print(f"❌ Erreur lors de la synchronisation HelloAsso : {e}")
    return []

def sanitize_rows(rows):
    import math
    import datetime
    import json
    sanitized_rows = []
    for row in rows:
        sanitized_row = []
        for val in row:
            if val is None or pd.isna(val):
                new_val = ""
            elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                new_val = ""
            elif hasattr(val, "to_pydatetime") or isinstance(val, (datetime.datetime, datetime.date)):
                try:
                    if hasattr(val, "to_pydatetime"):
                        dt_val = val.to_pydatetime()
                    elif isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
                        dt_val = datetime.datetime(val.year, val.month, val.day)
                    else:
                        dt_val = val
                    
                    if hasattr(dt_val, "tzinfo") and dt_val.tzinfo is not None:
                        dt_val = dt_val.replace(tzinfo=None)
                    
                    # Convert to Excel serial number to avoid locale-specific date swapping and OSError pre-1970
                    epoch = datetime.datetime(1899, 12, 30)
                    delta = dt_val - epoch
                    new_val = delta.days + (delta.seconds + delta.microseconds / 1000000.0) / 86400.0
                except Exception:
                    new_val = ""
            elif "numpy" in str(type(val)):
                type_name = type(val).__name__
                if "int" in type_name:
                    new_val = int(val)
                elif "float" in type_name:
                    try:
                        f_val = float(val)
                        if math.isnan(f_val) or math.isinf(f_val):
                            new_val = ""
                        else:
                            new_val = f_val
                    except Exception:
                        new_val = ""
                else:
                    new_val = str(val)
            elif isinstance(val, (list, tuple, set)):
                new_val = ", ".join(str(x) for x in val)
            elif isinstance(val, dict):
                new_val = json.dumps(val, ensure_ascii=False)
            elif not isinstance(val, (str, int, float, bool)):
                new_val = str(val)
            else:
                new_val = val
            sanitized_row.append(new_val)
        sanitized_rows.append(sanitized_row)
    return sanitized_rows

def choose_membership_file(files):
    if not files:
        return None
    if len(files) == 1:
        return files[0]
        
    print("\n⚠️ Plusieurs fichiers d'adhésions détectés :")
    for idx, f in enumerate(files, 1):
        print(f" {idx}. {os.path.basename(f)}")
        
    choice = prompt_user(f"Quel fichier souhaitez-vous utiliser ? (1 à {len(files)}, par défaut 1) : ", "1")
    try:
        choice_idx = int(choice) - 1
        if 0 <= choice_idx < len(files):
            return files[choice_idx]
    except ValueError:
        pass
    return files[0]

def parse_date_to_datetime(val):
    if not val or pd.isna(val):
        return ""
    # Si c'est déjà un timestamp ou datetime
    if hasattr(val, "to_pydatetime"):
        return val.to_pydatetime()
    if isinstance(val, (datetime.datetime, datetime.date)):
        if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
            return datetime.datetime(val.year, val.month, val.day)
        return val
        
    val_str = str(val).strip()
    if not val_str:
        return ""
        
    # Essayer de parser différents formats de chaînes courants
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            # Pour l'ISO-8601 complet (avec millisecondes et décalage)
            if "T" in val_str and fmt == "%Y-%m-%dT%H:%M:%S":
                return datetime.datetime.strptime(val_str[:19], fmt)
            return datetime.datetime.strptime(val_str, fmt)
        except Exception:
            pass
            
    # Si on n'a pas réussi à parser mais que c'est une chaîne non vide, on la renvoie brute
    return val_str

def clean_digits_only(val):
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        if pd.isna(val):
            return ""
        try:
            return str(int(float(val)))
        except (ValueError, TypeError):
            return ""
    val_str = str(val).strip()
    if not val_str:
        return ""
    if val_str.endswith(".0"):
        val_str = val_str[:-2]
    return "".join(c for c in val_str if c.isdigit())

def get_direct_excel_data():
    print("\n--- EXTRACTION DIRECTE SANS PASSAGE PAR HELLOASSO ---")
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        participants_data = SqliteRepository.load_direct_data()
        print(f"Extraction réussie : {len(participants_data)} adhésions récupérées directement depuis la base SQLite.")
        return participants_data
    except Exception as e:
        print(f"Erreur lors de l'extraction directe depuis la base SQLite : {e}")
        return []

def format_to_excel_date(date_str):
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    try:
        if "T" in date_str:
            dt = datetime.datetime.strptime(date_str[:10], "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        elif "-" in date_str:
            parts = date_str.split("-")
            if len(parts) == 3 and len(parts[0]) == 4:
                dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                return dt.strftime("%d/%m/%Y")
    except Exception:
        pass
    return date_str

def update_membership_excel():
    global gui_active
    print("\n================================================================================")
    print("🔄 [PIPELINE SYNC] ÉTAPE 1/8 : Téléchargement de la base SQLite partagée...")
    print("================================================================================")
    
    env_vars = load_env_variables()
    db_drive_id = env_vars.get("GOOGLE_DRIVE_DB_ID", "").strip()
    excel_drive_id = env_vars.get("GOOGLE_DRIVE_FILE_ID", "").strip()
    
    from infrastructure.sqlite_repository import SqliteRepository
    db_local_path = SqliteRepository.get_db_path()
    
    # S'assurer d'avoir la base de données initialisée et téléchargée
    if not db_drive_id and excel_drive_id:
        print("🚀 [MIGRATION AUTOMATIQUE] Première utilisation de SQLite détectée.")
        try:
            from migrate_excel_to_db import run_migration
            run_migration(interactive=False) # Mode non interactif
            env_vars = load_env_variables()
            db_drive_id = env_vars.get("GOOGLE_DRIVE_DB_ID", "").strip()
        except Exception as me:
            print(f"⚠️ Échec de la migration automatique : {me}")
            
    if db_drive_id:
        print(f"🔗 ID de BDD partagée détecté sur le Drive : {db_drive_id}")
        print("📥 Téléchargement de database.db depuis Google Drive...")
        if download_file_from_drive(db_drive_id, db_local_path):
            print("✅ Base de données SQLite partagée téléchargée avec succès.")
        else:
            print("⚠️ Échec du téléchargement. Utilisation de la base SQLite locale existante.")
    else:
        print("⚠️ Aucun ID de BDD partagée détecté sur le Drive. Utilisation de la base SQLite locale.")

    SqliteRepository.setup_database()
    initial_db_hash = get_file_hash(db_local_path)
    existing_participants = SqliteRepository.load_direct_data()
    
    # ÉTAPES 2 & 3 gérées dynamiquement au sein de get_helloasso_data()
    participants_data = get_helloasso_data()
    if not participants_data:
        print("❌ Erreur : Impossible de charger les données HelloAsso. Le pipeline est interrompu.")
        return False, [], "Impossible de charger les données HelloAsso."
        
    try:
        print("\n================================================================================")
        print("🔄 [PIPELINE SYNC] ÉTAPE 4/8 : Déduplication ultra-sécurisée (Anti-Doublons)...")
        print("================================================================================")
        print(f"👥 Comparaison de HelloAsso avec les {len(existing_participants)} adhérents en local...")
        print("🎯 Clés d'unicité vérifiées (OrderRef + Nom + Prénom + Licence FFME).")

        # 1. Identifier les clés d'adhésions existantes de manière accent-insensible et les numéros de licence
        from collections import Counter

        existing_keys = set()
        existing_licenses = set()
        excel_order_counts = Counter() # Compter les occurences par commande dans la BDD !
        existing_member_max_score = {} # (firstName, lastName) -> score maximal du statut existant en BDD

        status_priorities = {
            "processed": 10,
            "validated": 9,
            "validé": 8,
            "valide": 8,
            "terminé": 7,
            "en cours": 5,
            "canceled": 1,
            "annulé": 1,
            "annule": 1
        }

        def get_priority_score(status, tarif_name, amount):
            status_lower = str(status or "").strip().lower()
            base_prio = status_priorities.get(status_lower, 0)
            
            # Pénalité importante de 20 points pour les listes d'attente ou montants nuls
            tarif_lower = str(tarif_name or "").strip().lower()
            try:
                amt_val = float(amount) if amount else 0.0
            except ValueError:
                amt_val = 0.0
                
            if "attente" in tarif_lower or amt_val == 0.0:
                base_prio -= 20
                
            return base_prio
        
        for p in existing_participants:
            o_ref = str(p.get("order_ref", "")).strip()
            if o_ref.endswith(".0"):
                o_ref = o_ref[:-2]
                
            f_name = normalize_name(p.get("user_firstName", ""))
            l_name = normalize_name(p.get("user_lastName", ""))
            existing_keys.add((o_ref, f_name, l_name))
            
            # Calculer et enregistrer le score maximal existant pour cet adhérent
            score_existing = get_priority_score(p.get("status"), p.get("tarif_name"), p.get("amount"))
            key_member = (f_name, l_name)
            existing_member_max_score[key_member] = max(existing_member_max_score.get(key_member, -999), score_existing)
            
            # Incrémenter le compteur de commandes dans la BDD
            if o_ref:
                excel_order_counts[o_ref] += 1
            
            # Extraire la licence FFME de la BDD
            lic_val = str(p.get("champ_Numéro de Licence FFME (6 chiffres)", "")).strip()
            if lic_val.endswith(".0"):
                lic_val = lic_val[:-2]
            if lic_val and lic_val.lower() not in ("", "nan", "aucune", "non"):
                existing_licenses.add(lic_val.lower())
                
        # Compter les occurrences par commande renvoyées par HelloAsso
        helloasso_order_counts = Counter()
        for p_temp in participants_data:
            o_temp = str(p_temp.get("order_ref", "")).strip()
            if o_temp.endswith(".0"):
                o_temp = o_temp[:-2]
            if o_temp:
                helloasso_order_counts[o_temp] += 1
            
        # 2. Trouver les nouvelles adhésions dans HelloAsso de manière ultra-sécurisée
        new_participants = []
        for p in participants_data:
            o_ref = str(p.get("order_ref", "")).strip()
            if o_ref.endswith(".0"):
                o_ref = o_ref[:-2]
                
            f_name_norm = normalize_name(p.get("user_firstName", ""))
            l_name_norm = normalize_name(p.get("user_lastName", ""))
            key_norm = (o_ref, f_name_norm, l_name_norm)
            
            # Extraire la licence FFME de la nouvelle adhésion
            new_lic = str(p.get("champ_Numéro de Licence FFME (6 chiffres)", "")).strip()
            if new_lic.endswith(".0"):
                new_lic = new_lic[:-2]
                
            is_duplicate = False
            
            # Contrôle 0 : Si l'adhérent possède déjà une inscription plus prioritaire en BDD
            # (par exemple un cours validé par rapport à une liste d'attente ou commande annulée)
            new_score = get_priority_score(p.get("status"), p.get("tarif_name"), p.get("amount"))
            key_member = (f_name_norm, l_name_norm)
            if key_member in existing_member_max_score:
                exist_score = existing_member_max_score[key_member]
                if exist_score > new_score:
                    is_duplicate = True
                    print(f"🛡️ [DEDUPL] Inscription moins prioritaire ignorée pour {p.get('user_lastName')} {p.get('user_firstName')} (Score existant: {exist_score}, Nouveau: {new_score})")
            
            # Contrôle 1 : Si le numéro de licence existe déjà, c'est un doublon !
            if not is_duplicate and new_lic and new_lic.lower() not in ("", "nan", "aucune", "non"):
                if new_lic.lower() in existing_licenses:
                    is_duplicate = True
                    print(f"🛡️ [DEDUPL] Doublon détecté via N° Licence FFME : {p.get('user_lastName')} {p.get('user_firstName')} ({new_lic})")
            
            # Contrôle 2 : Si la clé de commande + nom/prénom normalisés existe déjà !
            if key_norm in existing_keys:
                is_duplicate = True
                
            # Contrôle 3 : Règle de sécurité de commande déjà présente
            if not is_duplicate and o_ref in excel_order_counts:
                order_date_raw = p.get("order_date", "")
                p_date = parse_date_to_datetime(order_date_raw)
                
                if isinstance(p_date, (datetime.datetime, datetime.date)):
                    cutoff_date = datetime.datetime(2026, 8, 1)
                    if p_date < cutoff_date:
                        if excel_order_counts[o_ref] >= helloasso_order_counts[o_ref]:
                            is_duplicate = True
                            print(f"🛡️ [DEDUPL] Doublon historique bloqué pour la commande {o_ref} (Date d'achat : {p_date.strftime('%d/%m/%Y')})")
            
            if not is_duplicate:
                new_participants.append(p)
                
        print(f"🔍 Filtrage terminé : {len(new_participants)} nouvelle(s) adhésion(s) trouvée(s).")
        if len(new_participants) == 0:
            print("ℹ️ Aucune nouvelle adhésion à ajouter. La base SQLite est déjà entièrement à jour.")
            
            print("\n================================================================================")
            print("🔄 [PIPELINE SYNC] ÉTAPE 8/8 : Actualisation complète de l'IHM...")
            print("================================================================================")
            print("🔄 Signalement à l'interface graphique de vider les caches...")
            print("🎉 [FIN DE PIPELINE] Synchronisation HelloAsso terminée avec succès (base déjà à jour) !")
            print("================================================================================\n")
            return True, [], "Aucune nouvelle adhésion à ajouter. La base est déjà à jour."
            
        print("\n================================================================================")
        print("🔄 [PIPELINE SYNC] ÉTAPE 5/8 : Création d'un Point de Restauration (Backup)...")
        print("================================================================================")
        print("💾 Sauvegarde préventive de la base de données locale en cours...")
        # Note : Le backup est créé automatiquement par SqliteRepository.upsert_members() ci-dessous.
        
        print("\n================================================================================")
        print("🔄 [PIPELINE SYNC] ÉTAPE 6/8 : Insertion chirurgicale en Base de Données...")
        print("================================================================================")
        # 3. Marquer comme "Oui (Ajouté)" et insérer dans SQLite
        for p in new_participants:
            p["is_modified"] = "Oui (Ajouté)"
            p["commentaires_correctif"] = ""
            
        print(f"📝 Écriture de {len(new_participants)} nouvelles fiches adhérents dans SQLite...")
        SqliteRepository.upsert_members(new_participants)
        print("✅ Base SQLite locale mise à jour et complétée.")
        
        print("\n================================================================================")
        print("🔄 [PIPELINE SYNC] ÉTAPE 7/8 : Téléversement et Partage sur Google Drive...")
        print("================================================================================")
        # 4. Envoi de la base SQLite mise à jour vers Google Drive
        if db_drive_id:
            current_db_hash = get_file_hash(db_local_path)
            if initial_db_hash and current_db_hash == initial_db_hash:
                print("ℹ️ Aucun changement détecté dans la base SQLite locale. Téléversement Google Drive ignoré pour économiser de la bande passante.")
            else:
                print("📤 Envoi et partage de database.db vers Google Drive...")
                upload_file_to_drive(db_drive_id, db_local_path)
                print("✅ Base SQLite partagée synchronisée avec succès sur Google Drive !")
        else:
            print("⚠️ Aucun ID de BDD Drive configuré. La base de données reste uniquement locale.")
            
        print("\n================================================================================")
        print("🔄 [PIPELINE SYNC] ÉTAPE 8/8 : Actualisation complète de l'IHM...")
        print("================================================================================")
        print("🔄 Signalement à l'interface graphique de vider les caches graphiques...")
        print("🎉 [FIN DE PIPELINE] Synchronisation HelloAsso accomplie avec succès !")
        print("================================================================================\n")
        return True, new_participants, db_local_path
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ [PIPELINE ERROR] Erreur lors de la mise à jour de la base de données : {e}")
        return False, [], str(e)

def draw_dashboard(ws_dash, participants_data):
    ws_dash.Range("A3:Z1000").ClearContents()
    ws_dash.Range("A3:Z1000").Borders.LineStyle = -4142 # xlNone
    ws_dash.Range("A3:Z1000").Interior.ColorIndex = -4142 # xlNone
    ws_dash.Range("A3:Z1000").Font.Bold = False
    
    # Filtrer les listes d'attente pour le dashboard
    valid_participants = []
    for p in participants_data:
        t_name = str(p.get("tarif_name", "")).lower()
        amount = p.get("amount", 0.0)
        status = str(p.get("status", "")).lower()
        if "attente" in t_name or amount == 0.0 or "annul" in status:
            continue
        valid_participants.append(p)
        
    count_total = len(valid_participants)
    rev_total = sum(float(p.get("amount", 0.0)) for p in valid_participants)
    
    ws_dash.Cells(3, 1).Value = "Nombre total d'inscrits :"
    ws_dash.Cells(3, 2).Value = count_total
    ws_dash.Cells(3, 2).Font.Bold = True
    ws_dash.Cells(4, 1).Value = "Revenus totaux :"
    ws_dash.Cells(4, 2).Value = f"{rev_total} €"
    ws_dash.Cells(4, 2).Font.Bold = True
    
    # Calculer le nombre en liste d'attente
    count_waitlist = sum(1 for p in participants_data if "attente" in str(p.get("tarif_name", "")).lower() or float(p.get("amount", 0.0)) == 0.0)
    ws_dash.Cells(5, 1).Value = "Nombre en liste d'attente :"
    ws_dash.Cells(5, 2).Value = count_waitlist
    ws_dash.Cells(5, 2).Font.Bold = True
    
    # Calcul des statistiques
    dict_cat = {}
    dict_city = {}
    dict_week = {}
    age_groups = {
        "Moins de 10 ans": 0,
        "10-13 ans": 0,
        "14-17 ans": 0,
        "18-34 ans": 0,
        "35 ans et +": 0,
        "Non spécifié": 0
    }
    
    for p in valid_participants:
        t_name = p.get("tarif_name", "").strip()
        dict_cat[t_name] = dict_cat.get(t_name, 0) + 1
        
        ville = p.get("champ_Ville", "").strip().upper()
        if ville:
            dict_city[ville] = dict_city.get(ville, 0) + 1
            
        raw_date = p.get("order_date", "")
        dt = None
        if isinstance(raw_date, (datetime.datetime, datetime.date)):
            dt = raw_date
        else:
            parsed_dt = parse_date_to_datetime(str(raw_date).strip())
            if isinstance(parsed_dt, (datetime.datetime, datetime.date)):
                dt = parsed_dt
                
        try:
            if dt is None:
                raise ValueError("Date invalide")
            w_year, w_num, _ = dt.isocalendar()
            w_key = f"{w_year}-S{w_num:02d}"
            dict_week[w_key] = dict_week.get(w_key, 0) + 1
        except Exception:
            pass
            
        # Calcul de l'âge de l'adhérent
        dob = p.get("champ_Date de naissance de l'adhérent", "")
        dt_dob = None
        if isinstance(dob, (datetime.datetime, datetime.date)):
            dt_dob = dob
        elif isinstance(dob, str) and dob.strip():
            dt_dob = parse_date_to_datetime(dob.strip())
            
        if isinstance(dt_dob, (datetime.datetime, datetime.date)):
            try:
                now = datetime.datetime.now()
                age = now.year - dt_dob.year - ((now.month, now.day) < (dt_dob.month, dt_dob.day))
                if age < 10:
                    age_groups["Moins de 10 ans"] += 1
                elif age <= 13:
                    age_groups["10-13 ans"] += 1
                elif age <= 17:
                    age_groups["14-17 ans"] += 1
                elif age <= 34:
                    age_groups["18-34 ans"] += 1
                else:
                    age_groups["35 ans et +"] += 1
            except Exception:
                age_groups["Non spécifié"] += 1
        else:
            age_groups["Non spécifié"] += 1
            
    # Écriture Table Catégories
    ws_dash.Cells(7, 1).Value = "Répartition par Catégorie"
    ws_dash.Cells(7, 2).Value = "Inscrits"
    ws_dash.Range(ws_dash.Cells(7, 1), ws_dash.Cells(7, 2)).Font.Bold = True
    ws_dash.Range(ws_dash.Cells(7, 1), ws_dash.Cells(7, 2)).Interior.Color = 0xE1E6DC
    
    dict_macro = {}
    dict_sub = {}
    for cat, count in dict_cat.items():
        t = cat.lower()
        if "autonome" in t:
            mg = "Les autonomes"
        elif "compétition" in t:
            mg = "Les compétiteurs"
        elif "cours" in t or "perfectionnement" in t:
            mg = "Les cours"
        elif "loisir" in t:
            mg = "Loisir mineurs"
        else:
            mg = "Autres"
            
        dict_macro[mg] = dict_macro.get(mg, 0) + count
        
        if "2019" in t and "2020" in t:
            sg = "Enfants 2019-2020"
        elif "2016" in t and "2018" in t:
            sg = "Enfants 2016-2018"
        elif "collège" in t:
            sg = "Collège"
        else:
            sg = cat
            
        subkey = f"{mg}|{sg}"
        dict_sub[subkey] = dict_sub.get(subkey, 0) + count
        
    r = 8
    for mg, mg_count in sorted(dict_macro.items()):
        ws_dash.Cells(r, 1).Value = mg
        ws_dash.Cells(r, 2).Value = mg_count
        ws_dash.Range(ws_dash.Cells(r, 1), ws_dash.Cells(r, 2)).Font.Bold = True
        ws_dash.Range(ws_dash.Cells(r, 1), ws_dash.Cells(r, 2)).Interior.Color = 0xF5F5EB
        r += 1
        for subkey, count in sorted(dict_sub.items()):
            parts = subkey.split("|")
            if parts[0] == mg:
                ws_dash.Cells(r, 1).Value = f"   └ {parts[1]}"
                ws_dash.Cells(r, 2).Value = count
                ws_dash.Cells(r, 1).Font.Italic = True
                r += 1
                
    if r > 8:
        ws_dash.Range(ws_dash.Cells(7, 1), ws_dash.Cells(r - 1, 2)).Borders.LineStyle = 1
        
    # Écriture Table Villes
    ws_dash.Cells(7, 4).Value = "Répartition par Ville"
    ws_dash.Cells(7, 4).Font.Bold = True
    ws_dash.Cells(7, 4).Interior.Color = 0xE6F1DC
    r_city = 8
    for city, count in sorted(dict_city.items(), key=lambda x: x[1], reverse=True):
        ws_dash.Cells(r_city, 4).Value = city
        ws_dash.Cells(r_city, 5).Value = count
        r_city += 1
    if r_city > 8:
        ws_dash.Range(ws_dash.Cells(7, 4), ws_dash.Cells(r_city - 1, 5)).Borders.LineStyle = 1
        
    # Écriture Table Semaines
    ws_dash.Cells(7, 7).Value = "Évolution par Semaine"
    ws_dash.Cells(7, 8).Value = "Inscriptions"
    ws_dash.Range(ws_dash.Cells(7, 7), ws_dash.Cells(7, 8)).Font.Bold = True
    ws_dash.Range(ws_dash.Cells(7, 7), ws_dash.Cells(7, 8)).Interior.Color = 0xDCE6F1
    r_week = 8
    for week, count in sorted(dict_week.items()):
        ws_dash.Cells(r_week, 7).Value = week
        ws_dash.Cells(r_week, 8).Value = count
        r_week += 1
    if r_week > 8:
        ws_dash.Range(ws_dash.Cells(7, 7), ws_dash.Cells(r_week - 1, 8)).Borders.LineStyle = 1
        
    # Recréation du graphique d'évolution
    for cObj in ws_dash.ChartObjects():
        try:
            cObj.Delete()
        except Exception:
            pass
            
    if dict_week:
        try:
            cObj = ws_dash.ChartObjects().Add(Left=ws_dash.Cells(7, 10).Left, Top=ws_dash.Cells(7, 10).Top, Width=450, Height=280)
            cObj.Chart.ChartType = 51 # xlColumnClustered
            cObj.Chart.SetSourceData(Source=ws_dash.Range(ws_dash.Cells(7, 7), ws_dash.Cells(r_week - 1, 8)))
            cObj.Chart.HasTitle = True
            cObj.Chart.ChartTitle.Text = "Évolution des inscriptions par semaine"
            cObj.Chart.HasLegend = False
        except Exception as ce:
            print(f"Note : Impossible d'ajouter le graphique sur le Dashboard : {ce}")

    # Écriture Table Âge
    ws_dash.Cells(26, 10).Value = "Répartition par Âge"
    ws_dash.Cells(26, 11).Value = "Adhérents"
    ws_dash.Range(ws_dash.Cells(26, 10), ws_dash.Cells(26, 11)).Font.Bold = True
    ws_dash.Range(ws_dash.Cells(26, 10), ws_dash.Cells(26, 11)).Interior.Color = 0xF1DCE6 # Rose/Violet pastel
    
    age_keys = ["Moins de 10 ans", "10-13 ans", "14-17 ans", "18-34 ans", "35 ans et +", "Non spécifié"]
    for idx, key in enumerate(age_keys, 27):
        ws_dash.Cells(idx, 10).Value = key
        ws_dash.Cells(idx, 11).Value = age_groups[key]
        
    ws_dash.Range(ws_dash.Cells(26, 10), ws_dash.Cells(32, 11)).Borders.LineStyle = 1

    # Recréation du graphique d'âge
    try:
        cObj_age = ws_dash.ChartObjects().Add(Left=ws_dash.Cells(34, 10).Left, Top=ws_dash.Cells(34, 10).Top, Width=450, Height=280)
        cObj_age.Chart.ChartType = 51 # xlColumnClustered
        cObj_age.Chart.SetSourceData(Source=ws_dash.Range(ws_dash.Cells(26, 10), ws_dash.Cells(32, 11)))
        cObj_age.Chart.HasTitle = True
        cObj_age.Chart.ChartTitle.Text = "Répartition des adhérents par tranche d'âge"
        cObj_age.Chart.HasLegend = False
    except Exception as ce:
        print(f"Note : Impossible d'ajouter le graphique d'âge sur le Dashboard : {ce}")

def build_excel(participants_data, rows_values, modified_rows, added_rows, headers):
    timestamp = datetime.datetime.now().strftime("%Y%m%d")
    save_filename = f"HelloAsso_Admin_{timestamp}.xlsx"
    
    # Définir le dossier d'importation des fichiers HelloAsso actifs
    import_dir = os.path.join(ROOT_DIR, "import", "helloAsso")
    os.makedirs(import_dir, exist_ok=True)
    save_path = os.path.join(import_dir, save_filename)
    
    # Archiver les anciens rapports HelloAsso_Admin
    archive_dir = os.path.join(ROOT_DIR, "archive", "helloAsso")
    os.makedirs(archive_dir, exist_ok=True)
    import shutil
    for old_file in glob.glob(os.path.join(import_dir, "HelloAsso_Admin_*.xlsx")):
        if os.path.basename(old_file) != save_filename:
            try:
                shutil.move(old_file, os.path.join(archive_dir, os.path.basename(old_file)))
                print(f"📦 Ancien rapport HelloAsso_Admin archivé : {os.path.basename(old_file)}")
            except Exception:
                pass
    
    # Vérification si le fichier est ouvert par l'utilisateur ou verrouillé
    while True:
        if os.path.exists(save_path):
            try:
                # Tenter d'ouvrir le fichier en mode écriture exclusive (r+)
                with open(save_path, "r+"):
                    pass
                break  # Non verrouillé, on peut continuer !
            except IOError:
                global gui_active
                if gui_active:
                    import tkinter.messagebox
                    ans = tkinter.messagebox.askretrycancel(
                        "Fichier verrouillé",
                        f"Le fichier '{save_filename}' est actuellement OUVERT dans Excel ou verrouillé par OneDrive.\n\n"
                        "Veuillez le fermer, puis cliquer sur 'Recommencer'.\n"
                        "Ou cliquez sur 'Annuler' pour abandonner la génération."
                    )
                    if not ans:
                        print("\n❌ Génération annulée par l'utilisateur (fichier verrouillé).")
                        raise Exception("Génération annulée (fichier verrouillé).")
                else:
                    print(f"\n❌ ERREUR : Le fichier '{save_filename}' est actuellement OUVERT dans Excel ou verrouillé par OneDrive.")
                    print("👉 Veuillez fermer le fichier dans Excel pour permettre sa mise à jour.")
                    prompt_user("Appuyez sur Entrée une fois le fichier fermé pour réessayer...", "")
        else:
            break

    print("\nGénération du fichier Excel final (xlsx)...")
    excel = create_excel_app()
    
    if os.path.exists(save_path):
        try:
            os.remove(save_path)
        except Exception as de:
            pass
            
    wb = excel.Workbooks.Add()
    
    ws_tableau = wb.Sheets(1)
    ws_tableau.Name = "Tableau"
    
    ws_dashboard = wb.Sheets.Add(After=ws_tableau)
    ws_dashboard.Name = "Dashboard"
    
    # Nettoyer les onglets Excel créés par défaut
    for s in wb.Sheets:
        if s.Name not in ("Tableau", "Dashboard"):
            try:
                s.Delete()
            except Exception:
                pass
                
    # Écriture des en-têtes
    for col, h in enumerate(headers, 1):
        ws_tableau.Cells(1, col).Value = h
        ws_tableau.Cells(1, col).Font.Bold = True

    # Écriture matricielle ultra-rapide
    if rows_values:
        start_cell = ws_tableau.Cells(2, 1)
        end_cell = ws_tableau.Cells(1 + len(rows_values), len(headers))
        ws_tableau.Range(start_cell, end_cell).Value = sanitize_rows(rows_values)
        
    # Application des couleurs
    for r in modified_rows:
        ws_tableau.Cells(r, 1).Interior.Color = 0xCCFFFF # Jaune clair
    for r in added_rows:
        ws_tableau.Cells(r, 1).Interior.Color = 0xCCFFCC # Vert clair

    # Création du tableau structuré
    row_count = len(rows_values) + 1
    list_obj_tab = ws_tableau.ListObjects.Add(1, ws_tableau.Range(ws_tableau.Cells(1, 1), ws_tableau.Cells(row_count, len(headers))), None, 1)
    list_obj_tab.Name = "TableauInscrits"
    list_obj_tab.TableStyle = "TableStyleMedium2"
    
    # Formatage
    ws_tableau.Columns(3).NumberFormatLocal = "jj/mm/aaaa"
    ws_tableau.Columns(12).NumberFormatLocal = "jj/mm/aaaa"
    ws_tableau.Columns.AutoFit()
    
    # Dessiner le Dashboard
    draw_dashboard(ws_dashboard, participants_data)
    ws_dashboard.Columns.AutoFit()
    
    # Sauvegarde du fichier Excel
    saved_successfully = False
    for attempt in range(1, 4):
        try:
            wb.SaveAs(save_path)
            saved_successfully = True
            break
        except Exception as se:
            print(f"Tentative de sauvegarde {attempt}/3 échouée (OneDrive) : {se}")
            time.sleep(1)
            
    if not saved_successfully:
        alt_name = f"HelloAsso_Admin_{timestamp}_{int(time.time())}.xlsx"
        save_path = os.path.abspath(alt_name)
        print(f"Sauvegarde de secours sous : {save_path}")
        wb.SaveAs(save_path)

    wb.Close(False)
    excel.Quit()
    global excel_app
    excel_app = None
    print(f"Fichier Excel finalisé : {save_path}")

def generate_ffme_csv(participants_data, output_path=None):
    """
    Génère le CSV d'import FFME.
    Si output_path est fourni (tests de non-régression), écrit à cet emplacement exact
    sans horodatage ni archivage. Sinon, comportement historique : fichier horodaté
    dans exports/ avec archivage des anciens CSV.
    """
    print("\nGénération simultanée du fichier CSV FFME...")
    if output_path:
        csv_path = output_path
        out_dir = os.path.dirname(os.path.abspath(csv_path))
        os.makedirs(out_dir, exist_ok=True)
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"import_ffme_{timestamp}.csv"

        root_dir = ROOT_DIR
        exports_dir = os.path.join(root_dir, "exports")
        os.makedirs(exports_dir, exist_ok=True)
        csv_path = os.path.join(exports_dir, csv_filename)

        # Archiver les anciens fichiers import_ffme
        archive_dir = os.path.join(exports_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        import shutil
        for old_file in glob.glob(os.path.join(exports_dir, "import_ffme_*.csv")):
            if os.path.basename(old_file) != csv_filename:
                try:
                    shutil.move(old_file, os.path.join(archive_dir, os.path.basename(old_file)))
                    print(f"📦 Ancien fichier CSV FFME archivé : {os.path.basename(old_file)}")
                except Exception:
                    pass
    
    headers = [
        "numero de licence", "nom", "prenom", "date de naissance", "sexe", "nationalite",
        "adresse", "adresse complement", "code postal", "ville", "pays", "tel fixe", "tel mobile", 
        "courriel", "courriel 2", "pap nom", "pap prenom", "pap telephone", "pap courriel", 
        "nom de naissance", "commune de naissance", "departement de naissance", "type licence", 
        "assurance", "option ski", "option slackline", "option trail", "option vtt", 
        "assurance complementaire", "option protection agression"
    ]

    csv_rows = []
    ignored_members = []

    for p in participants_data:
        # Exclure les listes d'attente, montants nuls (sauf les ajouts manuels), commandes annulées/canceled ou déjà validées (terminé)
        tarif_name = str(p.get("tarif_name", "")).lower()
        amount = p.get("amount", 0.0)
        status = str(p.get("status", "")).lower()
        commentaires = str(p.get("commentaires_correctif", "")).lower()
        is_manual = "ajout manuel" in commentaires
        
        if "attente" in tarif_name or (amount == 0.0 and not is_manual) or "annul" in status or "cancel" in status or "termin" in status:
            continue

        nom = str(p.get("user_lastName", "")).strip().upper()
        if not nom: nom = "INCONNU"

        prenom = str(p.get("user_firstName", "")).strip()
        if not prenom: prenom = "INCONNU"

        # 1. Licence
        lic_num = clean_digits_only(p.get("champ_Numéro de Licence FFME (6 chiffres)", ""))
        if len(lic_num) < 5 or len(lic_num) > 10:
            lic_num = ""

        # 2. DOB
        dob_val = p.get("champ_Date de naissance de l'adhérent", "")
        dob_date = None
        if isinstance(dob_val, (datetime.datetime, datetime.date)):
            dob_date = dob_val
        else:
            dob_str = str(dob_val).strip()
            parsed_dt = parse_date_to_datetime(dob_str)
            if isinstance(parsed_dt, (datetime.datetime, datetime.date)):
                dob_date = parsed_dt

        if not dob_date or dob_date >= datetime.datetime.now():
            ignored_members.append(f"⚠️ [IGNORÉ] {nom} {prenom} (Commande {p.get('order_ref')}) : date de naissance absente ou invalide ('{dob_val}')")
            continue
            
        dob = dob_date.strftime("%d/%m/%Y")
            
        # 3. Sexe
        sexe_raw = str(p.get("champ_Sexe", "")).strip().upper()
        if sexe_raw.startswith(("M", "H", "G")):
            sexe = "H"
        elif sexe_raw.startswith(("F", "D")):
            sexe = "F"
        else:
            sexe = "" if lic_num else "H"
            
        # 4. Pays
        pays_raw = str(p.get("champ_Pays", "France")).strip().upper()
        pays = "FR" if "FR" in pays_raw or pays_raw == "FRANCE" or pays_raw == "" else pays_raw[:2]
        if not pays and not lic_num:
            pays = "FR"
            
        # 5. Nationalité
        nat_raw = str(p.get("champ_Nationalité", "Francaise")).strip().upper()
        if "FR" in nat_raw or nat_raw == "FRANCE" or nat_raw == "":
            nat = "FR"
        elif "SUED" in nat_raw or "SWE" in nat_raw:
            nat = "SE"
        elif len(nat_raw) == 2:
            nat = nat_raw
        else:
            nat = "FR" if not lic_num else ""
            
        # 6. Adresse
        adresse = str(p.get("champ_Adresse : numéro et nom de rue", "")).strip()[:255]
        if not adresse and not lic_num:
            adresse = "ADRESSE NON COMMUNIQUEE"
            
        # 7. Code postal
        cp = clean_digits_only(p.get("champ_Code postal", ""))
        if pays == "FR":
            if cp:
                cp = cp.zfill(5)[:5]
            else:
                cp = "69330" if not lic_num else ""
        else:
            cp = cp[:10]
            
        # 8. Ville
        ville = str(p.get("champ_Ville", "")).strip().upper()[:100]
        if not ville and not lic_num:
            ville = "JONAGE"
            
        # 9. Téléphones
        tel_raw = clean_digits_only(p.get("champ_Téléphone ", ""))
        if pays == "FR" and tel_raw:
            if tel_raw.startswith("33"):
                tel_raw = "0" + tel_raw[2:]
            tel_raw = tel_raw[:10]
        tel = tel_raw
        
        # 10. Courriels
        email = str(p.get("champ_Adresse mail pour la réception des informations du club", "")).strip().lower()[:100]
        if not email:
            email = str(p.get("payer_email", "")).strip().lower()[:100]
        if not email and not lic_num:
            email = "contact@amicale-laique-jonage.fr"
            
        email2 = str(p.get("champ_Deuxième adresse mail pour la réception des informations du club", "")).strip().lower()[:100]
        
        # 11. PAP
        pap_raw = str(p.get("champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule", "")).strip()
        pap_nom = ""
        pap_prenom = ""
        if pap_raw:
            if " " in pap_raw:
                parts = pap_raw.split(" ", 1)
                pap_prenom = parts[0][:100]
                pap_nom = parts[1].upper()[:100]
            else:
                pap_nom = pap_raw.upper()[:100]
                
        pap_tel = clean_digits_only(p.get("champ_Personne à prévenir en cas d'urgence - Téléphone", ""))[:15]
        
        # 12. Type licence (J, A, F)
        is_tribu = str(p.get("champ_Famille : nous sommes une tribu de 3 ou plus inscrits ce qui permet un code de réduction : FAMILLE", "")).lower()
        if is_tribu in ("true", "vrai", "oui", "1"):
            type_licence = "F"
        else:
            cutoff_date = datetime.datetime(2009, 8, 31)
            if dob_date > cutoff_date:
                type_licence = "J"
            else:
                type_licence = "A"
                
        # 13. Assurance (RC, B, B+, B++)
        val_ass_base = str(p.get("opt_Assurance Base", "Non")).upper()
        val_ass_plus = str(p.get("opt_Assurance Base +", "Non")).upper()
        val_ass_plusplus = str(p.get("opt_Assurance Base ++", "Non")).upper()
        
        if val_ass_plusplus in ("OUI", "TRUE", "VRAI"):
            assurance = "B++"
        elif val_ass_plus in ("OUI", "TRUE", "VRAI"):
            assurance = "B+"
        elif val_ass_base in ("OUI", "TRUE", "VRAI"):
            assurance = "B"
        else:
            assurance = "RC"
            
        # 14. Options
        val_ski = str(p.get("opt_Assurance Option ski de piste", "Non")).upper()
        opt_ski = "OUI" if val_ski in ("OUI", "TRUE", "VRAI") else "NON"
        
        val_vtt = str(p.get("opt_Assurance Option VTT", "Non")).upper()
        opt_vtt = "OUI" if val_vtt in ("OUI", "TRUE", "VRAI") else "NON"
        
        val_trail = str(p.get("opt_Assurance Option Trail", "Non")).upper()
        opt_trail = "OUI" if val_trail in ("OUI", "TRUE", "VRAI") else "NON"
        
        row = [
            lic_num, nom, prenom, dob, sexe, nat, adresse, "", cp, ville, pays, "", tel, 
            email, email2, pap_nom, pap_prenom, pap_tel, "", "", "", "", type_licence, 
            assurance, opt_ski, "NON", opt_trail, opt_vtt, "NON", "NON"
        ]
        csv_rows.append(row)
        
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(headers)
        writer.writerows(csv_rows)
        
    print(f"Fichier CSV FFME généré : {csv_path}")
    return ignored_members

def generate_csv_from_excel():
    import_dir = os.path.join(ROOT_DIR, "import", "helloAsso")
    excel_files = glob.glob(os.path.join(import_dir, "HelloAsso_Admin_*.xlsx"))
    print("\n--- GÉNÉRATION DU CSV À PARTIR DE L'EXCEL ---")
    if not excel_files:
        print("Erreur : Aucun fichier Excel 'HelloAsso_Admin_*.xlsx' trouvé.")
        print("Veuillez d'abord lancer la génération de l'Excel (Option 1).")
        return
        
    # Prendre le plus récent
    excel_path = max(excel_files, key=os.path.getmtime)
    print(f"Chargement du tableau Excel : {os.path.basename(excel_path)}...")
    try:
        # Charger la feuille 'Tableau'
        df = pd.read_excel(excel_path, sheet_name="Tableau")
        df = df.fillna("")
        
        # Convertir en liste de dictionnaires
        participants_data = df.to_dict(orient="records")
        
        # Formater les dates pour qu'elles soient compatibles avec generate_ffme_csv
        for p in participants_data:
            for k in ("order_date", "champ_Date de naissance de l'adhérent"):
                val = p.get(k, "")
                if pd.isna(val) or val is pd.NaT:
                    p[k] = ""
                elif hasattr(val, "strftime"):
                    try:
                        p[k] = val.strftime("%d/%m/%Y")
                    except Exception:
                        p[k] = ""
                else:
                    p[k] = str(val).strip()
                    
        print(f"Chargement réussi ({len(participants_data)} lignes trouvées dans l'Excel).")
        generate_ffme_csv(participants_data)
        
    except Exception as e:
        print(f"Erreur lors de la génération du CSV depuis l'Excel : {e}")

def run_extraction_pipeline():
    print("\n--- DEBUT EXTRACTION DIRECTE ET GENERATION EXCEL & CSV ---")
    # Extraction directe depuis le fichier Excel d'adhésion
    participants_data = get_direct_excel_data()
    if not participants_data:
        print("Erreur : Impossible de charger les participants. Extraction annulée.")
        return
    
    # 3. Compilation des lignes de données
    headers = [
        "is_modified", "order_ref", "order_date", "status", "tarif_name", "amount", 
        "user_firstName", "user_lastName", "payer_firstName", "payer_lastName", "payer_email",
        "champ_Date de naissance de l'adhérent", "champ_Sexe", "champ_Nationalité", 
        "champ_Adresse : numéro et nom de rue", "champ_Code postal", "champ_Ville", "champ_Pays", 
        "champ_Téléphone ", "champ_Adresse mail pour la réception des informations du club", 
        "champ_Deuxième adresse mail pour la réception des informations du club", 
        "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule", 
        "champ_Personne à prévenir en cas d'urgence - Téléphone", 
        "champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)", 
        "champ_Parent 2 - Numéro de téléphone portable", 
        "champ_En cas de prise de vue (Photo ou vidéo), j'autorise...", 
        "champ_Je m'engage à compléter mon questionnaire de santé...", 
        "champ_Famille : nous sommes une tribu de 3...", 
        "champ_Numéro de Licence FFME (6 chiffres)",
        "opt_Assurance Base", "opt_Montant Assurance Base", 
        "opt_Assurance Base +", "opt_Montant Assurance Base +", 
        "opt_Assurance Base ++", "opt_Montant Assurance Base ++",
        "opt_Assurance Option ski de piste", "opt_Montant Assurance Option ski de piste",
        "opt_Assurance Option VTT", "opt_Montant Assurance Option VTT",
        "opt_Assurance Option Trail", "opt_Montant Assurance Option Trail",
        "commentaires_correctif"
    ]
    
    rows_values = []
    modified_rows = []
    added_rows = []
    
    current_row = 2
    for p in participants_data:
        is_mod = p.get("is_modified", "Non")
        if is_mod == "Oui":
            modified_rows.append(current_row)
        elif is_mod == "Oui (Ajouté)":
            added_rows.append(current_row)
            
        row_vals = [
            is_mod,
            p.get("order_ref", ""),
            p.get("order_date", ""),
            p.get("status", ""),
            p.get("tarif_name", ""),
            p.get("amount", 0.0),
            p.get("user_firstName", ""),
            p.get("user_lastName", ""),
            p.get("payer_firstName", ""),
            p.get("payer_lastName", ""),
            p.get("payer_email", ""),
            p.get("champ_Date de naissance de l'adhérent", ""),
            p.get("champ_Sexe", ""),
            p.get("champ_Nationalité", ""),
            p.get("champ_Adresse : numéro et nom de rue", ""),
            p.get("champ_Code postal", ""),
            p.get("champ_Ville", ""),
            p.get("champ_Pays", ""),
            p.get("champ_Téléphone ", ""),
            p.get("champ_Adresse mail pour la réception des informations du club", ""),
            p.get("champ_Deuxième adresse mail pour la réception des informations du club", ""),
            p.get("champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule", ""),
            p.get("champ_Personne à prévenir en cas d'urgence - Téléphone", ""),
            p.get("champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)", ""),
            p.get("champ_Parent 2 - Numéro de téléphone portable", ""),
            p.get("champ_En cas de prise de vue (Photo ou vidéo), j'autorise...", ""),
            p.get("champ_Je m'engage à compléter mon questionnaire de santé...", ""),
            p.get("champ_Famille : nous sommes une tribu de 3...", ""),
            p.get("champ_Numéro de Licence FFME (6 chiffres)", ""),
            p.get("opt_Assurance Base", "Non"),
            p.get("opt_Montant Assurance Base", 0.0),
            p.get("opt_Assurance Base +", "Non"),
            p.get("opt_Montant Assurance Base +", 0.0),
            p.get("opt_Assurance Base ++", "Non"),
            p.get("opt_Montant Assurance Base ++", 0.0),
            p.get("opt_Assurance Option ski de piste", "Non"),
            p.get("opt_Montant Assurance Option ski de piste", 0.0),
            p.get("opt_Assurance Option VTT", "Non"),
            p.get("opt_Montant Assurance Option VTT", 0.0),
            p.get("opt_Assurance Option Trail", "Non"),
            p.get("opt_Montant Assurance Option Trail", 0.0),
            p.get("commentaires_correctif", "")
        ]
        rows_values.append(row_vals)
        current_row += 1
        
    # 4. Génération de l'Excel (.xlsx, sans macros !)
    build_excel(participants_data, rows_values, modified_rows, added_rows, headers)
    
    # 5. Génération simultanée du CSV FFME
    generate_ffme_csv(participants_data)
    
    print("\n====================================================")
    print("          TRAITEMENT PIPELINE ACCOMPLI !            ")
    print("====================================================")



def save_email_dates_to_excel(sent_records):
    """
    Enregistre les dates d'envoi dans la colonne "Date d'envoi de l'email" du fichier d'adhésion.
    """
    global current_corrective_file_path
    if not current_corrective_file_path or not os.path.exists(current_corrective_file_path):
        print("[EMAIL] Fichier Excel introuvable pour enregistrer les dates d'envoi.")
        return False
        
    print(f"[EMAIL] Ouverture de l'Excel pour enregistrer les dates d'envoi : {current_corrective_file_path}")
    excel = create_excel_app()
    wb = None
    try:
        wb = excel.Workbooks.Open(current_corrective_file_path)
        ws = wb.Sheets(1)
        
        # Mapper les en-têtes de colonnes existants à leurs index (1-based)
        headers_map = {}
        col = 1
        while True:
            val = ws.Cells(1, col).Value
            if val is None or str(val).strip() == "":
                break
            headers_map[str(val).strip()] = col
            col += 1
            
        ref_col = headers_map.get("Référence commande")
        last_name_col = headers_map.get("Nom adhérent")
        first_name_col = headers_map.get("Prénom adhérent")
        
        if not ref_col or not last_name_col or not first_name_col:
            print("[EMAIL] Colonnes indispensables manquantes dans l'Excel source.")
            wb.Close(False)
            excel.Quit()
            return False
            
        # Obtenir ou créer l'index de la colonne "Date d'envoi de l'email"
        date_col_idx = headers_map.get("Date d'envoi de l'email")
        if not date_col_idx:
            date_col_idx = col  # Première colonne libre
            ws.Cells(1, date_col_idx).Value = "Date d'envoi de l'email"
            ws.Cells(1, date_col_idx).Font.Bold = True
            print(f"[EMAIL] Colonne 'Date d'envoi de l'email' créée à l'index {date_col_idx}")
            
        # Trouver le nombre total de lignes
        total_rows = ws.UsedRange.Rows.Count
        
        # Parcourir et mettre à jour chaque ligne correspondante
        updated_count = 0
        for record in sent_records:
            target_ref = str(record["order_ref"]).strip()
            if target_ref.endswith(".0"):
                target_ref = target_ref[:-2]
                
            target_first = str(record["first_name"]).strip().lower()
            target_last = str(record["last_name"]).strip().lower()
            date_sent = record["date_sent"]
            
            for row in range(2, total_rows + 1):
                raw_ref = ws.Cells(row, ref_col).Value
                if isinstance(raw_ref, (int, float)):
                    ref_val = str(int(raw_ref))
                else:
                    ref_val = str(raw_ref or "").strip()
                if ref_val.endswith(".0"):
                    ref_val = ref_val[:-2]
                    
                first_val = str(ws.Cells(row, first_name_col).Value or "").strip().lower()
                last_val = str(ws.Cells(row, last_name_col).Value or "").strip().lower()
                
                if ref_val == target_ref and first_val == target_first and last_val == target_last:
                    ws.Cells(row, date_col_idx).Value = date_sent
                    updated_count += 1
                    break
                    
        print(f"[EMAIL] Enregistrement de {updated_count} date(s) d'envoi dans le fichier Excel.")
        wb.Save()
        wb.Close(False)
        excel.Quit()
        
        # Gérer la mise à jour sur Google Drive
        env_vars = load_env_variables()
        drive_file_id = env_vars.get("GOOGLE_DRIVE_FILE_ID", "").strip()
        if drive_file_id and current_corrective_file_path.endswith("DRIVE_TEMP.xlsx"):
            print("[EMAIL] Téléversement du fichier mis à jour vers Google Drive...")
            upload_file_to_drive(drive_file_id, current_corrective_file_path)
            
        return True
    except Exception as ex:
        print(f"[EMAIL] Erreur lors de l'enregistrement des dates dans l'Excel : {ex}")
        if wb:
            try:
                wb.Close(False)
            except Exception:
                pass
        try:
            excel.Quit()
        except Exception:
            pass
        return False

def show_member_details(parent, p):
    """
    Affiche une fiche détaillée ergonomique de l'adhérent dans un popup modale.
    """
    import tkinter as tk
    from tkinter import ttk
    
    top = tk.Toplevel(parent)
    top.title(f"Détails de l'Adhérent - {str(p.get('user_lastName', '')).upper()} {str(p.get('user_firstName', '')).capitalize()}")
    top.geometry("820x920")
    top.configure(bg="#F0F4F8")
    top.resizable(True, True)
    
    top.transient(parent)
    top.grab_set()
    
    root_x = parent.winfo_x()
    root_y = parent.winfo_y()
    root_w = parent.winfo_width()
    root_h = parent.winfo_height()
    x = root_x + (root_w - 820) // 2
    y = root_y + (root_h - 920) // 2
    top.geometry(f"820x920+{x}+{y}")
    
    # Titre de la fiche
    full_name = f"👤 {str(p.get('user_lastName', '')).upper()} {str(p.get('user_firstName', '')).capitalize()}"
    lbl_title = tk.Label(top, text=full_name, font=("Segoe UI", 14, "bold"), bg="#1E3A8A", fg="white", pady=12)
    lbl_title.pack(fill=tk.X)
    
    # Container défilable (scrollable frame)
    container = tk.Frame(top, bg="#F0F4F8")
    container.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
    
    canvas = tk.Canvas(container, bg="#F0F4F8", highlightthickness=0)
    scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    scroll_frame = tk.Frame(canvas, bg="#F0F4F8")
    
    scroll_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    def configure_width(event):
        canvas.itemconfig(canvas_window, width=event.width)
    canvas.bind("<Configure>", configure_width)
    
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    # Association du défilement à la molette de la souris (uniquement au survol de la fiche)
    def _on_details_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
    container.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_details_mousewheel))
    container.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
    
    # Grid layout de 2 colonnes pour ranger les cartes d'informations
    scroll_frame.columnconfigure(0, weight=1)
    scroll_frame.columnconfigure(1, weight=1)
    
    card_bg = "#FFFFFF"
    
    def create_card(title, col, row, columnspan=1):
        lf = tk.LabelFrame(scroll_frame, text=title, font=("Segoe UI", 10, "bold"), bg=card_bg, fg="#1F2937", padx=12, pady=10, bd=1, relief=tk.SOLID)
        lf.grid(column=col, row=row, columnspan=columnspan, sticky="nwes", padx=10, pady=10)
        lf.columnconfigure(1, weight=1)
        return lf

    def add_field(card, label, value, row, wrap_width=None):
        lbl = tk.Label(card, text=f"{label} : ", font=("Segoe UI", 9, "bold"), bg=card_bg, fg="#4B5563", anchor="w")
        lbl.grid(row=row, column=0, sticky="w", pady=3)
        
        val_str = str(value).strip() if value is not None else ""
        if not val_str:
            val_str = "-"
            val_color = "#9CA3AF"
        else:
            val_color = "#1F2937"
            
        if wrap_width:
            approx_lines = max(1, (len(val_str) * 7) // wrap_width + 1)
            # Text widget plat (sélectionnable & copiable)
            val_lbl = tk.Text(card, font=("Segoe UI", 9), bg=card_bg, fg=val_color, bd=0, highlightthickness=0, height=approx_lines, wrap="word", width=28)
            val_lbl.insert("1.0", val_str)
            val_lbl.configure(state="disabled")
        else:
            # Entry widget plat (sélectionnable & copiable)
            val_lbl = tk.Entry(card, font=("Segoe UI", 9), bg=card_bg, fg=val_color, bd=0, highlightthickness=0, readonlybackground=card_bg, width=32)
            val_lbl.insert(0, val_str)
            val_lbl.configure(state="readonly")
            
        val_lbl.grid(row=row, column=1, sticky="w", pady=3, padx=(5, 0))
        return val_lbl

    # Carte 1 : Informations Adhérent (Col 0, Row 0)
    card_member = create_card("👤 Informations Adhérent", 0, 0)
    add_field(card_member, "Nom", p.get("user_lastName", "").upper(), 0)
    add_field(card_member, "Prénom", p.get("user_firstName", "").capitalize(), 1)
    
    dob = p.get("champ_Date de naissance de l'adhérent", "")
    if hasattr(dob, "strftime"):
        dob_str = dob.strftime("%d/%m/%Y")
    else:
        dob_str = str(dob)
    add_field(card_member, "Naissance", dob_str, 2)
    add_field(card_member, "Sexe", p.get("champ_Sexe", ""), 3)
    add_field(card_member, "Nationalité", p.get("champ_Nationalité", ""), 4)
    add_field(card_member, "N° Licence FFME", p.get("champ_Numéro de Licence FFME (6 chiffres)", ""), 5)
    add_field(card_member, "Email Club", p.get("champ_Adresse mail pour la réception des informations du club", ""), 6, wrap_width=200)

    # Carte 2 : Commande & Paiement (Col 1, Row 0)
    card_order = create_card("💳 Commande & Paiement", 1, 0)
    add_field(card_order, "Réf Commande", p.get("order_ref", ""), 0)
    
    o_date = p.get("order_date", "")
    if hasattr(o_date, "strftime"):
        o_date_str = o_date.strftime("%d/%m/%Y %H:%M")
    else:
        o_date_str = str(o_date)
    add_field(card_order, "Date Commande", o_date_str, 1)
    add_field(card_order, "Statut", p.get("status", ""), 2)
    add_field(card_order, "Tarif HelloAsso", p.get("tarif_name", ""), 3, wrap_width=200)
    add_field(card_order, "Montant Payé", f"{p.get('amount', 0.0)} €", 4)
    add_field(card_order, "Payeur", f"{str(p.get('payer_lastName', '')).upper()} {str(p.get('payer_firstName', '')).capitalize()}", 5)
    add_field(card_order, "Email Payeur", p.get("payer_email", ""), 6, wrap_width=200)

    # Carte 3 : Coordonnées (Col 0, Row 1)
    card_addr = create_card("📍 Adresse & Téléphone", 0, 1)
    add_field(card_addr, "Adresse", p.get("champ_Adresse : numéro et nom de rue", ""), 0, wrap_width=200)
    add_field(card_addr, "Code Postal", p.get("champ_Code postal", ""), 1)
    add_field(card_addr, "Ville", p.get("champ_Ville", "").upper(), 2)
    add_field(card_addr, "Pays", p.get("champ_Pays", ""), 3)
    add_field(card_addr, "Téléphone", p.get("champ_Téléphone ", ""), 4)

    # Carte 4 : Contacts Urgence (Col 1, Row 1)
    card_urg = create_card("📞 Contacts d'Urgence", 1, 1)
    add_field(card_urg, "Contact 1", p.get("champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule", ""), 0, wrap_width=200)
    add_field(card_urg, "Téléphone 1", p.get("champ_Personne à prévenir en cas d'urgence - Téléphone", ""), 1)
    add_field(card_urg, "Contact 2", p.get("champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)", ""), 2, wrap_width=200)
    add_field(card_urg, "Téléphone 2", p.get("champ_Parent 2 - Numéro de téléphone portable", ""), 3)

    # Carte 5 : Options Assurances (Col 0, Row 2)
    card_ins = create_card("🛡️ Assurances & Options", 0, 2)
    add_field(card_ins, "Assurance Base", f"{p.get('opt_Assurance Base', 'Non')} ({p.get('opt_Montant Assurance Base', 0.0)} €)", 0)
    add_field(card_ins, "Assurance Base +", f"{p.get('opt_Assurance Base +', 'Non')} ({p.get('opt_Montant Assurance Base +', 0.0)} €)", 1)
    add_field(card_ins, "Assurance Base ++", f"{p.get('opt_Assurance Base ++', 'Non')} ({p.get('opt_Montant Assurance Base ++', 0.0)} €)", 2)
    add_field(card_ins, "Option Ski", f"{p.get('opt_Assurance Option ski de piste', 'Non')} ({p.get('opt_Montant Assurance Option ski de piste', 0.0)} €)", 3)
    add_field(card_ins, "Option VTT", f"{p.get('opt_Assurance Option VTT', 'Non')} ({p.get('opt_Montant Assurance Option VTT', 0.0)} €)", 4)
    add_field(card_ins, "Option Trail", f"{p.get('opt_Assurance Option Trail', 'Non')} ({p.get('opt_Montant Assurance Option Trail', 0.0)} €)", 5)

    # Carte 6 : Engagements & Divers (Col 1, Row 2)
    card_eng = create_card("📝 Engagements & Suivi", 1, 2)
    add_field(card_eng, "Tribu Famille", p.get("champ_Famille : nous sommes une tribu de 3 ou plus inscrits ce qui permet un code de réduction : FAMILLE", "Non"), 0, wrap_width=200)
    add_field(card_eng, "Certif. Médical", p.get("champ_Je m'engage à compléter mon questionnaire de santé ou téléverser mon certificat médical sur le site  https://www.myffme.fr à réception du mail de confirmation d'adhésion, pour mon enfant (cours enfants) ou moi-même (créneau adultes)", "Non"), 1, wrap_width=200)
    add_field(card_eng, "Droit à l'image", p.get("champ_En cas de prise de vue (Photo ou vidéo), j'autorise à ce que l'image de mon enfant (cours enfants) ou la mienne (créneau adultes) puisse être utilisée par l'Amicale Laïque de Jonage à des fins non commerciales", "Non"), 2, wrap_width=200)
    
    # Historique de suivi d'envoi d'e-mail
    sent_date = p.get("email_sent_date", "")
    lbl_email_status_title = tk.Label(card_eng, text="Suivi d'Envoi : ", font=("Segoe UI", 9, "bold"), bg=card_bg, fg="#4B5563", anchor="w")
    lbl_email_status_title.grid(row=3, column=0, sticky="w", pady=12)
    
    if sent_date:
        status_txt = f"📧 Envoyé le {sent_date}"
        status_bg = "#D1FAE5"  # Vert pastel
        status_fg = "#065F46"  # Vert foncé
    else:
        status_txt = "❌ Jamais envoyé"
        status_bg = "#FEE2E2"  # Rouge pastel
        status_fg = "#991B1B"  # Rouge foncé
        
    lbl_email_status_val = tk.Label(card_eng, text=status_txt, font=("Segoe UI", 9, "bold"), bg=status_bg, fg=status_fg, padx=8, pady=4, bd=1, relief=tk.SOLID)
    lbl_email_status_val.grid(row=3, column=1, sticky="w", pady=12, padx=(5, 0))

    # Carte 7 : Passeports, Badges & Diplômes FFME (Col 0, Row 3, columnspan=2)
    card_license = create_card("🏅 Passeports, Badges & Diplômes FFME (Licenciés)", 0, 3, columnspan=2)
    card_license.columnconfigure(0, weight=1)
    card_license.columnconfigure(1, weight=1)
    
    badge_rouge = p.get("badge_rouge", "Non")
    autonomie_bloc = p.get("autonomie_bloc", "Non")
    
    # Section Badges d'autonomie (en haut de la carte)
    frame_achievements = tk.Frame(card_license, bg=card_bg, pady=5)
    frame_achievements.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    frame_achievements.columnconfigure(0, weight=1)
    frame_achievements.columnconfigure(1, weight=1)
    
    # Section Badges d'autonomie (en haut de la carte)
    frame_achievements = tk.Frame(card_license, bg=card_bg, pady=5)
    frame_achievements.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    frame_achievements.columnconfigure(0, weight=1)
    frame_achievements.columnconfigure(1, weight=1)
    
    # Sous-cadre Badge Rouge (colonne 0)
    frame_br = tk.Frame(frame_achievements, bg=card_bg)
    frame_br.grid(row=0, column=0, sticky="w", padx=(20, 0))
    
    lbl_br = tk.Label(frame_br, text="🔴 Badge rouge diff : ", font=("Segoe UI", 9, "bold"), bg=card_bg, fg="#4B5563")
    lbl_br.pack(side=tk.LEFT)
    
    lbl_br_val = tk.Entry(frame_br, font=("Segoe UI", 9, "bold"), bg=card_bg, fg="#EA580C" if badge_rouge == "Oui" else "#6B7280", bd=0, highlightthickness=0, readonlybackground=card_bg, width=8)
    lbl_br_val.insert(0, badge_rouge)
    lbl_br_val.configure(state="readonly")
    lbl_br_val.pack(side=tk.LEFT)
    
    # Sous-cadre Autonomie Bloc (colonne 1)
    frame_ab = tk.Frame(frame_achievements, bg=card_bg)
    frame_ab.grid(row=0, column=1, sticky="w", padx=(20, 0))
    
    lbl_ab = tk.Label(frame_ab, text="🟩 Autonomie Bloc : ", font=("Segoe UI", 9, "bold"), bg=card_bg, fg="#4B5563")
    lbl_ab.pack(side=tk.LEFT)
    
    lbl_ab_val = tk.Entry(frame_ab, font=("Segoe UI", 9, "bold"), bg=card_bg, fg="#10B981" if autonomie_bloc == "Oui" else "#6B7280", bd=0, highlightthickness=0, readonlybackground=card_bg, width=8)
    lbl_ab_val.insert(0, autonomie_bloc)
    lbl_ab_val.configure(state="readonly")
    lbl_ab_val.pack(side=tk.LEFT)
    
    # Séparateur horizontal
    sep = ttk.Separator(card_license, orient="horizontal")
    sep.grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
    
    passports = p.get("passports", [])
    diplomas = p.get("diplomas", [])
    
    # Section Passeports (colonne 0, row 2)
    lbl_p_title = tk.Label(card_license, text="🎓 Passeports obtenus :", font=("Segoe UI", 9, "bold"), bg=card_bg, fg="#1E3A8A")
    lbl_p_title.grid(row=2, column=0, sticky="w", pady=(5, 5))
    if passports:
        for idx, pass_val in enumerate(passports, 3):
            ent_p = tk.Entry(card_license, font=("Segoe UI", 9), bg=card_bg, fg="#1F2937", bd=0, highlightthickness=0, readonlybackground=card_bg, width=32)
            ent_p.insert(0, f"  • {pass_val}")
            ent_p.configure(state="readonly")
            ent_p.grid(row=idx, column=0, sticky="w", pady=1)
    else:
        lbl_no_p = tk.Label(card_license, text="  (Aucun passeport enregistré)", font=("Segoe UI", 9, "italic"), bg=card_bg, fg="#6B7280")
        lbl_no_p.grid(row=3, column=0, sticky="w", pady=1)
        
    # Section Diplômes (colonne 1, row 2)
    lbl_d_title = tk.Label(card_license, text="📜 Diplômes obtenus :", font=("Segoe UI", 9, "bold"), bg=card_bg, fg="#1E3A8A")
    lbl_d_title.grid(row=2, column=1, sticky="w", pady=(5, 5))
    if diplomas:
        for idx, dip_val in enumerate(diplomas, 3):
            ent_d = tk.Entry(card_license, font=("Segoe UI", 9), bg=card_bg, fg="#1F2937", bd=0, highlightthickness=0, readonlybackground=card_bg, width=32)
            ent_d.insert(0, f"  • {dip_val}")
            ent_d.configure(state="readonly")
            ent_d.grid(row=idx, column=1, sticky="w", pady=1)
    else:
        lbl_no_d = tk.Label(card_license, text="  (Aucun diplôme enregistré)", font=("Segoe UI", 9, "italic"), bg=card_bg, fg="#6B7280")
        lbl_no_d.grid(row=3, column=1, sticky="w", pady=1)

    # Bouton fermer tout en bas
    btn_close = tk.Button(top, text="Fermer la Fiche", command=top.destroy, bg="#1E3A8A", fg="white", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, padx=22, pady=6)
    btn_close.pack(pady=12)

def open_presence_window(parent, participants_data):
    import tkinter as tk
    from tkinter import ttk
    import tkinter.messagebox
    import datetime

    # Extract unique tarif names (groups), excluding waitlist groups
    unique_tarifs = set()
    has_autonome_adultes = False
    has_autonome_jeunes = False
    
    for p in participants_data:
        t_name = str(p.get("tarif_name", "")).strip()
        if t_name and "attente" not in t_name.lower():
            if t_name == "Adultes autonomes":
                has_autonome_adultes = True
            elif t_name == "Jeunes Adultes autonomes - nés entre 2001 et 2008":
                has_autonome_jeunes = True
            else:
                unique_tarifs.add(t_name)
                
    if has_autonome_adultes or has_autonome_jeunes:
        unique_tarifs.add("Adultes & Jeunes Adultes autonomes")

    sorted_tarifs = sorted(list(unique_tarifs))

    if not sorted_tarifs:
        tkinter.messagebox.showwarning("Aucune donnée", "Aucun groupe/tarif disponible. Veuillez d'abord charger les données.")
        return

    top = tk.Toplevel(parent)
    top.title("Génération des Feuilles de Présence au Cours (A3 Vertical)")
    top.geometry("550x570")
    top.configure(bg="#F0F4F8")
    top.resizable(True, True)
    top.transient(parent)
    top.grab_set()

    # Center popup
    root_x = parent.winfo_x()
    root_y = parent.winfo_y()
    root_w = parent.winfo_width()
    root_h = parent.winfo_height()
    x = root_x + (root_w - 550) // 2
    y = root_y + (root_h - 570) // 2
    top.geometry(f"550x570+{x}+{y}")

    lbl_title = tk.Label(top, text="📝 Génération des Listes de Présence (A3)", font=("Segoe UI", 12, "bold"), bg="#06B6D4", fg="white", pady=10)
    lbl_title.pack(fill=tk.X)

    lbl_desc = tk.Label(top, text="Sélectionnez le ou les groupes d'adhérents à exporter pour l'impression.\nUn fichier Excel séparé sera créé pour chaque groupe coché.", font=("Segoe UI", 9, "italic"), bg="#F0F4F8", fg="#4B5563", pady=8)
    lbl_desc.pack()

    # Champs pour saisir les dates de début et de fin
    frame_dates = tk.LabelFrame(top, text="📅 Période des séances (Optionnelle)", font=("Segoe UI", 9, "bold"), bg="#F0F4F8", fg="#1F2937", padx=10, pady=5)
    frame_dates.pack(fill=tk.X, padx=15, pady=5)
    
    tk.Label(frame_dates, text="Début (JJ/MM/AAAA) :", font=("Segoe UI", 9), bg="#F0F4F8", fg="#4B5563").grid(row=0, column=0, padx=5, pady=5, sticky="w")
    ent_start = tk.Entry(frame_dates, width=12, font=("Segoe UI", 9))
    ent_start.grid(row=0, column=1, padx=5, pady=5)
    
    tk.Label(frame_dates, text="Fin (JJ/MM/AAAA) :", font=("Segoe UI", 9), bg="#F0F4F8", fg="#4B5563").grid(row=0, column=2, padx=15, pady=5, sticky="w")
    ent_end = tk.Entry(frame_dates, width=12, font=("Segoe UI", 9))
    ent_end.grid(row=0, column=3, padx=5, pady=5)

    # Container for checklist
    frame_list = tk.LabelFrame(top, text="Groupes de tarifs disponibles (hors liste d'attente)", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#1F2937", padx=10, pady=10)
    frame_list.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

    # Add a canvas + scrollbar for checklist
    canvas = tk.Canvas(frame_list, bg="#FFFFFF", highlightthickness=0)
    scrollbar = tk.Scrollbar(frame_list, orient="vertical", command=canvas.yview)
    scroll_inner = tk.Frame(canvas, bg="#FFFFFF")

    scroll_inner.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    canvas_window = canvas.create_window((0, 0), window=scroll_inner, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    def configure_width(event):
        canvas.itemconfig(canvas_window, width=event.width)
    canvas.bind("<Configure>", configure_width)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # Add checkboxes
    checkbox_vars = {}
    for tarif in sorted_tarifs:
        var = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(scroll_inner, text=tarif, variable=var, font=("Segoe UI", 9), bg="#FFFFFF", activebackground="#FFFFFF", anchor="w", justify="left")
        chk.pack(fill=tk.X, anchor="w", pady=2)
        checkbox_vars[tarif] = var

    # Quick selection buttons
    frame_sel = tk.Frame(top, bg="#F0F4F8", pady=5)
    frame_sel.pack(fill=tk.X, padx=15)

    def select_all_groups():
        for var in checkbox_vars.values():
            var.set(True)

    def deselect_all_groups():
        for var in checkbox_vars.values():
            var.set(False)

    btn_all = tk.Button(frame_sel, text="Sélectionner Tout", command=select_all_groups, font=("Segoe UI", 9, "bold"), bg="#E2E8F0", fg="#1F2937", relief=tk.FLAT, padx=10)
    btn_all.pack(side=tk.LEFT, padx=5)

    btn_none = tk.Button(frame_sel, text="Désélectionner Tout", command=deselect_all_groups, font=("Segoe UI", 9, "bold"), bg="#E2E8F0", fg="#1F2937", relief=tk.FLAT, padx=10)
    btn_none.pack(side=tk.LEFT, padx=5)

    # Action generate button
    def do_generate():
        selected = [group for group, var in checkbox_vars.items() if var.get()]
        if not selected:
            tkinter.messagebox.showwarning("Aucune sélection", "Veuillez cocher au moins un groupe à générer.")
            return

        start_val = ent_start.get().strip()
        end_val = ent_end.get().strip()
        
        # Validation des dates
        if start_val or end_val:
            if not start_val or not end_val:
                tkinter.messagebox.showerror("Saisie incomplète", "Veuillez saisir à la fois une date de début et une date de fin (ou laisser les deux vides).")
                return
                
            try:
                dt_start = datetime.datetime.strptime(start_val, "%d/%m/%Y")
            except ValueError:
                tkinter.messagebox.showerror("Format invalide", "La date de début n'est pas au format valide (JJ/MM/AAAA).\nExemple : 15/09/2026")
                return
                
            try:
                dt_end = datetime.datetime.strptime(end_val, "%d/%m/%Y")
            except ValueError:
                tkinter.messagebox.showerror("Format invalide", "La date de fin n'est pas au format valide (JJ/MM/AAAA).\nExemple : 30/06/2027")
                return
                
            if dt_start > dt_end:
                tkinter.messagebox.showerror("Dates incohérentes", "La date de début doit être antérieure ou égale à la date de fin.")
                return

        top.destroy()
        parent.update()
        
        try:
            success, result = generate_presence_sheets(selected, participants_data, start_val, end_val)
            if success:
                tkinter.messagebox.showinfo("Génération Réussie", f"Génération accomplie !\n{len(result)} fichier(s) ont été créés dans le dossier 'liste adhérent' :\n\n" + "\n".join(result))
            else:
                tkinter.messagebox.showerror("Erreur de Génération", f"Une erreur s'est produite : {result}")
        except Exception as ex:
            tkinter.messagebox.showerror("Erreur Critique", f"Une exception s'est produite lors de la génération : {ex}")

    btn_frame = tk.Frame(top, bg="#F0F4F8", pady=10)
    btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

    btn_generate = tk.Button(btn_frame, text="🚀 Générer les listes Excel", command=do_generate, font=("Segoe UI", 10, "bold"), bg="#06B6D4", fg="white", relief=tk.FLAT, padx=20, pady=8)
    btn_generate.pack(pady=5)

def normalize_text(text):
    if not text:
        return ""
    import unicodedata
    nfkd_form = unicodedata.normalize('NFKD', str(text).strip().lower())
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def load_license_data():
    """Charge les passeports et diplômes depuis le fichier d'export des licenciés."""
    import pandas as pd
    root_dir = ROOT_DIR
    # Trouver le fichier Export_Licencies_*.xlsx
    files = glob.glob(os.path.join(root_dir, "Export_Licencies_david_lopez_*.xlsx"))
    if not files:
        # Essayer à la racine courante
        files = glob.glob(os.path.join(os.getcwd(), "Export_Licencies_david_lopez_*.xlsx"))
        
    if not files:
        print("[LICENSE DATA] Aucun fichier d'export de licenciés 'Export_Licencies_david_lopez_*.xlsx' trouvé.")
        return {}, {}
        
    lic_file = files[0]
    print(f"[LICENSE DATA] Chargement du fichier des licenciés : {os.path.basename(lic_file)}")
    try:
        df = pd.read_excel(lic_file)
        df = df.fillna("")
        
        mapping_by_lic = {}
        mapping_by_name = {}
        for idx, row in df.iterrows():
            raw_lic = str(row.get("N° de licence", "")).strip()
            if raw_lic.endswith(".0"):
                raw_lic = raw_lic[:-2]
            lic_num = "".join(c for c in raw_lic if c.isdigit())
            if not lic_num:
                continue
                
            nom = normalize_text(row.get("Nom", ""))
            prenom = normalize_text(row.get("Prénom", ""))
            name_key = (nom, prenom)
            
            passports_raw = str(row.get("Passeports", "")).strip()
            diplomas_raw = str(row.get("Diplômes", "")).strip()
            
            # Parser par virgule
            passports = [p.strip() for p in passports_raw.split(",") if p.strip()]
            diplomas = [d.strip() for d in diplomas_raw.split(",") if d.strip()]
            
            info = {
                "lic_num": lic_num,
                "passports": passports,
                "diplomas": diplomas,
                "raw_passports": passports_raw,
                "raw_diplomas": diplomas_raw
            }
            mapping_by_lic[lic_num] = info
            mapping_by_name[name_key] = info
            
        print(f"[LICENSE DATA] Mappé {len(mapping_by_lic)} licences avec leurs passeports et diplômes.")
        return mapping_by_lic, mapping_by_name
    except Exception as e:
        print(f"[LICENSE DATA] Erreur lors du chargement des licences : {e}")
        return {}, {}

def load_autonomous_data():
    """Charge les informations d'autonomie (Badge rouge diff, Autonomie Bloc) depuis Autonomes_2026-06-30.xlsx."""
    import pandas as pd
    root_dir = ROOT_DIR
    # Trouver le fichier Autonomes_*.xlsx
    files = glob.glob(os.path.join(root_dir, "Autonomes_*.xlsx"))
    if not files:
        files = glob.glob(os.path.join(os.getcwd(), "Autonomes_*.xlsx"))
        
    if not files:
        print("[AUTONOMES DATA] Aucun fichier d'autonomie 'Autonomes_*.xlsx' trouvé.")
        return {}
        
    aut_file = files[0]
    print(f"[AUTONOMES DATA] Chargement du fichier autonomie : {os.path.basename(aut_file)}")
    try:
        # Lire le fichier excel, en sautant la ligne de titre (header=1)
        df = pd.read_excel(aut_file, header=1)
        df = df.fillna("")
        
        mapping = {}
        for idx, row in df.iterrows():
            raw_lic = str(row.get("N° de licence", "")).strip()
            if raw_lic.endswith(".0"):
                raw_lic = raw_lic[:-2]
            lic_num = "".join(c for c in raw_lic if c.isdigit())
            if not lic_num:
                continue
                
            badge_rouge_raw = str(row.get("Badge rouge diff", "")).strip().upper()
            autonomie_bloc_raw = str(row.get("Autonomie Bloc", "")).strip().upper()
            
            badge_rouge = "Oui" if badge_rouge_raw == "X" else ("Non" if not badge_rouge_raw else badge_rouge_raw)
            autonomie_bloc = "Oui" if autonomie_bloc_raw == "X" else ("Non" if not autonomie_bloc_raw else autonomie_bloc_raw)
            
            mapping[lic_num] = {
                "badge_rouge": badge_rouge,
                "autonomie_bloc": autonomie_bloc
            }
        print(f"[AUTONOMES DATA] Mappé {len(mapping)} licences avec leurs badges autonomie.")
        return mapping
    except Exception as e:
        print(f"[AUTONOMES DATA] Erreur lors du chargement des autonomes : {e}")
        return {}

def open_statistics_window(parent, participants_data):
    import tkinter as tk
    from tkinter import ttk
    from collections import Counter
    import datetime

    valid_participants = []
    for p in participants_data:
        t_name = str(p.get("tarif_name", "")).lower()
        amount = p.get("amount", 0.0)
        status = str(p.get("status", "")).lower()
        if "attente" in t_name or amount == 0.0 or "annul" in status:
            continue
        valid_participants.append(p)

    if not valid_participants:
        import tkinter.messagebox
        tkinter.messagebox.showwarning("Aucune donnée", "Aucun adhérent valide pour générer les statistiques.")
        return

    top = tk.Toplevel(parent)
    top.title("📊 Statistiques Détaillées")
    top.geometry("900x700")
    top.configure(bg="#F0F4F8")
    
    # Centre window
    top.transient(parent)
    top.grab_set()

    notebook = ttk.Notebook(top)
    notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    def create_tab(title):
        frame = tk.Frame(notebook, bg="#FFFFFF", padx=10, pady=10)
        notebook.add(frame, text=title)
        
        canvas = tk.Canvas(frame, bg="#FFFFFF", highlightthickness=0)
        scrollbar = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scroll_inner = tk.Frame(canvas, bg="#FFFFFF")
        
        scroll_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return scroll_inner

    # 1. Tarif
    tab_tarif = create_tab("Par Tarif")
    counter_tarif = Counter([str(p.get("tarif_name", "")).strip() for p in valid_participants if p.get("tarif_name")])
    tk.Label(tab_tarif, text="Nombre d'adhérents par Tarif", font=("Segoe UI", 12, "bold"), bg="#FFFFFF", pady=10).pack()
    for tarif, count in counter_tarif.most_common():
        tk.Label(tab_tarif, text=f"{tarif} : {count}", font=("Segoe UI", 10), bg="#FFFFFF").pack(anchor="w", pady=2)

    # 2. Ville
    tab_ville = create_tab("Par Ville")
    from domain.utils import clean_city_name
    counter_ville = Counter([clean_city_name(p.get("champ_Ville", "")) for p in valid_participants if p.get("champ_Ville")])
    tk.Label(tab_ville, text="Nombre d'adhérents par Ville", font=("Segoe UI", 12, "bold"), bg="#FFFFFF", pady=10).pack()
    for ville, count in counter_ville.most_common():
        tk.Label(tab_ville, text=f"{ville if ville else 'INCONNUE'} : {count}", font=("Segoe UI", 10), bg="#FFFFFF").pack(anchor="w", pady=2)

    # 3. Âge
    tab_age = create_tab("Par Âge")
    age_groups = {"Moins de 10 ans": 0, "10-13 ans": 0, "14-17 ans": 0, "18-34 ans": 0, "35 ans et +": 0, "Non spécifié": 0}
    for p in valid_participants:
        dob = p.get("champ_Date de naissance de l'adhérent", "")
        dt_dob = None
        if isinstance(dob, (datetime.datetime, datetime.date)): dt_dob = dob
        elif isinstance(dob, str) and dob.strip(): dt_dob = parse_date_to_datetime(dob.strip())
        
        if isinstance(dt_dob, (datetime.datetime, datetime.date)):
            try:
                now = datetime.datetime.now()
                age = now.year - dt_dob.year - ((now.month, now.day) < (dt_dob.month, dt_dob.day))
                if age < 10: age_groups["Moins de 10 ans"] += 1
                elif age <= 13: age_groups["10-13 ans"] += 1
                elif age <= 17: age_groups["14-17 ans"] += 1
                elif age <= 34: age_groups["18-34 ans"] += 1
                else: age_groups["35 ans et +"] += 1
            except Exception: age_groups["Non spécifié"] += 1
        else: age_groups["Non spécifié"] += 1
        
    tk.Label(tab_age, text="Répartition par Tranche d'Âge", font=("Segoe UI", 12, "bold"), bg="#FFFFFF", pady=10).pack()
    for k, v in age_groups.items():
        tk.Label(tab_age, text=f"{k} : {v}", font=("Segoe UI", 10), bg="#FFFFFF").pack(anchor="w", pady=2)

    # 4. Inscription
    tab_date = create_tab("Par Date")
    counter_date = Counter()
    for p in valid_participants:
        d = p.get("order_date", "")
        if isinstance(d, (datetime.datetime, datetime.date)):
            counter_date[d.strftime("%Y-%m-%d")] += 1
        elif isinstance(d, str) and d.strip():
            pd = parse_date_to_datetime(d.strip())
            if isinstance(pd, (datetime.datetime, datetime.date)): counter_date[pd.strftime("%Y-%m-%d")] += 1
            
    tk.Label(tab_date, text="Inscriptions par Date", font=("Segoe UI", 12, "bold"), bg="#FFFFFF", pady=10).pack()
    for d_str, count in sorted(counter_date.items()):
        tk.Label(tab_date, text=f"{d_str} : {count}", font=("Segoe UI", 10), bg="#FFFFFF").pack(anchor="w", pady=2)

    # 5. Noms / Prénoms
    tab_noms = create_tab("Noms/Prénoms")
    counter_nom = Counter([str(p.get("user_lastName", "")).strip().upper() for p in valid_participants if p.get("user_lastName")])
    counter_prenom = Counter([str(p.get("user_firstName", "")).strip().capitalize() for p in valid_participants if p.get("user_firstName")])
    
    tk.Label(tab_noms, text="Top 10 Noms de Famille", font=("Segoe UI", 11, "bold"), bg="#FFFFFF", pady=5).pack()
    for n, c in counter_nom.most_common(10):
        tk.Label(tab_noms, text=f"{n} : {c}", font=("Segoe UI", 10), bg="#FFFFFF").pack(anchor="w", pady=1)
        
    tk.Label(tab_noms, text="Top 10 Prénoms", font=("Segoe UI", 11, "bold"), bg="#FFFFFF", pady=10).pack()
    for p_name, c in counter_prenom.most_common(10):
        tk.Label(tab_noms, text=f"{p_name} : {c}", font=("Segoe UI", 10), bg="#FFFFFF").pack(anchor="w", pady=1)

def launch_gui():
    print("-----------------------------------------------------------------")
    print("L'ancienne interface Tkinter a été retirée au profit de PySide6.")
    print("Pour lancer l'application moderne ALJ Escalade, exécutez :")
    print("  python src/app.py (ou double-cliquez sur run_app.bat)")
    print("-----------------------------------------------------------------")
    return

if __name__ == "__main__":
    launch_gui()
