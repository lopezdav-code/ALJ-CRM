import os
import sys
import glob
import pandas as pd
import datetime
import csv

from paths import CODE_ROOT, ROOT_DIR
from domain.constants import (
    get_active_season
)
from infrastructure.secret_store import SecretStore
from infrastructure.google_drive_client import GoogleDriveClient
from domain.utils import normalize_name

# S'assurer que le répertoire de travail et le répertoire du script sont dans le chemin de recherche
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)
if CODE_ROOT not in sys.path:
    sys.path.append(CODE_ROOT)

# Phase 3 — mapping canonique unique (domain.constants), fin de la duplication
from infrastructure.schema_v2 import purchase_priority_score

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

        # Phase 3 — table de priorité des statuts centralisée (infrastructure.schema_v2)
        def get_priority_score(status, tarif_name, amount):
            return purchase_priority_score(status, tarif_name, amount)
        
        for p in existing_participants:
            o_ref = str(p.get("order_ref", "")).strip()
            if o_ref.endswith(".0"):
                o_ref = o_ref[:-2]
                
            f_name = normalize_name(p.get("first_name", ""))
            l_name = normalize_name(p.get("last_name", ""))
            existing_keys.add((o_ref, f_name, l_name))
            
            # Calculer et enregistrer le score maximal existant pour cet adhérent
            score_existing = get_priority_score(p.get("status"), p.get("tarif_name"), p.get("amount"))
            key_member = (f_name, l_name)
            existing_member_max_score[key_member] = max(existing_member_max_score.get(key_member, -999), score_existing)
            
            # Incrémenter le compteur de commandes dans la BDD
            if o_ref:
                excel_order_counts[o_ref] += 1
            
            # Extraire la licence FFME de la BDD
            lic_val = str(p.get("licence_ffme", "")).strip()
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



def generate_ffme_csv(participants_data, output_path=None):
    """
    Génère le CSV d'import FFME.
    Si output_path est fourni (tests de non-régression), écrit à cet emplacement exact
    sans horodatage ni archivage. Sinon, comportement historique : fichier horodaté
    dans exports/ffme/ avec archivage des anciens CSV.
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
        ffme_dir = os.path.join(root_dir, "exports", "ffme")
        os.makedirs(ffme_dir, exist_ok=True)
        csv_path = os.path.join(ffme_dir, csv_filename)

        # Archiver les anciens fichiers import_ffme
        archive_dir = os.path.join(ffme_dir, "archive")
        os.makedirs(archive_dir, exist_ok=True)
        import shutil
        for old_file in glob.glob(os.path.join(ffme_dir, "import_ffme_*.csv")):
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
        # Phase 6 — Normalisation NULL : les valeurs None du schéma v2 (vue legacy) sont
        # converties en chaîne vide AVANT traitement, supprimant les artefacts str(None)
        # historiques ('NO' pays, 'none' courriel 2, 'NONE' pap, 'None' adresse/ville).
        p = {k: (v if v is not None else "") for k, v in p.items()}

        # Exclure les listes d'attente, montants nuls (sauf les ajouts manuels), commandes annulées/canceled ou déjà validées (terminé)
        tarif_name = str(p.get("tarif_name", "")).lower()
        amount = p.get("amount", 0.0)
        status = str(p.get("status", "")).lower()
        commentaires = str(p.get("commentaires_correctif", "")).lower()
        is_manual = "ajout manuel" in commentaires
        
        if "attente" in tarif_name or (amount == 0.0 and not is_manual) or "annul" in status or "cancel" in status or "termin" in status:
            continue

        nom = str(p.get("last_name", "")).strip().upper()
        if not nom: nom = "INCONNU"

        prenom = str(p.get("first_name", "")).strip()
        if not prenom: prenom = "INCONNU"

        # 1. Licence
        lic_num = clean_digits_only(p.get("licence_ffme", ""))
        if len(lic_num) < 5 or len(lic_num) > 10:
            lic_num = ""

        # 2. DOB
        dob_val = p.get("birth_date", "")
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
        sexe_raw = str(p.get("gender", "")).strip().upper()
        if sexe_raw.startswith(("M", "H", "G")):
            sexe = "H"
        elif sexe_raw.startswith(("F", "D")):
            sexe = "F"
        else:
            sexe = "" if lic_num else "H"
            
        # 4. Pays
        pays_raw = str(p.get("country", "France")).strip().upper()
        pays = "FR" if "FR" in pays_raw or pays_raw == "FRANCE" or pays_raw == "" else pays_raw[:2]
        if not pays and not lic_num:
            pays = "FR"
            
        # 5. Nationalité
        nat_raw = str(p.get("nationality", "Francaise")).strip().upper()
        if "FR" in nat_raw or nat_raw == "FRANCE" or nat_raw == "":
            nat = "FR"
        elif "SUED" in nat_raw or "SWE" in nat_raw:
            nat = "SE"
        elif len(nat_raw) == 2:
            nat = nat_raw
        else:
            nat = "FR" if not lic_num else ""
            
        # 6. Adresse
        adresse = str(p.get("address", "")).strip()[:255]
        if not adresse and not lic_num:
            adresse = "ADRESSE NON COMMUNIQUEE"
            
        # 7. Code postal
        cp = clean_digits_only(p.get("zip_code", ""))
        if pays == "FR":
            if cp:
                cp = cp.zfill(5)[:5]
            else:
                cp = "69330" if not lic_num else ""
        else:
            cp = cp[:10]
            
        # 8. Ville
        ville = str(p.get("city", "")).strip().upper()[:100]
        if not ville and not lic_num:
            ville = "JONAGE"
            
        # 9. Téléphones
        tel_raw = clean_digits_only(p.get("phone", ""))
        if pays == "FR" and tel_raw:
            if tel_raw.startswith("33"):
                tel_raw = "0" + tel_raw[2:]
            tel_raw = tel_raw[:10]
        tel = tel_raw
        
        # 10. Courriels
        email = str(p.get("email_primary", "")).strip().lower()[:100]
        if not email:
            email = str(p.get("payer_email", "")).strip().lower()[:100]
        if not email and not lic_num:
            email = "contact@amicale-laique-jonage.fr"
            
        email2 = str(p.get("email_secondary", "")).strip().lower()[:100]
        
        # 11. PAP
        pap_raw = str(p.get("emergency1_name", "")).strip()
        pap_nom = ""
        pap_prenom = ""
        if pap_raw:
            if " " in pap_raw:
                parts = pap_raw.split(" ", 1)
                pap_prenom = parts[0][:100]
                pap_nom = parts[1].upper()[:100]
            else:
                pap_nom = pap_raw.upper()[:100]
                
        pap_tel = clean_digits_only(p.get("emergency1_phone", ""))[:15]
        
        # 12. Type licence (J, A, F)
        is_tribu = str(p.get("is_tribe", "")).lower()
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













