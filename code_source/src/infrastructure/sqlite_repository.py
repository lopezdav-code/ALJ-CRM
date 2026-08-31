import os
import sqlite3
import datetime
import pandas as pd
import json
from paths import CODE_ROOT, ROOT_DIR
from infrastructure.secret_store import SecretStore
from domain.constants import CORRECTIVE_MAP
from infrastructure import schema_v2

EXTRA_COLUMNS = {
    "is_modified": "TEXT DEFAULT 'Non'",
    "commentaires_correctif": "TEXT DEFAULT ''",
    "badge_rouge": "TEXT DEFAULT 'Non'",
    "autonomie_bloc": "TEXT DEFAULT 'Non'",
    "raw_passports": "TEXT DEFAULT ''",
    "raw_diplomas": "TEXT DEFAULT ''",
    "parental_auth_autonomous": "TEXT DEFAULT 'Non'", # Nouveau !
    "parental_auth_family": "TEXT DEFAULT 'Non'",     # Nouveau !
}

# Phase 0 — Versionnement du schéma (PRAGMA user_version) :
#   1 = schéma legacy (adherents / adherents_seasons)
#   2 = schéma cible (users / orders / purchases / purchase_options, voir migrate_schema_v2.py)
SCHEMA_VERSION = 1

# Phase 2 — Vue de compatibilité : reproduit le format plat legacy (colonnes champ_* / opt_*)
# à partir du schéma cible users / orders / purchases / purchase_options.
# Stratégie strangler : le code existant lit cette vue sans modification.
# Les options d'assurance sont exposées au niveau user (achat porteur de la saison active),
# reproduisant l'emplacement legacy (colonnes opt_* de la table adherents).
COMPAT_VIEW_SQL = """
CREATE VIEW IF NOT EXISTS v_adherents_legacy AS
SELECT
    u.legacy_adherent_id AS "id",
    u.id AS "user_id",
    u.last_name AS "user_lastName",
    u.first_name AS "user_firstName",
    u.birth_date_raw AS "champ_Date de naissance de l'adhérent",
    u.gender AS "champ_Sexe",
    u.nationality AS "champ_Nationalité",
    u.address AS "champ_Adresse : numéro et nom de rue",
    u.zip_code AS "champ_Code postal",
    u.city AS "champ_Ville",
    u.country AS "champ_Pays",
    u.phone AS "champ_Téléphone ",
    u.email_primary AS "champ_Adresse mail pour la réception des informations du club",
    u.email_secondary AS "champ_Deuxième adresse mail pour la réception des informations du club",
    u.emergency1_name AS "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule",
    u.emergency1_phone AS "champ_Personne à prévenir en cas d'urgence - Téléphone",
    u.emergency2_name AS "champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)",
    u.emergency2_phone AS "champ_Parent 2 - Numéro de téléphone portable",
    u.photo_auth AS "champ_En cas de prise de vue (Photo ou vidéo), j'autorise à ce que l'image de mon enfant (cours enfants) ou la mienne (créneau adultes) puisse être utilisée par l'Amicale Laïque de Jonage à des fins non commerciales",
    u.health_commitment AS "champ_Je m'engage à compléter mon questionnaire de santé ou téléverser mon certificat médical sur le site  https://www.myffme.fr à réception du mail de confirmation d'adhésion, pour mon enfant (cours enfants) ou moi-même (créneau adultes)",
    p.is_tribe AS "champ_Famille : nous sommes une tribu de 3 ou plus inscrits ce qui permet un code de réduction : FAMILLE",
    u.licence_ffme AS "champ_Numéro de Licence FFME (6 chiffres)",
    (SELECT CASE WHEN po2.id IS NOT NULL THEN 'Oui' END
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Base' LIMIT 1) AS "opt_Assurance Base",
    (SELECT po2.amount
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Base' LIMIT 1) AS "opt_Montant Assurance Base",
    (SELECT CASE WHEN po2.id IS NOT NULL THEN 'Oui' END
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Base +' LIMIT 1) AS "opt_Assurance Base +",
    (SELECT po2.amount
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Base +' LIMIT 1) AS "opt_Montant Assurance Base +",
    (SELECT CASE WHEN po2.id IS NOT NULL THEN 'Oui' END
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Base ++' LIMIT 1) AS "opt_Assurance Base ++",
    (SELECT po2.amount
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Base ++' LIMIT 1) AS "opt_Montant Assurance Base ++",
    (SELECT CASE WHEN po2.id IS NOT NULL THEN 'Oui' END
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Option ski de piste' LIMIT 1) AS "opt_Assurance Option ski de piste",
    (SELECT po2.amount
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Option ski de piste' LIMIT 1) AS "opt_Montant Assurance Option ski de piste",
    (SELECT CASE WHEN po2.id IS NOT NULL THEN 'Oui' END
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Option VTT' LIMIT 1) AS "opt_Assurance Option VTT",
    (SELECT po2.amount
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Option VTT' LIMIT 1) AS "opt_Montant Assurance Option VTT",
    (SELECT CASE WHEN po2.id IS NOT NULL THEN 'Oui' END
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Option Trail' LIMIT 1) AS "opt_Assurance Option Trail",
    (SELECT po2.amount
       FROM purchase_options po2 JOIN purchases p2 ON p2.id = po2.purchase_id
      WHERE p2.user_id = u.id AND po2.option_name = 'Assurance Option Trail' LIMIT 1) AS "opt_Montant Assurance Option Trail",
    u.badge_rouge AS "badge_rouge",
    u.autonomie_bloc AS "autonomie_bloc",
    u.raw_passports AS "raw_passports",
    u.raw_diplomas AS "raw_diplomas",
    u.parental_auth_autonomous AS "parental_auth_autonomous",
    u.parental_auth_family AS "parental_auth_family",
    o.order_ref AS "order_ref",
    o.order_date AS "order_date",
    p.tarif_name AS "tarif_name",
    p.amount AS "amount",
    p.status AS "status",
    p.is_modified AS "is_modified",
    p.commentaires_correctif AS "commentaires_correctif",
    p.email_sent_date AS "email_sent_date",
    s.name AS "season_name",
    (SELECT COUNT(*) FROM purchases p3
      WHERE p3.user_id = u.id AND p3.legacy_season_id != p.legacy_season_id) AS "already_member"
FROM purchases p
JOIN users u ON u.id = p.user_id
JOIN orders o ON o.id = p.order_id
JOIN seasons s ON s.id = o.season_id
"""

class SqliteRepository:
    """
    Gère la persistance locale ultra-légère dans une base de données SQLite des adhérents.
    """
    _db_path = os.path.join(ROOT_DIR, "database.db")
    _database_setup_done = False
    _startup_db_hash = None

    @classmethod
    def get_db_path(cls) -> str:
        return cls._db_path

    @classmethod
    def set_db_path(cls, path: str):
        cls._db_path = path
        cls._database_setup_done = False
        cls._startup_db_hash = None

    @classmethod
    def get_file_hash(cls) -> str:
        """Calcule le hash SHA-256 du fichier de base de données SQLite courant."""
        import hashlib
        if not os.path.exists(cls._db_path):
            return ""
        sha = hashlib.sha256()
        try:
            with open(cls._db_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha.update(chunk)
            return sha.hexdigest()
        except Exception:
            return ""

    @classmethod
    def get_connection(cls):
        conn = sqlite3.connect(cls._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        return conn

    @classmethod
    def setup_database(cls, force: bool = False):
        """Initialise la base de données et crée les tables requises."""
        if not force and cls._database_setup_done:
            return
        print(f"🔧 [SQLITE] Initialisation de la BDD à l'emplacement : {cls._db_path}")
        conn = cls.get_connection()
        cursor = conn.cursor()

        # Construction dynamique de la table d'adhérents à partir de CORRECTIVE_MAP
        columns = []
        for key in CORRECTIVE_MAP.values():
            if key == "amount" or key.startswith("opt_Montant"):
                columns.append(f'"{key}" REAL')
            else:
                columns.append(f'"{key}" TEXT')

        for extra_col, col_type in EXTRA_COLUMNS.items():
            columns.append(f'"{extra_col}" {col_type}')

        # Clé primaire composite pour identifier de manière unique un adhérent
        columns_sql = ", ".join(columns)
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS adherents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {columns_sql},
            UNIQUE(order_ref, user_lastName, user_firstName)
        );
        """
        cursor.execute(create_table_sql)
        
        # Création d'index pour optimiser les recherches
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_ref ON adherents(order_ref);')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_names ON adherents(user_lastName, user_firstName);')
        
        # Création des tables de saisons (Nouveau !)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 0
        );
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS adherents_seasons (
            adherent_id INTEGER,
            season_id INTEGER,
            order_ref TEXT,
            order_date TEXT,
            tarif_name TEXT,
            amount REAL,
            status TEXT,
            is_modified TEXT DEFAULT 'Non',
            commentaires_correctif TEXT DEFAULT '',
            email_sent_date TEXT,
            PRIMARY KEY(adherent_id, season_id),
            FOREIGN KEY(adherent_id) REFERENCES adherents(id) ON DELETE CASCADE,
            FOREIGN KEY(season_id) REFERENCES seasons(id) ON DELETE CASCADE
        );
        """)
        
        # Insérer les saisons par défaut
        cursor.execute("INSERT OR IGNORE INTO seasons (name, is_active) VALUES ('2025-2026', 0)")
        cursor.execute("INSERT OR IGNORE INTO seasons (name, is_active) VALUES ('2026-2027', 1)")
        
        # Vérification et migration de la saison 2026-2027 si vide (Nouveau !)
        cursor.execute("SELECT COUNT(*) FROM adherents_seasons")
        cnt_link = cursor.fetchone()[0]
        if cnt_link == 0:
            cursor.execute("SELECT id FROM seasons WHERE name = '2026-2027'")
            season_id = cursor.fetchone()[0]
            
            # Charger tous les adhérents existants de la BDD
            cursor.execute("""
                SELECT id, order_ref, order_date, tarif_name, amount, status, is_modified, commentaires_correctif, email_sent_date
                FROM adherents
            """)
            existing_adherents = cursor.fetchall()
            
            links_to_insert = []
            for adj in existing_adherents:
                adj_id = adj["id"]
                status_raw = str(adj["status"] or "").strip().lower()
                tarif_raw = str(adj["tarif_name"] or "").strip().lower()
                
                # Exclure les abandons et la liste d'attente (votre demande !)
                if "abandon" in status_raw:
                    continue
                if "attente" in tarif_raw and "liste" in tarif_raw:
                    continue
                    
                links_to_insert.append((
                    adj_id,
                    season_id,
                    adj["order_ref"],
                    adj["order_date"],
                    adj["tarif_name"],
                    adj["amount"],
                    adj["status"],
                    adj["is_modified"] or "Non",
                    adj["commentaires_correctif"] or "",
                    adj["email_sent_date"]
                ))
                
            if links_to_insert:
                cursor.executemany("""
                    INSERT OR REPLACE INTO adherents_seasons (
                        adherent_id, season_id, order_ref, order_date, tarif_name, amount, status, is_modified, commentaires_correctif, email_sent_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, links_to_insert)
                print(f"📦 [SQLITE] Initialisation multi-saisons : {len(links_to_insert)} adhérents rattachés à la saison 2026-2027.")
                
        # Initialisation automatique de la saison historique 2025-2026 (Nouveau !)
        import sys
        if "test" not in cls.get_db_path().lower() and "unittest" not in sys.modules:
            cursor.execute("SELECT id FROM seasons WHERE name = '2025-2026'")
            row_s25 = cursor.fetchone()
            if row_s25:
                season_25_id = row_s25["id"]
                cursor.execute("SELECT COUNT(*) FROM adherents_seasons WHERE season_id = ?", (season_25_id,))
                cnt_25 = cursor.fetchone()[0]
                if cnt_25 == 0:
                    hist_excel_path = os.path.join(ROOT_DIR, "import", "ffme", "Export_Licencies_david_lopez_50_2026-08-28-15-30-00 Saison 2025-2026.xlsx")
                    if not os.path.exists(hist_excel_path):
                        hist_excel_path = os.path.join(CODE_ROOT, "import", "ffme", "Export_Licencies_david_lopez_50_2026-08-28-15-30-00 Saison 2025-2026.xlsx")
                    
                    if os.path.exists(hist_excel_path):
                        print(f"🚀 [SQLITE] Initialisation automatique de la saison 2025-2026 depuis {os.path.basename(hist_excel_path)}...")
                        # Valider la transaction en cours, fermer pour l'importateur, puis réouvrir
                        conn.commit()
                        conn.close()
                        cls.import_old_season_ffme(hist_excel_path, "2025-2026")
                        conn = cls.get_connection()
                        cursor = conn.cursor()
        
        # Création de la table de cache géocodage
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS geocache (
            address TEXT PRIMARY KEY,
            lat REAL,
            lon REAL
        );
        """)

        # Création de la table de planning
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS planning (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            groupe TEXT NOT NULL,
            type TEXT,
            categorie_age TEXT,
            whatsapp_link TEXT,
            jour TEXT,
            horaires TEXT,
            encadrants TEXT,
            helloasso_tarifs TEXT DEFAULT '[]'
        );
        """)
        
        # S'assurer de la présence de la colonne helloasso_tarifs pour les BDD existantes (migration auto)
        try:
            cursor.execute("SELECT helloasso_tarifs FROM planning LIMIT 1")
        except sqlite3.OperationalError:
            print("🔧 [SQLITE] Ajout de la colonne 'helloasso_tarifs' à la table planning...")
            cursor.execute("ALTER TABLE planning ADD COLUMN helloasso_tarifs TEXT DEFAULT '[]'")
            conn.commit()
        
        # S'assurer de la présence des colonnes d'autorisations parentales pour les BDD existantes (migration auto via PRAGMA) (Nouveau !)
        cursor.execute("PRAGMA table_info(adherents)")
        existing_cols = [row["name"] for row in cursor.fetchall()]
        for col_name in ("parental_auth_autonomous", "parental_auth_family"):
            if col_name not in existing_cols:
                print(f"🔧 [SQLITE] Ajout de la colonne '{col_name}' à la table adherents...")
                cursor.execute(f'ALTER TABLE adherents ADD COLUMN "{col_name}" TEXT DEFAULT "Non"')
                conn.commit()

        # Création de la table de templates d'email (Nouveau !)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL
        );
        """)
        
        # Seed des templates par défaut si vides (Nouveau !)
        cursor.execute("SELECT COUNT(*) FROM email_templates")
        cnt_tmpl = cursor.fetchone()[0]
        if cnt_tmpl == 0:
            default_templates = [
                ("Attestation standard", "Attestation de paiement escalade - Amicale Laïque de Jonage", 
                 "Bonjour {first_name},\n\nNous avons le plaisir de vous transmettre en pièce jointe l'attestation de paiement pour votre adhésion ou celle de votre enfant à la section escalade de l'Amicale Laïque de Jonage pour la saison.\n\nSportivement,\nL'équipe ALJ Escalade"),
                ("Relance inscription", "Rappel : Finalisation de votre inscription ALJ Escalade", 
                 "Bonjour {first_name},\n\nSauf erreur de notre part, il nous manque encore certains éléments pour finaliser votre dossier d'adhésion pour la saison.\nNous vous invitons à vous connecter sur votre espace licencié pour vérifier le statut de votre certificat médical.\n\nSportivement,\nL'équipe ALJ Escalade")
            ]
            cursor.executemany("""
                INSERT INTO email_templates (name, subject, body) VALUES (?, ?, ?)
            """, default_templates)
            conn.commit()
        
        # Phase 0/2 — Gestion de la version du schéma (PRAGMA user_version)
        cursor.execute("PRAGMA user_version")
        current_version = cursor.fetchone()[0]
        if current_version == 0:
            cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            print(f"🔖 [SQLITE] Schéma tagué en version {SCHEMA_VERSION} (legacy).")
        elif current_version >= 2:
            # Base migrée vers le schéma cible : s'assurer que la vue de compatibilité existe
            cursor.execute(COMPAT_VIEW_SQL)
            print("🔗 [SQLITE] Vue de compatibilité v_adherents_legacy vérifiée.")

        conn.commit()
        conn.close()
        print("✅ [SQLITE] Initialisation et vérification du schéma d'adhérents accomplies.")
        
        # Tenter la migration du JSON s'il existe
        cls.migrate_json_geocache()
        cls.migrate_json_planning()
        
        cls._database_setup_done = True
        
        # Enregistrer le hash initial après la première initialisation de la BDD
        if cls._startup_db_hash is None:
            cls._startup_db_hash = cls.get_file_hash()

    @classmethod
    def get_geocache(cls) -> dict:
        """Récupère tout le cache géocodage sous forme de dictionnaire {adresse: [lat, lon]}."""
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT address, lat, lon FROM geocache")
            rows = cursor.fetchall()
            return {row["address"]: [row["lat"], row["lon"]] for row in rows}
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors du chargement du geocache : {e}")
            return {}
        finally:
            conn.close()

    @classmethod
    def save_geocode(cls, address: str, lat: float, lon: float):
        """Sauvegarde ou met à jour les coordonnées d'une adresse dans la table de cache."""
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO geocache (address, lat, lon)
                VALUES (?, ?, ?)
                ON CONFLICT(address) DO UPDATE SET
                    lat = excluded.lat,
                    lon = excluded.lon
            """, (address, lat, lon))
            conn.commit()
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la sauvegarde du géocodage de '{address}' : {e}")
            conn.rollback()
        finally:
            conn.close()

    @classmethod
    def migrate_json_geocache(cls):
        """Migre les données du fichier historique doc/geo_cache.json vers la table geocache."""
        json_path = os.path.join(ROOT_DIR, "doc", "geo_cache.json")
        if not os.path.exists(json_path):
            # Essayer aussi dans CODE_ROOT / "doc"
            json_path = os.path.join(CODE_ROOT, "doc", "geo_cache.json")
            if not os.path.exists(json_path):
                # Essayer directement dans ROOT_DIR
                json_path = os.path.join(ROOT_DIR, "geo_cache.json")
                if not os.path.exists(json_path):
                    return

        # Vérifier si la table est déjà peuplée pour éviter une migration inutile
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM geocache")
            count = cursor.fetchone()["cnt"]
            if count > 0:
                return # Déjà migré ou déjà peuplé
        except Exception:
            return
        finally:
            conn.close()

        print(f"📦 [SQLITE] Migration du cache géographique historique depuis {json_path}...")
        conn = None
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            conn = cls.get_connection()
            cursor = conn.cursor()
            inserted = 0
            for addr, coords in data.items():
                if isinstance(coords, list) and len(coords) == 2:
                    lat, lon = coords[0], coords[1]
                    cursor.execute("""
                        INSERT INTO geocache (address, lat, lon)
                        VALUES (?, ?, ?)
                        ON CONFLICT(address) DO UPDATE SET lat=excluded.lat, lon=excluded.lon
                    """, (addr, lat, lon))
                    inserted += 1
            conn.commit()
            print(f"✅ [SQLITE] Migration réussie de {inserted} adresses géocodées.")
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la migration du fichier json geocache : {e}")
        finally:
            if conn:
                conn.close()

    @classmethod
    def create_db_backup(cls):
        """Crée une sauvegarde de sécurité horodatée de la base de données dans archive/db avec rétention de 10 jours (Nouveau !)."""
        import shutil
        import glob
        import datetime
        import time
        
        db_path = cls.get_db_path()
        if not os.path.exists(db_path):
            return
            
        backup_dir = os.path.join(ROOT_DIR, "archive", "db")
        os.makedirs(backup_dir, exist_ok=True)
        
        # Éviter de sur-sauvegarder si la base n'a pas changé ou si la dernière sauvegarde a moins de 5 secondes
        backups = glob.glob(os.path.join(backup_dir, "database_backup_*.db"))
        if backups:
            backups.sort(key=os.path.getmtime, reverse=True)
            latest_backup = backups[0]
            # Si la base de données n'a pas été modifiée depuis le dernier backup, on ignore la sauvegarde
            if os.path.getmtime(db_path) <= os.path.getmtime(latest_backup):
                return
            if time.time() - os.path.getmtime(latest_backup) < 5:
                return
        
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"database_backup_{now_str}.db")

        try:
            # API backup SQLite : snapshot cohérent (inclut le journal WAL), contrairement
            # à une copie fichier brute qui peut capturer un état incohérent.
            src_conn = cls.get_connection()
            dst_conn = sqlite3.connect(backup_path)
            src_conn.backup(dst_conn)
            dst_conn.close()
            src_conn.close()
            print(f"💾 [SQLITE] Sauvegarde de BDD créée : {os.path.basename(backup_path)}")
            
            # Gérer la rétention : conserver toutes les sauvegardes des 10 derniers jours (Nouveau !)
            backups = glob.glob(os.path.join(backup_dir, "database_backup_*.db"))
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=10)
            
            for bk in backups:
                try:
                    mtime = os.path.getmtime(bk)
                    file_date = datetime.datetime.fromtimestamp(mtime)
                    if file_date < cutoff_date:
                        os.remove(bk)
                        print(f"🗑️ [SQLITE] Sauvegarde BDD expirée (>10 jours) purgée : {os.path.basename(bk)}")
                except Exception as pe:
                    print(f"⚠️ [SQLITE] Impossible de purger l'ancien backup {bk} : {pe}")
                    
        except Exception as e:
            print(f"⚠️ [SQLITE] Impossible de créer la sauvegarde de BDD : {e}")

    @classmethod
    def load_direct_data(cls, season_filter: str = "2026-2027") -> list:
        """
        Charge les données d'adhérents depuis SQLite pour une saison spécifique ou un filtre comparatif.
        """
        # Résolution pour la rétrocompatibilité (si un chemin de fichier Excel .xlsx est passé)
        if isinstance(season_filter, str) and (season_filter.endswith(".xlsx") or "\\" in season_filter or "/" in season_filter):
            season_filter = "2026-2027" # Par défaut

        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()

        # Phase 2 — Si la base est migrée (user_version >= 2), lire via la vue de compatibilité
        try:
            current_version = cursor.execute("PRAGMA user_version").fetchone()[0]
        except Exception:
            current_version = 0
        if current_version >= 2:
            try:
                return cls._load_data_from_compat_view(conn, season_filter)
            except Exception as e:
                print(f"❌ [SQLITE] Erreur lors du chargement via la vue de compatibilité : {e}")
                return []
            finally:
                conn.close()

        # Liste de toutes les colonnes personnelles de l'adhérent dans la table 'adherents' (Sans colonnes saisonnières !)
        personal_fields = [
            "id", "user_lastName", "user_firstName", "champ_Sexe", "champ_Nationalité",
            "champ_Date de naissance de l'adhérent", "champ_Adresse : numéro et nom de rue",
            "champ_Code postal", "champ_Ville", "champ_Pays", "champ_Téléphone ",
            "champ_Adresse mail pour la réception des informations du club",
            "champ_Deuxième adresse mail pour la réception des informations du club",
            "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule",
            "champ_Personne à prévenir en cas d'urgence - Téléphone",
            "champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)",
            "champ_Parent 2 - Numéro de téléphone portable",
            "champ_En cas de prise de vue (Photo ou vidéo), j'autorise à ce que l'image de mon enfant (cours enfants) ou la mienne (créneau adultes) puisse être utilisée par l'Amicale Laïque de Jonage à des fins non commerciales",
            "champ_Je m'engage à compléter mon questionnaire de santé ou téléverser mon certificat médical sur le site  https://www.myffme.fr à réception du mail de confirmation d'adhésion, pour mon enfant (cours enfants) ou moi-même (créneau adultes)",
            "champ_Famille : nous sommes une tribu de 3 ou plus inscrits ce qui permet un code de réduction : FAMILLE",
            "champ_Numéro de Licence FFME (6 chiffres)", "opt_Assurance Base", "opt_Montant Assurance Base",
            "opt_Assurance Base +", "opt_Montant Assurance Base +", "opt_Assurance Base ++", "opt_Montant Assurance Base ++",
            "opt_Assurance Option ski de piste", "opt_Montant Assurance Option ski de piste",
            "opt_Assurance Option VTT", "opt_Montant Assurance Option VTT", "opt_Assurance Option Trail",
            "opt_Montant Assurance Option Trail", "badge_rouge", "autonomie_bloc", "raw_passports", "raw_diplomas",
            "parental_auth_autonomous", "parental_auth_family"
        ]
        
        select_fields = ", ".join([f'a."{f}"' for f in personal_fields])

        try:
            # Si le filtre est "Tous" ou "Toutes les saisons"
            if season_filter in ("Tous", "Toutes les saisons", "Toutes les saisons confondues"):
                cursor.execute(f"""
                    SELECT {select_fields}, s.name as season_name,
                           las.order_ref, las.order_date, las.tarif_name, las.amount, las.status,
                           las.is_modified, las.commentaires_correctif, las.email_sent_date,
                           (SELECT COUNT(*) FROM adherents_seasons las2 WHERE las2.adherent_id = a.id AND las2.season_id != las.season_id) as already_member
                    FROM adherents a
                    JOIN adherents_seasons las ON a.id = las.adherent_id
                    JOIN seasons s ON las.season_id = s.id
                    ORDER BY a.id DESC
                """)

            # Si c'est le filtre spécial : Présents en 2025-2026 mais non réinscrits en 2026-2027
            elif season_filter in ("Non réinscrits", "Anciens (25-26) non réinscrits en 26-27", "Anciens non réinscrits (Présents en 25/26 mais pas en 26/27)"):
                cursor.execute(f"""
                    SELECT {select_fields}, '2025-2026' as season_name,
                           las.order_ref, las.order_date, las.tarif_name, las.amount, las.status,
                           las.is_modified, las.commentaires_correctif, las.email_sent_date,
                           (SELECT COUNT(*) FROM adherents_seasons las2 WHERE las2.adherent_id = a.id AND las2.season_id != las.season_id) as already_member
                    FROM adherents a
                    JOIN adherents_seasons las ON a.id = las.adherent_id
                    JOIN seasons s ON las.season_id = s.id
                    WHERE s.name = '2025-2026'
                      AND a.id NOT IN (
                          SELECT las2.adherent_id 
                          FROM adherents_seasons las2 
                          JOIN seasons s2 ON las2.season_id = s2.id 
                          WHERE s2.name = '2026-2027'
                      )
                    ORDER BY a.id DESC
                """)

            # Sinon, filtre classique sur une saison spécifique (ex: "2026-2027", "2025-2026")
            else:
                cursor.execute(f"""
                    SELECT {select_fields}, s.name as season_name,
                           las.order_ref, las.order_date, las.tarif_name, las.amount, las.status,
                           las.is_modified, las.commentaires_correctif, las.email_sent_date,
                           (SELECT COUNT(*) FROM adherents_seasons las2 WHERE las2.adherent_id = a.id AND las2.season_id != las.season_id) as already_member
                    FROM adherents a
                    JOIN adherents_seasons las ON a.id = las.adherent_id
                    JOIN seasons s ON las.season_id = s.id
                    WHERE s.name = ?
                    ORDER BY a.id DESC
                """, (season_filter,))

            rows = cursor.fetchall()
            participants_data = []
            for row in rows:
                row_dict = dict(row)
                # Supprimer le champ d'identifiant interne
                if "id" in row_dict:
                    row_dict.pop("id")
                participants_data.append(row_dict)
            return participants_data

        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors du chargement des données multi-saisons : {e}")
            return []
        finally:
            conn.close()

    @classmethod
    def _load_data_from_compat_view(cls, conn, season_filter: str) -> list:
        """Phase 2 — Chargement via v_adherents_legacy (schéma cible v2). Mêmes clés que le chemin legacy."""
        cursor = conn.cursor()
        if season_filter in ("Tous", "Toutes les saisons", "Toutes les saisons confondues"):
            cursor.execute('SELECT * FROM v_adherents_legacy ORDER BY "id" DESC')
        elif season_filter in ("Non réinscrits", "Anciens (25-26) non réinscrits en 26-27", "Anciens non réinscrits (Présents en 25/26 mais pas en 26/27)"):
            cursor.execute("""
                SELECT * FROM v_adherents_legacy
                WHERE season_name = '2025-2026'
                  AND "user_id" NOT IN (
                      SELECT "user_id" FROM v_adherents_legacy WHERE season_name = '2026-2027'
                  )
                ORDER BY "id" DESC
            """)
        else:
            cursor.execute('SELECT * FROM v_adherents_legacy WHERE season_name = ? ORDER BY "id" DESC', (season_filter,))

        rows = cursor.fetchall()
        participants_data = []
        for row in rows:
            row_dict = dict(row)
            # Supprimer le champ d'identifiant interne (comme le chemin legacy)
            row_dict.pop("id", None)
            participants_data.append(row_dict)
        return participants_data

    @classmethod
    def export_to_excel(cls, file_path: str) -> bool:
        """
        Exporte l'ensemble des données d'adhérents de la saison active SQLite vers un fichier Excel.
        """
        cls.setup_database()
        data = cls.load_direct_data(season_filter="2026-2027") # Filtrer sur la saison active !

        excel_rows = []
        for row in data:
            excel_row = {}
            # Reconstituer toutes les colonnes d'origine de CORRECTIVE_MAP
            for excel_col, cache_key in CORRECTIVE_MAP.items():
                excel_row[excel_col] = row.get(cache_key, "")

            # Ajouter les colonnes supplémentaires indispensables
            for col_key in EXTRA_COLUMNS.keys():
                excel_row[col_key] = row.get(col_key, "")

            excel_rows.append(excel_row)

        try:
            df = pd.DataFrame(excel_rows)
            # S'assurer que le dossier parent existe
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            df.to_excel(file_path, index=False)
            print(f"💾 [SQLITE] Base de données exportée avec succès vers Excel : {file_path}")
            return True
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de l'exportation de la base de données vers Excel : {e}")
            return False

    @classmethod
    def upsert_members(cls, members: list, season_name: str = "2026-2027") -> int:
        """Insère ou met à jour un lot d'adhérents dans SQLite (compatible multi-saisons)."""
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()

        # Obtenir l'ID de la saison choisie
        cursor.execute("SELECT id FROM seasons WHERE name = ?", (season_name,))
        row_s = cursor.fetchone()
        if not row_s:
            cursor.execute("INSERT INTO seasons (name, is_active) VALUES (?, 0)", (season_name,))
            season_id = cursor.lastrowid
        else:
            season_id = row_s["id"]

        inserted_count = 0
        try:
            # Phase 3 — Écriture miroir dans le schéma cible v2 (même transaction que le
            # flux legacy : toute erreur annule les deux). Écrit enfin les payeurs
            # (payer_*) absents de l'ancien flux et les options dans purchase_options.
            v2_stats = schema_v2.sync_members_to_v2(cursor, members, season_name)
            print(f"🔄 [SQLITE] Miroir v2 : {v2_stats}")

            for m in members:
                # Étape 1 : Rapprochement ou insertion dans la table adherents par Nom et Prénom
                last_name_raw = str(m.get("user_lastName", "")).strip()
                first_name_raw = str(m.get("user_firstName", "")).strip()

                cursor.execute("""
                    SELECT id FROM adherents 
                    WHERE TRIM(UPPER(user_lastName)) = ? AND TRIM(LOWER(user_firstName)) = ?
                """, (last_name_raw.upper(), first_name_raw.lower()))

                exist_row = cursor.fetchone()
                if exist_row:
                    adherent_id = exist_row["id"]
                    # Mettre à jour les informations personnelles de l'adhérent
                    cursor.execute("""
                        UPDATE adherents
                        SET "champ_Téléphone " = ?,
                            "champ_Adresse mail pour la réception des informations du club" = ?,
                            "champ_Deuxième adresse mail pour la réception des informations du club" = ?,
                            "champ_Adresse : numéro et nom de rue" = ?,
                            "champ_Code postal" = ?,
                            "champ_Ville" = ?,
                            "champ_Pays" = ?,
                            "champ_Date de naissance de l'adhérent" = ?,
                            "champ_Sexe" = ?,
                            "champ_Nationalité" = ?,
                            "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule" = ?,
                            "champ_Personne à prévenir en cas d'urgence - Téléphone" = ?,
                            "champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)" = ?,
                            "champ_Parent 2 - Numéro de téléphone portable" = ?,
                            "champ_Numéro de Licence FFME (6 chiffres)" = COALESCE(NULLIF(?, ''), "champ_Numéro de Licence FFME (6 chiffres)")
                        WHERE id = ?
                    """, (
                        m.get("champ_Téléphone ", ""),
                        m.get("champ_Adresse mail pour la réception des informations du club", ""),
                        m.get("champ_Deuxième adresse mail pour la réception des informations du club", ""),
                        m.get("champ_Adresse : numéro et nom de rue", ""),
                        m.get("champ_Code postal", ""),
                        m.get("champ_Ville", ""),
                        m.get("champ_Pays", ""),
                        m.get("champ_Date de naissance de l'adhérent", ""),
                        m.get("champ_Sexe", ""),
                        m.get("champ_Nationalité", ""),
                        m.get("champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule", ""),
                        m.get("champ_Personne à prévenir en cas d'urgence - Téléphone", ""),
                        m.get("champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)", ""),
                        m.get("champ_Parent 2 - Numéro de téléphone portable", ""),
                        m.get("champ_Numéro de Licence FFME (6 chiffres)", ""),
                        adherent_id
                    ))
                else:
                    # Insérer un nouvel adhérent dans la table
                    cursor.execute("""
                        INSERT INTO adherents (
                            user_lastName, user_firstName, "champ_Téléphone ",
                            "champ_Adresse mail pour la réception des informations du club",
                            "champ_Deuxième adresse mail pour la réception des informations du club",
                            "champ_Adresse : numéro et nom de rue", "champ_Code postal", "champ_Ville", "champ_Pays",
                            "champ_Date de naissance de l'adhérent", "champ_Sexe", "champ_Nationalité",
                            "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule",
                            "champ_Personne à prévenir en cas d'urgence - Téléphone",
                            "champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)",
                            "champ_Parent 2 - Numéro de téléphone portable",
                            "champ_Numéro de Licence FFME (6 chiffres)",
                            badge_rouge, autonomie_bloc, raw_passports, raw_diplomas
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Non', 'Non', '', '')
                    """, (
                        last_name_raw, first_name_raw,
                        m.get("champ_Téléphone ", ""),
                        m.get("champ_Adresse mail pour la réception des informations du club", ""),
                        m.get("champ_Deuxième adresse mail pour la réception des informations du club", ""),
                        m.get("champ_Adresse : numéro et nom de rue", ""),
                        m.get("champ_Code postal", ""),
                        m.get("champ_Ville", ""),
                        m.get("champ_Pays", ""),
                        m.get("champ_Date de naissance de l'adhérent", ""),
                        m.get("champ_Sexe", ""),
                        m.get("champ_Nationalité", ""),
                        m.get("champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule", ""),
                        m.get("champ_Personne à prévenir en cas d'urgence - Téléphone", ""),
                        m.get("champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)", ""),
                        m.get("champ_Parent 2 - Numéro de téléphone portable", ""),
                        m.get("champ_Numéro de Licence FFME (6 chiffres)", "")
                    ))
                    adherent_id = cursor.lastrowid

                # Étape 2 : Insérer ou remplacer le lien de saison dans adherents_seasons (par ordre de priorité)
                # Traitement de l'amount (REAL/Float)
                amt = m.get("amount", 0.0)
                try:
                    amt_val = float(amt) if amt else 0.0
                except ValueError:
                    amt_val = 0.0

                new_status = str(m.get("status", "Validé")).strip()
                
                # Vérifier s'il y a déjà une inscription pour cette saison
                cursor.execute("""
                    SELECT order_ref, status, tarif_name, amount FROM adherents_seasons 
                    WHERE adherent_id = ? AND season_id = ?
                """, (adherent_id, season_id))
                exist_reg = cursor.fetchone()
                
                should_write = True
                if exist_reg:
                    exist_status = str(exist_reg["status"] or "").strip().lower()
                    new_status_lower = new_status.lower()
                    
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
                    
                    def get_score(status, tarif, val_amt):
                        status_key = str(status or "").strip().lower()
                        prio = status_priorities.get(status_key, 0)
                        tarif_key = str(tarif or "").strip().lower()
                        if "attente" in tarif_key or val_amt == 0.0:
                            prio -= 20
                        return prio

                    # Récupérer l'ancien montant existant pour un score précis
                    exist_tarif = str(exist_reg["tarif_name"] or "").strip()
                    exist_amt = float(exist_reg["amount"]) if exist_reg["amount"] else 0.0

                    exist_prio = get_score(exist_status, exist_tarif, exist_amt)
                    new_prio = get_score(new_status_lower, m.get("tarif_name", ""), amt_val)
                    
                    # Si l'existant est plus prioritaire (ex: Processed réel vs Validé liste d'attente), on ne l'écrase pas
                    if exist_prio > new_prio:
                        should_write = False
                        print(f"🛡️ [SYNC] Inscription existante plus active conservée pour l'ID {adherent_id} (Saison {season_id}) : "
                              f"Existant: {exist_reg['order_ref']} ({exist_reg['status']} / {exist_tarif}) - "
                              f"Nouveau ignoré: {m.get('order_ref')} ({new_status} / {m.get('tarif_name')})")
                
                if should_write:
                    cursor.execute("""
                        INSERT OR REPLACE INTO adherents_seasons (
                            adherent_id, season_id, order_ref, order_date, tarif_name, amount, status, is_modified, commentaires_correctif, email_sent_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        adherent_id,
                        season_id,
                        m.get("order_ref", ""),
                        m.get("order_date", ""),
                        m.get("tarif_name", ""),
                        amt_val,
                        new_status,
                        m.get("is_modified", "Non"),
                        m.get("commentaires_correctif", ""),
                        m.get("email_sent_date", None)
                    ))
                    inserted_count += 1

            conn.commit()
            print(f"💾 [SQLITE] Synchro réussie : {inserted_count} adhésions enregistrées/mises à jour pour la saison {season_name}.")
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de l'upsert des adhérents multi-saisons : {e}")
            conn.rollback()
        finally:
            conn.close()
        return inserted_count

    @classmethod
    def update_member_in_db(cls, original_order_ref: str, original_last_name: str, original_first_name: str, updated_fields: dict, comment_text: str):
        """
        Met à jour de manière chirurgicale un adhérent dans la base SQLite (compatible multi-saisons).
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()

        # 1. Trouver l'ID de l'adhérent lié à cette référence de commande en gérant les familles en Python (pour contourner UPPER/LOWER d'accent sous SQLite)
        cursor.execute("""
            SELECT las.adherent_id, a.user_lastName, a.user_firstName
            FROM adherents_seasons las
            JOIN adherents a ON las.adherent_id = a.id
            WHERE las.order_ref = ?
        """, (original_order_ref.strip(),))
        rows = cursor.fetchall()
        
        adherent_id = None
        if rows:
            from domain.utils import normalize_name
            target_last = normalize_name(original_last_name)
            target_first = normalize_name(original_first_name)
            for r in rows:
                r_last = normalize_name(r["user_lastName"])
                r_first = normalize_name(r["user_firstName"])
                if r_last == target_last and r_first == target_first:
                    adherent_id = r["adherent_id"]
                    break
                    
            if not adherent_id:
                # Si aucun ne correspond exactement par nom/prénom normalisé (ex: faute de frappe), on prend le premier de la famille
                adherent_id = rows[0]["adherent_id"]
        else:
            # Fallback s'il s'agit d'une ancienne base sans liaison : recherche en Python sur toute la base
            cursor.execute("SELECT id, user_lastName, user_firstName FROM adherents")
            all_adh = cursor.fetchall()
            from domain.utils import normalize_name
            target_last = normalize_name(original_last_name)
            target_first = normalize_name(original_first_name)
            for a in all_adh:
                a_last = normalize_name(a["user_lastName"])
                a_first = normalize_name(a["user_firstName"])
                if a_last == target_last and a_first == target_first:
                    adherent_id = a["id"]
                    break
            
            if not adherent_id:
                conn.close()
                return False, f"Aucun adhérent correspondant trouvé pour {original_last_name} {original_first_name}."

        # 2. Dictionnaire liant les clés de l'IHM aux colonnes SQLite de la table 'adherents' (Données personnelles)
        personal_fields = {
            "user_last_name": "user_lastName",
            "user_first_name": "user_firstName",
            "birth_date": "champ_Date de naissance de l'adhérent",
            "primary_email": "champ_Adresse mail pour la réception des informations du club",
            "secondary_email": "champ_Deuxième adresse mail pour la réception des informations du club",
            "phone": "champ_Téléphone ",
            "city": "champ_Ville",
            "emergency_contact_name_1": "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule",
            "emergency_contact_phone_1": "champ_Personne à prévenir en cas d'urgence - Téléphone",
            "licence_ffme": "champ_Numéro de Licence FFME (6 chiffres)",
            "opt_assurance_base": "opt_Assurance Base",
            "opt_assurance_base_plus": "opt_Assurance Base +",
            "opt_assurance_base_plus_plus": "opt_Assurance Base ++",
            "opt_assurance_ski": "opt_Assurance Option ski de piste",
            "opt_assurance_vtt": "opt_Assurance Option VTT",
            "opt_assurance_trail": "opt_Assurance Option Trail",
            "photo_auth": "champ_En cas de prise de vue (Photo ou vidéo), j'autorise à ce que l'image de mon enfant (cours enfants) ou la mienne (créneau adultes) puisse être utilisée par l'Amicale Laïque de Jonage à des fins non commerciales",
            "health_q_auth": "champ_Je m'engage à compléter mon questionnaire de santé ou téléverser mon certificat médical sur le site  https://www.myffme.fr à réception du mail de confirmation d'adhésion, pour mon enfant (cours enfants) ou moi-même (créneau adultes)",
            "badge_rouge": "badge_rouge",
            "autonomie_bloc": "autonomie_bloc",
            "raw_passports": "raw_passports",
            "raw_diplomas": "raw_diplomas",
            "parental_auth_autonomous": "parental_auth_autonomous",
            "parental_auth_family": "parental_auth_family"
        }

        # 3. Mettre à jour la table 'adherents' (Informations personnelles)
        personal_sets = []
        personal_params = []
        for field, col_name in personal_fields.items():
            if field in updated_fields:
                personal_sets.append(f'"{col_name}" = ?')
                personal_params.append(updated_fields[field])
                
        if personal_sets:
            personal_sql = f'UPDATE adherents SET {", ".join(personal_sets)} WHERE id = ?'
            personal_params.append(adherent_id)
            try:
                cursor.execute(personal_sql, personal_params)
            except Exception as e:
                print(f"❌ [SQLITE] Erreur lors de la mise à jour des données personnelles : {e}")
                conn.rollback()
                conn.close()
                return False, str(e)

        # 4. Mettre à jour la table 'adherents_seasons' (Données spécifiques de saison)
        season_sets = []
        season_params = []
        
        # Statut de la commande
        if "status" in updated_fields:
            season_sets.append('"status" = ?')
            season_params.append(updated_fields["status"])
            
        # Indicateurs d'édition et commentaires
        season_sets.append('"is_modified" = ?')
        season_params.append("Oui")
        season_sets.append('"commentaires_correctif" = ?')
        season_params.append(comment_text)

        # Clause WHERE pour mettre à jour la liaison exacte
        season_sets_sql = ", ".join(season_sets)
        season_sql = f'UPDATE adherents_seasons SET {season_sets_sql} WHERE adherent_id = ? AND order_ref = ?'
        season_params.extend([adherent_id, original_order_ref.strip()])

        try:
            cursor.execute(season_sql, season_params)
            # Phase 3 — miroir des correctifs manuels dans le schéma v2 (même transaction)
            schema_v2.mirror_member_update(cursor, adherent_id, original_order_ref,
                                           original_last_name, original_first_name,
                                           updated_fields, comment_text)
            conn.commit()
            print(f"📝 [SQLITE] Adhérent {original_last_name} {original_first_name} mis à jour avec succès (multi-saisons).")
            return True, ""
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de l'adresse de liaison de la saison de l'adhérent : {e}")
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    @classmethod
    def update_email_sent_date(cls, order_ref: str, last_name: str, first_name: str, date_str: str) -> bool:
        """Met à jour de manière chirurgicale la date d'envoi de l'e-mail d'un adhérent (dans sa liaison de saison)."""
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE adherents_seasons
                SET email_sent_date = ?
                WHERE order_ref = ? AND adherent_id = (
                    SELECT id FROM adherents 
                    WHERE TRIM(UPPER(user_lastName)) = ? AND TRIM(LOWER(user_firstName)) = ?
                )
            """, (date_str, order_ref.strip(), last_name.strip().upper(), first_name.strip().lower()))
            rows_affected = cursor.rowcount
            if rows_affected == 0:
                # Fallback si le nom a été modifié localement ou ne matche pas
                cursor.execute("""
                    UPDATE adherents_seasons
                    SET email_sent_date = ?
                    WHERE order_ref = ?
                """, (date_str, order_ref.strip()))
                rows_affected = cursor.rowcount

            # Phase 3 — miroir v2 sur les achats de la commande
            schema_v2.mirror_email_sent_date(cursor, order_ref, date_str)

            conn.commit()
            if rows_affected > 0:
                print(f"📝 [SQLITE] Date d'envoi d'e-mail enregistrée dans la liaison de saison pour la commande {order_ref} : {date_str}")
                return True
            else:
                print(f"⚠️ [SQLITE] Aucun enregistrement de saison trouvé pour la commande {order_ref}")
                return False
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la mise à jour de la date d'envoi d'e-mail : {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    @classmethod
    def merge_ffme_licensees(cls, excel_path: str) -> dict:
        """
        Importe la liste des licenciés FFME depuis un fichier Excel et fusionne avec les adhérents SQLite.
        """
        cls.create_db_backup()
        import pandas as pd
        from domain.utils import normalize_name
        
        stats = {
            "total_processed": 0,
            "matched_by_licence": 0,
            "matched_by_name": 0,
            "not_found": 0,
            "errors": []
        }
        
        if not os.path.exists(excel_path):
            stats["errors"].append(f"Fichier introuvable : {excel_path}")
            return stats
            
        try:
            df = pd.read_excel(excel_path)
        except Exception as e:
            stats["errors"].append(f"Erreur de lecture Excel : {e}")
            return stats
            
        required_cols = ["Nom", "Prénom", "N° de licence"]
        for col in required_cols:
            if col not in df.columns:
                stats["errors"].append(f"Colonne requise manquante dans le fichier Excel : {col}")
                return stats
                
        # Charger tous les adhérents existants pour la comparaison par nom
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        
        try:
            # Charger les adhérents
            cursor.execute("SELECT id, user_lastName, user_firstName, status, \"champ_Numéro de Licence FFME (6 chiffres)\" FROM adherents")
            adherents = [dict(row) for row in cursor.fetchall()]
            
            # Préparer les adhérents indexés par licence et par nom normalisé pour un traitement rapide
            adherents_by_licence = {}
            adherents_by_name = {}
            
            for adj in adherents:
                lic = str(adj["champ_Numéro de Licence FFME (6 chiffres)"] or "").strip()
                if lic:
                    adherents_by_licence[lic] = adj
                
                # Indexer par nom et prénom normalisés
                norm_last = normalize_name(adj["user_lastName"])
                norm_first = normalize_name(adj["user_firstName"])
                if norm_last and norm_first:
                    adherents_by_name[(norm_last, norm_first)] = adj
            
            updates = [] # Liste de tuples (status, licence, id)
            
            for idx, row in df.iterrows():
                stats["total_processed"] += 1
                
                raw_lic = row["N° de licence"]
                if pd.isna(raw_lic):
                    lic_str = ""
                else:
                    # Traiter si float (ex: 123456.0)
                    if isinstance(raw_lic, float):
                        lic_str = str(int(raw_lic)).strip()
                    else:
                        lic_str = str(raw_lic).strip()
                        
                nom = str(row["Nom"] or "").strip()
                prenom = str(row["Prénom"] or "").strip()
                
                matched_adj = None
                match_type = None
                
                # 1. Essayer de faire correspondre par numéro de licence
                if lic_str and lic_str in adherents_by_licence:
                    matched_adj = adherents_by_licence[lic_str]
                    match_type = "licence"
                
                # 2. Sinon, essayer de faire correspondre par Nom, Prénom
                if not matched_adj and nom and prenom:
                    norm_nom = normalize_name(nom)
                    norm_prenom = normalize_name(prenom)
                    if (norm_nom, norm_prenom) in adherents_by_name:
                        matched_adj = adherents_by_name[(norm_nom, norm_prenom)]
                        match_type = "name"
                
                if matched_adj:
                    # Enregistrer la mise à jour
                    target_id = matched_adj["id"]
                    # On garde la licence existante ou on prend la nouvelle du fichier FFME
                    final_lic = lic_str if lic_str else matched_adj["champ_Numéro de Licence FFME (6 chiffres)"]
                    
                    # Extraire et nettoyer les passeports et diplômes
                    passports_str = str(row.get("Passeports") or "").strip()
                    if passports_str.lower() in ("nan", "none", ""):
                        passports_str = ""
                    
                    diplomas_str = str(row.get("Diplômes") or "").strip()
                    if diplomas_str.lower() in ("nan", "none", ""):
                        diplomas_str = ""
                    
                    updates.append(("Processed", final_lic, passports_str, diplomas_str, target_id))
                    
                    if match_type == "licence":
                        stats["matched_by_licence"] += 1
                    else:
                        stats["matched_by_name"] += 1
                else:
                    stats["not_found"] += 1
            
            # Appliquer les mises à jour en base de données
            if updates:
                # 1. Mettre à jour l'identité (licence, passeports, diplômes) dans la table adherents
                cursor.executemany("""
                    UPDATE adherents
                    SET "champ_Numéro de Licence FFME (6 chiffres)" = ?,
                        raw_passports = ?,
                        raw_diplomas = ?
                    WHERE id = ?
                """, [(u[1], u[2], u[3], u[4]) for u in updates])
                
                # 2. Mettre à jour le statut dans la table adherents_seasons (saison active 2026-2027) (Nouveau !)
                cursor.executemany("""
                    UPDATE adherents_seasons
                    SET status = ?
                    WHERE adherent_id = ? AND season_id = (SELECT id FROM seasons WHERE name = '2026-2027')
                """, [(u[0], u[4]) for u in updates])
                
                # 3. Mettre à jour le statut dans la table adherents pour la rétrocompatibilité (Nouveau !)
                cursor.executemany("""
                    UPDATE adherents
                    SET status = ?
                    WHERE id = ?
                """, [(u[0], u[4]) for u in updates])

                # Phase 3 — miroir v2 : identité vers users, statut vers purchases (saison active)
                schema_v2.ensure_v2_schema(cursor)
                cursor.executemany("""
                    UPDATE users
                    SET licence_ffme = ?, raw_passports = ?, raw_diplomas = ?
                    WHERE legacy_adherent_id = ?
                """, [(u[1], u[2], u[3], u[4]) for u in updates])
                cursor.executemany("""
                    UPDATE purchases
                    SET status = ?, status_normalized = ?
                    WHERE legacy_adherent_id = ? AND legacy_season_id = (SELECT id FROM seasons WHERE name = '2026-2027')
                """, [(u[0], schema_v2.normalize_status(u[0]), u[4]) for u in updates])

                conn.commit()
                
        except Exception as e:
            conn.rollback()
            stats["errors"].append(f"Erreur lors de la fusion en BDD : {e}")
        finally:
            conn.close()
            
        return stats

    @classmethod
    def merge_autonomes_data(cls, excel_path: str) -> dict:
        """
        Importe la liste d'autonomie (Autonomes_*.xlsx) depuis un fichier Excel et fusionne avec les adhérents SQLite.
        """
        cls.create_db_backup()
        import pandas as pd
        
        stats = {
            "total_processed": 0,
            "matched": 0,
            "not_found": 0,
            "errors": []
        }
        
        if not os.path.exists(excel_path):
            stats["errors"].append(f"Fichier introuvable : {excel_path}")
            return stats
            
        try:
            # Lire le fichier excel, en sautant la ligne de titre (header=1)
            df = pd.read_excel(excel_path, header=1)
            df = df.fillna("")
        except Exception as e:
            stats["errors"].append(f"Erreur de lecture Excel : {e}")
            return stats
            
        required_cols = ["N° de licence", "Badge rouge diff", "Autonomie Bloc"]
        for col in required_cols:
            if col not in df.columns:
                stats["errors"].append(f"Colonne requise manquante dans le fichier Excel : {col}")
                return stats
                
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        
        try:
            # Charger les adhérents existants avec leur numéro de licence, nom, prénom et leurs passeports actuels (Nouveau !)
            cursor.execute("SELECT id, user_lastName, user_firstName, \"champ_Numéro de Licence FFME (6 chiffres)\", raw_passports FROM adherents")
            adherents = [dict(row) for row in cursor.fetchall()]
            
            adherents_by_licence = {}
            for adj in adherents:
                lic = str(adj["champ_Numéro de Licence FFME (6 chiffres)"] or "").strip()
                # Correction du bug de traînées de ".0" dans la base de données (Nouveau !)
                if lic.endswith(".0"):
                    lic = lic[:-2]
                clean_lic = "".join(c for c in lic if c.isdigit())
                if clean_lic:
                    adherents_by_licence[clean_lic] = adj
                    
            # Charger un dictionnaire par Nom/Prénom pour le fallback sémantique (Nouveau !)
            from domain.utils import normalize_name
            adherents_by_name = {}
            for adj in adherents:
                nom = normalize_name(adj.get("user_lastName", ""))
                prenom = normalize_name(adj.get("user_firstName", ""))
                if nom and prenom:
                    adherents_by_name[(nom, prenom)] = adj
            
            updates = [] # Liste de tuples (badge_rouge, autonomie_bloc, raw_passports, id)
            file_badge_rouge_count = 0
            
            for idx, row in df.iterrows():
                stats["total_processed"] += 1
                
                raw_lic = str(row.get("N° de licence", "")).strip()
                if raw_lic.endswith(".0"):
                    raw_lic = raw_lic[:-2]
                lic_num = "".join(c for c in raw_lic if c.isdigit())
                
                badge_rouge_raw = str(row.get("Badge rouge diff", "")).strip().upper()
                autonomie_bloc_raw = str(row.get("Autonomie Bloc", "")).strip().upper()
                
                if badge_rouge_raw == "X":
                    file_badge_rouge_count += 1
                
                badge_rouge = "Oui" if badge_rouge_raw == "X" else ("Non" if not badge_rouge_raw else row.get("Badge rouge diff", ""))
                autonomie_bloc = "Oui" if autonomie_bloc_raw == "X" else ("Non" if not autonomie_bloc_raw else row.get("Autonomie Bloc", ""))
                
                # Récupérer l'indicateur Passeport Orange s'il est noté X dans le fichier d'autonomie (votre demande !)
                has_orange_raw = str(row.get("Passeport Orange", "")).strip().upper()
                orange_passport_val = "Escalade - Passeport orange" if has_orange_raw == "X" else ""
                
                matched_adj = None
                
                # Étape 1 : Rapprochement par numéro de licence (CORRIGÉ !)
                if lic_num and lic_num in adherents_by_licence:
                    matched_adj = adherents_by_licence[lic_num]
                    
                # Étape 2 : Rapprochement sémantique par Nom et Prénom (Nouveau !)
                if not matched_adj:
                    nom_raw = str(row.get("NOM", "")).strip()
                    prenom_raw = str(row.get("Prénom", "")).strip()
                    if nom_raw and prenom_raw:
                        norm_nom = normalize_name(nom_raw)
                        norm_prenom = normalize_name(prenom_raw)
                        if (norm_nom, norm_prenom) in adherents_by_name:
                            matched_adj = adherents_by_name[(norm_nom, norm_prenom)]
                
                if matched_adj:
                    target_id = matched_adj["id"]
                    existing_passports = str(matched_adj.get("raw_passports") or "").strip()
                    
                    # Fusionner intelligemment avec le passeport Orange si noté X
                    if orange_passport_val:
                        if "orange" not in existing_passports.lower():
                            if existing_passports:
                                new_passports = f"{existing_passports}, {orange_passport_val}"
                            else:
                                new_passports = orange_passport_val
                        else:
                            new_passports = existing_passports
                    else:
                        new_passports = existing_passports
                        
                    updates.append((badge_rouge, autonomie_bloc, new_passports, target_id))
                    stats["matched"] += 1
                else:
                    stats["not_found"] += 1
            
            stats["file_badge_rouge_count"] = file_badge_rouge_count
            
            # Appliquer les mises à jour en base de données
            if updates:
                cursor.executemany("""
                    UPDATE adherents
                    SET badge_rouge = ?,
                        autonomie_bloc = ?,
                        raw_passports = ?
                    WHERE id = ?
                """, updates)

                # Phase 3 — miroir v2 : flags club vers users
                schema_v2.ensure_v2_schema(cursor)
                cursor.executemany("""
                    UPDATE users
                    SET badge_rouge = ?, autonomie_bloc = ?, raw_passports = ?
                    WHERE legacy_adherent_id = ?
                """, updates)

                conn.commit()
                
            # Calculer les statistiques après mise à jour
            cursor.execute("SELECT COUNT(*) as cnt FROM adherents WHERE badge_rouge = 'Oui'")
            stats["db_total_badge_rouge"] = cursor.fetchone()["cnt"]
            
            cursor.execute("SELECT COUNT(*) as cnt FROM adherents WHERE autonomie_bloc = 'Oui' AND (badge_rouge IS NULL OR badge_rouge != 'Oui')")
            stats["db_autonomes_without_badge_rouge"] = cursor.fetchone()["cnt"]
                
        except Exception as e:
            conn.rollback()
            stats["errors"].append(f"Erreur lors de la fusion en BDD : {e}")
        finally:
            conn.close()
            
        return stats

    @classmethod
    def import_old_season_ffme(cls, excel_path: str, season_name: str = "2025-2026") -> dict:
        """
        Importe les licenciés d'une ancienne saison depuis un export FFME (.xlsx) et les rattache à la saison spécifiée.
        Crée les adhérents inexistants.
        """
        cls.create_db_backup()
        import pandas as pd
        from domain.utils import normalize_name
        
        stats = {
            "total_processed": 0,
            "created": 0,
            "linked": 0,
            "errors": []
        }
        
        if not os.path.exists(excel_path):
            stats["errors"].append(f"Fichier introuvable : {excel_path}")
            return stats
            
        # Contournement de verrouillage de fichier par copie temporaire (Nouveau !)
        import shutil
        temp_path = os.path.join(ROOT_DIR, "archive", f"temp_import_{datetime.datetime.now().strftime('%H%M%S')}.xlsx")
        try:
            shutil.copy2(excel_path, temp_path)
            df = pd.read_excel(temp_path)
            df = df.fillna("")
            try:
                os.remove(temp_path)
            except Exception:
                pass
        except Exception as e:
            print(f"❌ [SQLITE] Erreur de lecture du fichier d'importation (fichier probablement ouvert ou verrouillé par Excel) : {e}")
            stats["errors"].append(f"Erreur de lecture du fichier Excel : {e}")
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return stats
            
        required_cols = ["Nom", "Prénom"]
        for col in required_cols:
            if col not in df.columns:
                stats["errors"].append(f"Colonne requise manquante dans le fichier Excel : {col}")
                return stats
                
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        
        try:
            # 1. Obtenir l'ID de la saison cible
            cursor.execute("SELECT id FROM seasons WHERE name = ?", (season_name,))
            row_s = cursor.fetchone()
            if not row_s:
                cursor.execute("INSERT INTO seasons (name, is_active) VALUES (?, 0)", (season_name,))
                season_id = cursor.lastrowid
            else:
                season_id = row_s["id"]
                
            # 2. Charger les adhérents existants pour le rapprochement
            cursor.execute("SELECT id, user_lastName, user_firstName, \"champ_Numéro de Licence FFME (6 chiffres)\" FROM adherents")
            adherents = [dict(row) for row in cursor.fetchall()]
            
            adherents_by_licence = {}
            adherents_by_name = {}
            for adj in adherents:
                lic = str(adj["champ_Numéro de Licence FFME (6 chiffres)"] or "").strip()
                if lic.endswith(".0"):
                    lic = lic[:-2]
                clean_lic = "".join(c for c in lic if c.isdigit())
                if clean_lic:
                    adherents_by_licence[clean_lic] = adj
                    
                nom = normalize_name(adj.get("user_lastName", ""))
                prenom = normalize_name(adj.get("user_firstName", ""))
                if nom and prenom:
                    adherents_by_name[(nom, prenom)] = adj
                    
            # 3. Traiter chaque ligne du fichier FFME
            for idx, row in df.iterrows():
                stats["total_processed"] += 1
                
                nom = str(row.get("Nom", "")).strip()
                prenom = str(row.get("Prénom", "")).strip()
                if not nom or not prenom:
                    continue
                    
                raw_lic = str(row.get("N° de licence", "")).strip()
                if raw_lic.endswith(".0"):
                    raw_lic = raw_lic[:-2]
                lic_num = "".join(c for c in raw_lic if c.isdigit())
                
                matched_adj = None
                
                # Rapprochement 1 : par licence
                if lic_num and lic_num in adherents_by_licence:
                    matched_adj = adherents_by_licence[lic_num]
                # Rapprochement 2 : par nom / prénom
                if not matched_adj:
                    norm_nom = normalize_name(nom)
                    norm_prenom = normalize_name(prenom)
                    if (norm_nom, norm_prenom) in adherents_by_name:
                        matched_adj = adherents_by_name[(norm_nom, norm_prenom)]
                        
                # Détecter le passeport Orange s'il est mentionné dans la colonne 'Passeports' de l'Excel (votre demande !)
                passports_col = str(row.get("Passeports", "")).strip()
                has_orange_in_excel = "orange" in passports_col.lower()
                
                if matched_adj:
                    adherent_id = matched_adj["id"]
                    # Optionnellement mettre à jour le numéro de licence s'il manquait
                    if lic_num and not matched_adj["champ_Numéro de Licence FFME (6 chiffres)"]:
                        cursor.execute("""
                            UPDATE adherents SET "champ_Numéro de Licence FFME (6 chiffres)" = ? WHERE id = ?
                        """, (raw_lic, adherent_id))
                        
                    # Mettre à jour le passeport Orange s'il est présent dans l'Excel de l'ancienne saison (votre demande !)
                    if has_orange_in_excel:
                        existing_passports = str(matched_adj.get("raw_passports") or "").strip()
                        if "orange" not in existing_passports.lower():
                            new_passports = f"{existing_passports}, Escalade - Passeport orange" if existing_passports else "Escalade - Passeport orange"
                            cursor.execute("""
                                UPDATE adherents SET raw_passports = ? WHERE id = ?
                            """, (new_passports, adherent_id))
                else:
                    # Créer un nouvel adhérent avec les informations du fichier FFME !
                    sexe = str(row.get("Sexe", "")).strip()
                    birth_date_raw = str(row.get("Date de naissance", "")).strip()
                    if birth_date_raw.endswith(" 00:00:00"):
                        birth_date_raw = birth_date_raw[:-9]
                        
                    address = str(row.get("Adresse", "")).strip()
                    zip_code = str(row.get("Code postal", "")).strip()
                    if zip_code.endswith(".0"):
                        zip_code = zip_code[:-2]
                    city = str(row.get("Ville", "")).strip()
                    phone = str(row.get("Téléphone", "")).strip()
                    email = str(row.get("Email", "")).strip()
                    
                    passports = str(row.get("Passeports", "")).strip()
                    if passports.lower() in ("nan", "none", "aucune", ""):
                        passports = ""
                    diplomas = str(row.get("Diplômes", "")).strip()
                    if diplomas.lower() in ("nan", "none", "aucune", ""):
                        diplomas = ""
                        
                    # Si passeport Orange est dans l'Excel mais pas dans passports, on l'ajoute (votre demande !)
                    if has_orange_in_excel and "orange" not in passports.lower():
                        passports = f"{passports}, Escalade - Passeport orange" if passports else "Escalade - Passeport orange"
                        
                    cursor.execute("""
                        INSERT INTO adherents (
                            user_lastName, user_firstName, "champ_Sexe", "champ_Date de naissance de l'adhérent",
                            "champ_Adresse : numéro et nom de rue", "champ_Code postal", "champ_Ville",
                            "champ_Téléphone ", "champ_Adresse mail pour la réception des informations du club",
                            "champ_Numéro de Licence FFME (6 chiffres)", raw_passports, raw_diplomas,
                            badge_rouge, autonomie_bloc, is_modified
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Non', 'Non', 'Non')
                    """, (
                        nom, prenom, sexe, birth_date_raw,
                        address, zip_code, city,
                        phone, email,
                        raw_lic, passports, diplomas
                    ))
                    adherent_id = cursor.lastrowid
                    stats["created"] += 1
                    
                # Établir la liaison adherents <-> adherents_seasons (avec le Type de licence de l'Excel !) (votre demande !)
                placeholder_ref = f"IMPORT-FFME-{season_name.replace('-', '')}-{adherent_id:04d}"
                tarif_name_val = str(row.get("Type de licence", "")).strip()
                if not_found := (not tarif_name_val or tarif_name_val.lower() == "nan"):
                    tarif_name_val = f"Import Historique (Saison {season_name})"
                
                cursor.execute("""
                    INSERT OR REPLACE INTO adherents_seasons (
                        adherent_id, season_id, order_ref, order_date, tarif_name, amount, status, is_modified, commentaires_correctif, email_sent_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """, (
                    adherent_id,
                    season_id,
                    placeholder_ref,
                    f"{season_name.split('-')[0]}-09-01",
                    tarif_name_val,
                    0.0,
                    "Validé",
                    "Non",
                    f"Importé automatiquement depuis le fichier FFME de la saison {season_name}"
                ))
                stats["linked"] += 1
                
            conn.commit()
            print(f"✅ [SQLITE] Import de la saison {season_name} terminé : {stats['created']} adhérents créés, {stats['linked']} liaisons établies.")
        except Exception as e:
            conn.rollback()
            stats["errors"].append(f"Erreur lors de l'importation de l'ancienne saison en base : {e}")
            print(f"❌ [SQLITE] Erreur lors de l'import de la saison historique : {e}")
        finally:
            conn.close()
            
        return stats

    @classmethod
    def migrate_json_planning(cls):
        """Migre les données du fichier historique planning.json et tarif_mapping.json vers la table planning de SQLite."""
        # 1. Vérifier si la table planning est déjà peuplée pour éviter une migration inutile
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM planning")
            count = cursor.fetchone()["cnt"]
            if count > 0:
                return # Déjà peuplé
        except Exception:
            return
        finally:
            conn.close()

        json_path = os.path.join(ROOT_DIR, "planning.json")
        if not os.path.exists(json_path):
            # Essayer aussi dans CODE_ROOT
            json_path = os.path.join(CODE_ROOT, "planning.json")
            if not os.path.exists(json_path):
                return

        # Tenter de charger le tarif_mapping.json historique pour fusionner les tarifs HelloAsso
        tarif_mapping_path = os.path.join(ROOT_DIR, "tarif_mapping.json")
        if not os.path.exists(tarif_mapping_path):
            tarif_mapping_path = os.path.join(CODE_ROOT, "tarif_mapping.json")

        slot_to_tarifs = {}
        if os.path.exists(tarif_mapping_path):
            try:
                with open(tarif_mapping_path, "r", encoding="utf-8") as tmf:
                    tarif_mapping = json.load(tmf)
                for rate_name, slot_ids_str in tarif_mapping.items():
                    if slot_ids_str and str(slot_ids_str).strip():
                        ids = [idx.strip() for idx in str(slot_ids_str).split(";")]
                        for idx in ids:
                            if idx not in slot_to_tarifs:
                                slot_to_tarifs[idx] = []
                            if rate_name not in slot_to_tarifs[idx]:
                                slot_to_tarifs[idx].append(rate_name)
                print(f"📦 [SQLITE] {len(tarif_mapping)} correspondances chargées depuis tarif_mapping.json pour la migration.")
            except Exception as tme:
                print(f"⚠️ [SQLITE] Impossible de charger tarif_mapping.json pour la migration : {tme}")

        print(f"📦 [SQLITE] Migration du planning historique depuis {json_path}...")
        conn = None
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                return
                
            conn = cls.get_connection()
            cursor = conn.cursor()
            inserted = 0
            for item in data:
                slot_id = str(item.get("id", ""))
                enc_json = json.dumps(item.get("encadrants", []), ensure_ascii=False)
                
                # Récupérer les tarifs déjà configurés ou utiliser ceux de tarif_mapping.json en repli
                tarifs = item.get("helloasso_tarifs")
                if not tarifs:
                    tarifs = slot_to_tarifs.get(slot_id, [])
                tarifs_json = json.dumps(tarifs, ensure_ascii=False)

                cursor.execute("""
                    INSERT OR REPLACE INTO planning (id, groupe, type, categorie_age, whatsapp_link, jour, horaires, encadrants, helloasso_tarifs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.get("id"),
                    item.get("groupe"),
                    item.get("type", "cours"),
                    item.get("categorie_age", ""),
                    item.get("whatsapp_link", ""),
                    item.get("jour", "Lundi"),
                    item.get("horaires", ""),
                    enc_json,
                    tarifs_json
                ))
                inserted += 1
            conn.commit()
            print(f"✅ [SQLITE] Migration réussie de {inserted} créneaux de planning avec leurs correspondances de tarifs.")
            
            # Archiver les fichiers json historiques
            try:
                if os.path.exists(json_path):
                    os.rename(json_path, json_path + ".migrated")
                    print(f"📦 [SQLITE] Fichier planning.json archivé en .migrated")
                if os.path.exists(tarif_mapping_path):
                    os.rename(tarif_mapping_path, tarif_mapping_path + ".migrated")
                    print(f"📦 [SQLITE] Fichier tarif_mapping.json archivé en .migrated")
            except Exception as re_err:
                print(f"⚠️ [SQLITE] Impossible d'archiver les fichiers historiques JSON : {re_err}")
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la migration du fichier json planning : {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    @classmethod
    def load_planning_data(cls) -> list:
        """Charge l'ensemble du planning de créneaux depuis SQLite."""
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM planning ORDER BY id ASC")
            rows = cursor.fetchall()
            planning_list = []
            for row in rows:
                row_dict = dict(row)
                
                # Désérialiser les encadrants
                encadrants_raw = row_dict.get("encadrants", "[]")
                if encadrants_raw:
                    try:
                        encadrants = json.loads(encadrants_raw)
                    except Exception:
                        encadrants = []
                else:
                    encadrants = []
                row_dict["encadrants"] = encadrants
                
                # Désérialiser les tarifs HelloAsso mappés
                tarifs_raw = row_dict.get("helloasso_tarifs", "[]")
                if tarifs_raw:
                    try:
                        tarifs = json.loads(tarifs_raw)
                    except Exception:
                        tarifs = []
                else:
                    tarifs = []
                row_dict["helloasso_tarifs"] = tarifs
                
                planning_list.append(row_dict)

            # Debug logging
            debug_log_path = os.path.join(ROOT_DIR, "planning_sync_debug.log")
            try:
                with open(debug_log_path, "a", encoding="utf-8") as lf:
                    lf.write(f"[{datetime.datetime.now()}] --- CHARGEMENT DU PLANNING ---\n")
                    lf.write(f"  • CWD : {os.getcwd()}\n")
                    lf.write(f"  • Chemin de la BDD : {cls._db_path}\n")
                    lf.write(f"  • Nb créneaux chargés : {len(planning_list)}\n")
                    for s in planning_list:
                        lf.write(f"    - ID: {s.get('id')} | Groupe: {s.get('groupe')} | Jour: {s.get('jour')} | Horaires: {s.get('horaires')}\n")
                    lf.write("\n")
            except Exception as le:
                print(f"⚠️ Erreur d'écriture du log debug : {le}")

            return planning_list
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors du chargement du planning : {e}")
            return []
        finally:
            conn.close()

    @classmethod
    def save_planning_data(cls, planning_list: list):
        """Enregistre le planning complet en SQLite et l'exporte sur planning.json pour rétrocompatibilité."""
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM planning")
            for item in planning_list:
                enc_json = json.dumps(item.get("encadrants", []), ensure_ascii=False)
                tarifs_json = json.dumps(item.get("helloasso_tarifs", []), ensure_ascii=False)
                cursor.execute("""
                    INSERT OR REPLACE INTO planning (id, groupe, type, categorie_age, whatsapp_link, jour, horaires, encadrants, helloasso_tarifs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.get("id"),
                    item.get("groupe"),
                    item.get("type", "cours"),
                    item.get("categorie_age", ""),
                    item.get("whatsapp_link", ""),
                    item.get("jour", "Lundi"),
                    item.get("horaires", ""),
                    enc_json,
                    tarifs_json
                ))
            conn.commit()
            print("💾 [SQLITE] Planning enregistré avec succès dans SQLite.")
            
            # Debug logging
            debug_log_path = os.path.join(ROOT_DIR, "planning_sync_debug.log")
            try:
                with open(debug_log_path, "a", encoding="utf-8") as lf:
                    lf.write(f"[{datetime.datetime.now()}] --- ENREGISTREMENT DU PLANNING ---\n")
                    lf.write(f"  • CWD : {os.getcwd()}\n")
                    lf.write(f"  • Chemin de la BDD : {cls._db_path}\n")
                    lf.write(f"  • Nb créneaux reçus : {len(planning_list)}\n")
                    for s in planning_list:
                        lf.write(f"    - ID: {s.get('id')} | Groupe: {s.get('groupe')} | Jour: {s.get('jour')} | Horaires: {s.get('horaires')}\n")
                    lf.write("\n")
            except Exception as le:
                print(f"⚠️ Erreur d'écriture du log debug : {le}")

        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la sauvegarde du planning : {e}")
            conn.rollback()
            raise e
        finally:
            conn.close()

    @classmethod
    def get_email_templates(cls) -> list:
        """
        Récupère l'ensemble des templates d'emails enregistrés en BDD.
        Retourne une liste de dicts : [{"name": ..., "subject": ..., "body": ...}]
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT name, subject, body FROM email_templates ORDER BY name ASC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la récupération des templates d'emails : {e}")
            return []
        finally:
            conn.close()

    @classmethod
    def save_email_template(cls, name: str, subject: str, body: str) -> bool:
        """
        Enregistre ou met à jour un template d'email dans la BDD.
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO email_templates (name, subject, body)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET subject = excluded.subject, body = excluded.body
            """, (name.strip(), subject.strip(), body.strip()))
            conn.commit()
            return True
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de l'enregistrement du template d'email '{name}' : {e}")
            return False
        finally:
            conn.close()

    @classmethod
    def delete_email_template(cls, name: str) -> bool:
        """
        Supprime un template d'email de la BDD.
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM email_templates WHERE name = ?", (name.strip(),))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la suppression du template d'email '{name}' : {e}")
            return False
        finally:
            conn.close()
