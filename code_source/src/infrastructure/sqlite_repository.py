import os
import sqlite3
import datetime
import pandas as pd
import json
from paths import CODE_ROOT, ROOT_DIR
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

# Adresse d'expédition par défaut des e-mails de la Communication (choisissable/sauvegardable dans l'IHM)
DEFAULT_SENDER_EMAIL = "inscription@alj-escalade.fr"

# Nom d'affichage de l'expéditeur (visible dans la colonne « De » des messageries)
DEFAULT_SENDER_NAME = "Amicale Laïque Jonage - Inscriptions"

# Phase 2 - vue de compatibilite : definie dans infrastructure/schema_v2.py (COMPAT_VIEW_SQL)

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

        # Phase 5 — schéma v2 natif : users / orders / purchases / purchase_options
        # (les tables legacy adherents / adherents_seasons ne sont plus créées)
        schema_v2.ensure_v2_schema(cursor)

        # Création des tables de saisons
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 0
        );
        """)

        # Insérer les saisons par défaut
        cursor.execute("INSERT OR IGNORE INTO seasons (name, is_active) VALUES ('2025-2026', 0)")
        cursor.execute("INSERT OR IGNORE INTO seasons (name, is_active) VALUES ('2026-2027', 1)")
        
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
            helloasso_tarifs TEXT DEFAULT '[]',
            naissance_min TEXT DEFAULT '',
            naissance_max TEXT DEFAULT ''
        );
        """)
        
        # S'assurer de la présence de la colonne helloasso_tarifs pour les BDD existantes (migration auto)
        try:
            cursor.execute("SELECT helloasso_tarifs FROM planning LIMIT 1")
        except sqlite3.OperationalError:
            print("🔧 [SQLITE] Ajout de la colonne 'helloasso_tarifs' à la table planning...")
            cursor.execute("ALTER TABLE planning ADD COLUMN helloasso_tarifs TEXT DEFAULT '[]'")
            conn.commit()

        # S'assurer de la présence des bornes de date de naissance par groupe (migration auto)
        # Utilisées pour le contrôle d'âge : un adulte (18 ans révolus au 01/09) ne peut pas
        # souscrire à un groupe enfants / collège / lycée, et l'année de naissance doit
        # correspondre aux années du tarif HelloAsso (ex : « jeunes nés en 2011, 2012... »).
        for _dob_col in ("naissance_min", "naissance_max"):
            try:
                cursor.execute(f"SELECT {_dob_col} FROM planning LIMIT 1")
            except sqlite3.OperationalError:
                print(f"🔧 [SQLITE] Ajout de la colonne '{_dob_col}' à la table planning...")
                cursor.execute(f"ALTER TABLE planning ADD COLUMN {_dob_col} TEXT DEFAULT ''")
                conn.commit()
        
        # Création de la table de templates d'email (Nouveau !)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            sender_email TEXT DEFAULT '',
            sender_name TEXT DEFAULT ''
        );
        """)

        # S'assurer de la présence de la colonne sender_email (adresse d'expédition) pour les BDD existantes (migration auto)
        try:
            cursor.execute("SELECT sender_email FROM email_templates LIMIT 1")
        except sqlite3.OperationalError:
            print("🔧 [SQLITE] Ajout de la colonne 'sender_email' à la table email_templates...")
            cursor.execute("ALTER TABLE email_templates ADD COLUMN sender_email TEXT DEFAULT ''")
            conn.commit()

        # S'assurer de la présence de la colonne sender_name (nom d'affichage de l'expéditeur) pour les BDD existantes (migration auto)
        try:
            cursor.execute("SELECT sender_name FROM email_templates LIMIT 1")
        except sqlite3.OperationalError:
            print("🔧 [SQLITE] Ajout de la colonne 'sender_name' à la table email_templates...")
            cursor.execute("ALTER TABLE email_templates ADD COLUMN sender_name TEXT DEFAULT ''")
            conn.commit()

        # Renseigner l'adresse d'expédition par défaut sur les modèles qui n'en ont pas encore
        cursor.execute("SELECT COUNT(*) FROM email_templates WHERE sender_email IS NULL OR TRIM(sender_email) = ''")
        if cursor.fetchone()[0] > 0:
            cursor.execute("UPDATE email_templates SET sender_email = ? WHERE sender_email IS NULL OR TRIM(sender_email) = ''", (DEFAULT_SENDER_EMAIL,))
            conn.commit()

        # Renseigner le nom d'affichage par défaut sur les modèles qui n'en ont pas encore
        cursor.execute("SELECT COUNT(*) FROM email_templates WHERE sender_name IS NULL OR TRIM(sender_name) = ''")
        if cursor.fetchone()[0] > 0:
            cursor.execute("UPDATE email_templates SET sender_name = ? WHERE sender_name IS NULL OR TRIM(sender_name) = ''", (DEFAULT_SENDER_NAME,))
            conn.commit()

        # Seed des templates par défaut si vides (Nouveau !)
        cursor.execute("SELECT COUNT(*) FROM email_templates")
        cnt_tmpl = cursor.fetchone()[0]
        if cnt_tmpl == 0:
            default_templates = [
                ("Attestation standard", "Attestation de paiement escalade - Amicale Laïque de Jonage",
                 "Bonjour {first_name},\n\nNous avons le plaisir de vous transmettre en pièce jointe l'attestation de paiement pour votre adhésion ou celle de votre enfant à la section escalade de l'Amicale Laïque de Jonage pour la saison.\n\nSportivement,\nL'équipe ALJ Escalade",
                 DEFAULT_SENDER_EMAIL, DEFAULT_SENDER_NAME),
                ("Relance inscription", "Rappel : Finalisation de votre inscription ALJ Escalade",
                 "Bonjour {first_name},\n\nSauf erreur de notre part, il nous manque encore certains éléments pour finaliser votre dossier d'adhésion pour la saison.\nNous vous invitons à vous connecter sur votre espace licencié pour vérifier le statut de votre certificat médical.\n\nSportivement,\nL'équipe ALJ Escalade",
                 DEFAULT_SENDER_EMAIL, DEFAULT_SENDER_NAME)
            ]
            cursor.executemany("""
                INSERT INTO email_templates (name, subject, body, sender_email, sender_name) VALUES (?, ?, ?, ?, ?)
            """, default_templates)
            conn.commit()
        
        # Création de la table de réglages applicatifs (clé/valeur) : texte WhatsApp, etc. (Nouveau !)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        
        # Phase 0/5 — Gestion de la version du schéma (PRAGMA user_version)
        cursor.execute("PRAGMA user_version")
        current_version = cursor.fetchone()[0]
        if current_version == 1:
            # Ancienne base legacy (v1) : auto-migration vers v2 au démarrage.
            # Le drapeau est posé avant l'appel pour éviter toute récursion (migrate
            # appelle setup_database lui-même).
            cls._database_setup_done = True
            conn.commit()
            conn.close()
            print("🔁 [SQLITE] Base legacy (v1) détectée : lancement de la migration v2...")
            import migrate_schema_v2
            migrate_schema_v2.migrate(skip_excel=False)
            if cls._startup_db_hash is None:
                cls._startup_db_hash = cls.get_file_hash()
            return
        if current_version == 0:
            cursor.execute(f"PRAGMA user_version = {schema_v2.SCHEMA_TARGET_VERSION}")
            print(f"🔖 [SQLITE] Base neuve taguée en version {schema_v2.SCHEMA_TARGET_VERSION} (schéma v2 natif).")
        # Vue de compatibilité : recréée à chaque démarrage pour suivre la définition du code
        schema_v2.recreate_compat_view(cursor)
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
        Charge les données d'adhérents depuis la vue de compatibilité (schéma v2)
        pour une saison spécifique ou un filtre comparatif.
        """
        # Résolution pour la rétrocompatibilité (si un chemin de fichier Excel .xlsx est passé)
        if isinstance(season_filter, str) and (season_filter.endswith(".xlsx") or "\\" in season_filter or "/" in season_filter):
            season_filter = "2026-2027" # Par défaut

        cls.setup_database()
        conn = cls.get_connection()
        try:
            return cls._load_data_from_compat_view(conn, season_filter)
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors du chargement des données : {e}")
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
    def get_members(cls, season_filter: str = "2026-2027") -> list:
        """
        Phase 4 — Lecture typée canonique : retourne des objets Member construits
        depuis la lecture bilingue (vue de compatibilité + Member.from_dict).
        API recommandée pour les nouveaux consommateurs.
        """
        from domain.models import Member
        return [Member.from_dict(row) for row in cls.load_direct_data(season_filter=season_filter)]

    @classmethod
    def export_to_excel(cls, file_path: str) -> bool:
        """
        Phase 9 — Exporte les adhérents de la saison active vers un fichier Excel,
        via Member.to_dict() (adaptateur vers le format colonnes historique).
        """
        cls.setup_database()
        members = cls.get_members(season_filter="2026-2027")

        excel_rows = []
        for m in members:
            d = m.to_dict()
            excel_row = {}
            # Reconstituer toutes les colonnes d'origine de CORRECTIVE_MAP
            for excel_col, cache_key in CORRECTIVE_MAP.items():
                excel_row[excel_col] = d.get(cache_key, "")

            # Ajouter les colonnes supplémentaires indispensables
            for col_key in EXTRA_COLUMNS.keys():
                excel_row[col_key] = d.get(col_key, "")

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
        """
        Phase 5 - Insere ou met a jour un lot d'adherents dans le schema v2
        (users / orders / purchases / purchase_options).
        """
        cls.setup_database()
        conn = cls.get_connection()
        inserted_count = 0
        try:
            cursor = conn.cursor()
            stats = schema_v2.sync_members_to_v2(cursor, members, season_name)
            inserted_count = stats["purchases"]
            conn.commit()
            print(f"[SQLITE] Synchro reussie : {inserted_count} adhesions enregistrees/mises a jour "
                  f"pour la saison {season_name}. (v2: {stats})")
        except Exception as e:
            print(f"[SQLITE] Erreur lors de l'upsert des adherents : {e}")
            conn.rollback()
        finally:
            conn.close()
        return inserted_count

    @classmethod
    def update_member_in_db(cls, original_order_ref: str, original_last_name: str, original_first_name: str, updated_fields: dict, comment_text: str):
        """
        Phase 5 - Met a jour un adherent dans le schema v2 :
        champs personnels -> users, champs de saison -> purchases (avec options).
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            from domain.utils import normalize_name
            cursor.execute("""
                SELECT p.user_id FROM purchases p
                JOIN orders o ON o.id = p.order_id
                WHERE o.order_ref = ?
            """, (original_order_ref.strip(),))
            rows = cursor.fetchall()
            user_id = None
            if rows:
                t_last = normalize_name(original_last_name)
                t_first = normalize_name(original_first_name)
                for r in rows:
                    u = cursor.execute("SELECT last_name, first_name FROM users WHERE id=?", (r["user_id"],)).fetchone()
                    if u and normalize_name(u["last_name"]) == t_last and normalize_name(u["first_name"]) == t_first:
                        user_id = r["user_id"]
                        break
                if user_id is None:
                    # Fallback famille : premier utilisateur de la commande
                    user_id = rows[0]["user_id"]
            if user_id is None:
                conn.close()
                return False, f"Aucun adherent correspondant trouve pour {original_last_name} {original_first_name}."
            schema_v2.apply_member_update(cursor, user_id, original_order_ref, updated_fields, comment_text)
            conn.commit()
            print(f"[SQLITE] Adherent {original_last_name} {original_first_name} mis a jour avec succes (v2).")
            return True, ""
        except Exception as e:
            print(f"[SQLITE] Erreur lors de la mise a jour de l'adherent : {e}")
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()
    @classmethod
    def get_season_tarifs(cls, season_name: str = "2026-2027") -> list:
        """Retourne la liste triée des tarifs HelloAsso distincts d'une saison (groupes disponibles)."""
        cls.setup_database()
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT p.tarif_name
                FROM purchases p
                JOIN orders o ON o.id = p.order_id
                JOIN seasons s ON s.id = o.season_id
                WHERE s.name = ? AND p.tarif_name IS NOT NULL AND TRIM(p.tarif_name) != ''
                ORDER BY p.tarif_name ASC
            """, (season_name,))
            return [r["tarif_name"].strip() for r in cursor.fetchall()]
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors du chargement des tarifs de la saison {season_name} : {e}")
            return []
        finally:
            conn.close()

    @classmethod
    def update_member_tarif(cls, order_ref: str, last_name: str, first_name: str, new_tarif: str):
        """Change le tarif (groupe) d'un adhérent : met à jour purchases.tarif_name.

        Retourne (succès, message_erreur).
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            from domain.utils import normalize_name
            new_tarif_clean = str(new_tarif or "").strip()
            if not new_tarif_clean:
                return False, "Le nouveau tarif ne peut pas être vide."

            cursor.execute("""
                SELECT p.user_id FROM purchases p
                JOIN orders o ON o.id = p.order_id
                WHERE o.order_ref = ?
            """, (str(order_ref or "").strip(),))
            rows = cursor.fetchall()
            user_id = None
            t_last = normalize_name(last_name)
            t_first = normalize_name(first_name)
            for r in rows:
                u = cursor.execute("SELECT last_name, first_name FROM users WHERE id=?", (r["user_id"],)).fetchone()
                if u and normalize_name(u["last_name"]) == t_last and normalize_name(u["first_name"]) == t_first:
                    user_id = r["user_id"]
                    break
            if user_id is None and rows:
                # Fallback famille : premier utilisateur de la commande
                user_id = rows[0]["user_id"]
            if user_id is None:
                return False, f"Aucun adhérent correspondant trouvé pour {last_name} {first_name}."

            now_iso = datetime.datetime.now().isoformat(timespec="seconds")
            cursor.execute("""
                UPDATE purchases
                SET tarif_name = ?, is_modified = 'Oui', updated_at = ?
                WHERE user_id = ? AND order_id IN (SELECT id FROM orders WHERE order_ref = ?)
            """, (new_tarif_clean, now_iso, user_id, str(order_ref or "").strip()))
            if cursor.rowcount == 0:
                conn.rollback()
                return False, "Aucune inscription trouvée pour cet adhérent et cette commande."
            conn.commit()
            print(f"[SQLITE] Tarif de {last_name} {first_name} changé en '{new_tarif_clean}' (commande {order_ref}).")
            return True, ""
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors du changement de tarif : {e}")
            conn.rollback()
            return False, str(e)
        finally:
            conn.close()

    @classmethod
    def update_email_sent_date(cls, order_ref: str, last_name: str, first_name: str, date_str: str) -> bool:
        """Phase 5 - Met a jour la date d'envoi d'e-mail sur les achats v2 de la commande."""
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE purchases
                SET email_sent_date = ?
                WHERE order_id IN (SELECT id FROM orders WHERE order_ref = ?)
                  AND user_id IN (
                      SELECT id FROM users
                      WHERE UPPER(TRIM(last_name)) = ? AND LOWER(TRIM(first_name)) = ?
                  )
            """, (date_str, order_ref.strip(),
                  str(last_name or "").strip().upper(), str(first_name or "").strip().lower()))
            rows_affected = cursor.rowcount
            if rows_affected == 0:
                cursor.execute("""
                    UPDATE purchases
                    SET email_sent_date = ?
                    WHERE order_id IN (SELECT id FROM orders WHERE order_ref = ?)
                """, (date_str, order_ref.strip()))
                rows_affected = cursor.rowcount
            conn.commit()
            if rows_affected > 0:
                print(f"[SQLITE] Date d'envoi d'e-mail enregistree pour la commande {order_ref} : {date_str}")
                return True
            print(f"[SQLITE] Aucun achat trouve pour la commande {order_ref}")
            return False
        except Exception as e:
            print(f"[SQLITE] Erreur lors de la mise a jour de la date d'envoi d'e-mail : {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    @classmethod
    def prepare_ffme_licensees(cls, excel_path: str) -> dict:
        """
        Phase A de l'import FFME — lit le fichier Excel, charge les utilisateurs et
        applique le rapprochement automatique (N° de licence puis Nom/Prénom).
        Ne modifie PAS la base. Retourne :
          {
            "updates":   [(match_type, licence, passeports, diplomas, user_id), ...],
            "unmatched": [{"nom", "prenom", "licence", "birth_date", "passeports", "diplomes"}, ...],
            "users":     [{"id", "last_name", "first_name", "licence_ffme", "birth_date"}, ...],
            "stats":     {"total_processed", "matched_by_licence", "matched_by_name", "errors"},
          }
        """
        import pandas as pd
        from domain.utils import normalize_name

        prep = {"updates": [], "unmatched": [], "users": [],
                "stats": {"total_processed": 0, "matched_by_licence": 0,
                          "matched_by_name": 0, "errors": []}}
        stats = prep["stats"]

        if not os.path.exists(excel_path):
            stats["errors"].append(f"Fichier introuvable : {excel_path}")
            return prep
        try:
            df = pd.read_excel(excel_path)
        except Exception as e:
            stats["errors"].append(f"Erreur de lecture Excel : {e}")
            return prep

        required_cols = ["Nom", "Pr\u00e9nom", "N\u00b0 de licence"]
        for col in required_cols:
            if col not in df.columns:
                stats["errors"].append(f"Colonne requise manquante dans le fichier Excel : {col}")
                return prep

        cls.setup_database()
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, last_name, first_name, licence_ffme,
                       COALESCE(birth_date, birth_date_raw, '') AS birth_date
                FROM users
            """)
            users = [dict(row) for row in cursor.fetchall()]
            prep["users"] = [
                {"id": u["id"], "last_name": u["last_name"], "first_name": u["first_name"],
                 "licence_ffme": u["licence_ffme"], "birth_date": u["birth_date"]}
                for u in users
            ]

            users_by_licence = {}
            users_by_name = {}
            for u in users:
                lic = str(u["licence_ffme"] or "").strip()
                if lic.endswith(".0"):
                    lic = lic[:-2]
                clean_lic = "".join(c for c in lic if c.isdigit())
                if clean_lic:
                    users_by_licence[clean_lic] = u
                nk = normalize_name(u["last_name"])
                fk = normalize_name(u["first_name"])
                if nk and fk:
                    users_by_name[(nk, fk)] = u

            def _cell_str(row, key):
                val = row.get(key)
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return ""
                return str(val).strip() if not hasattr(val, "strftime") else val.strftime("%d/%m/%Y")

            for idx, row in df.iterrows():
                stats["total_processed"] += 1
                raw_lic = row["N\u00b0 de licence"]
                if pd.isna(raw_lic):
                    lic_str = ""
                elif isinstance(raw_lic, float):
                    lic_str = str(int(raw_lic)).strip()
                else:
                    lic_str = str(raw_lic).strip()
                nom = str(row["Nom"] or "").strip()
                prenom = str(row["Pr\u00e9nom"] or "").strip()

                matched = None
                if lic_str and lic_str in users_by_licence:
                    matched = users_by_licence[lic_str]
                    match_type = "licence"
                if not matched and nom and prenom:
                    key = (normalize_name(nom), normalize_name(prenom))
                    if key in users_by_name:
                        matched = users_by_name[key]
                        match_type = "name"
                if matched:
                    final_lic = lic_str if lic_str else str(matched["licence_ffme"] or "")
                    passports_str = _cell_str(row, "Passeports")
                    if passports_str.lower() in ("nan", "none", ""):
                        passports_str = ""
                    diplomas_str = _cell_str(row, "Dipl\u00f4mes")
                    if diplomas_str.lower() in ("nan", "none", ""):
                        diplomas_str = ""
                    prep["updates"].append(("Terminé", final_lic, passports_str, diplomas_str, matched["id"]))
                    if match_type == "licence":
                        stats["matched_by_licence"] += 1
                    else:
                        stats["matched_by_name"] += 1
                else:
                    prep["unmatched"].append({
                        "nom": nom, "prenom": prenom, "licence": lic_str,
                        "birth_date": _cell_str(row, "Date de naissance"),
                        "passeports": _cell_str(row, "Passeports"),
                        "diplomes": _cell_str(row, "Dipl\u00f4mes"),
                    })
        except Exception as e:
            stats["errors"].append(f"Erreur lors du rapprochement FFME : {e}")
        finally:
            conn.close()
        return prep

    @classmethod
    def apply_ffme_matches(cls, updates: list) -> bool:
        """
        Phase B de l'import FFME — écrit en base les associations validées :
        updates = [(match_type, licence, passeports, diplomas, user_id), ...]
        Met à jour la licence/passeports/diplômes de l'utilisateur et bascule
        ses achats de la saison active en statut "Terminé" (licence FFME confirmée).
        """
        if not updates:
            return True
        cls.create_db_backup()
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.executemany("""
                UPDATE users
                SET licence_ffme = ?, raw_passports = ?, raw_diplomas = ?
                WHERE id = ?
            """, [(u[1], u[2], u[3], u[4]) for u in updates])
            cursor.executemany("""
                UPDATE purchases
                SET status = ?, status_normalized = ?
                WHERE user_id = ? AND order_id IN (
                    SELECT id FROM orders
                    WHERE season_id = (SELECT id FROM seasons WHERE name = '2026-2027')
                )
            """, [(u[0], schema_v2.normalize_status(u[0]), u[4]) for u in updates])
            conn.commit()
            return True
        except Exception as e:
            print(f"[SQLITE] Erreur lors de la fusion FFME en BDD : {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    @classmethod
    def merge_ffme_licensees(cls, excel_path: str) -> dict:
        """
        Import FFME non interactif (rétrocompatibilité / scripts) :
        rapprochement automatique + écriture directe, sans association manuelle.
        """
        prep = cls.prepare_ffme_licensees(excel_path)
        stats = prep["stats"]
        if not stats["errors"]:
            if not cls.apply_ffme_matches(prep["updates"]):
                stats["errors"].append("Erreur lors de la fusion en BDD.")
        stats["not_found"] = len(prep["unmatched"])
        return stats

    @classmethod
    def merge_autonomes_data(cls, excel_path: str) -> dict:
        """
        Phase 5 - Importe la liste d'autonomie (Autonomes_*.xlsx) et la fusionne avec
        les utilisateurs du schema v2 (badge rouge, autonomie bloc, passeports).
        """
        cls.create_db_backup()
        import pandas as pd
        from domain.utils import normalize_name

        stats = {"total_processed": 0, "matched": 0, "not_found": 0, "errors": []}

        if not os.path.exists(excel_path):
            stats["errors"].append(f"Fichier introuvable : {excel_path}")
            return stats
        try:
            df = pd.read_excel(excel_path, header=1)
            df = df.fillna("")
        except Exception as e:
            stats["errors"].append(f"Erreur de lecture Excel : {e}")
            return stats

        required_cols = ["N\u00b0 de licence", "Badge rouge diff", "Autonomie Bloc"]
        for col in required_cols:
            if col not in df.columns:
                stats["errors"].append(f"Colonne requise manquante dans le fichier Excel : {col}")
                return stats

        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, last_name, first_name, licence_ffme, raw_passports FROM users")
            users = [dict(row) for row in cursor.fetchall()]

            users_by_licence = {}
            for u in users:
                lic = str(u["licence_ffme"] or "").strip()
                if lic.endswith(".0"):
                    lic = lic[:-2]
                clean_lic = "".join(c for c in lic if c.isdigit())
                if clean_lic:
                    users_by_licence[clean_lic] = u

            users_by_name = {}
            for u in users:
                nk = normalize_name(u["last_name"])
                fk = normalize_name(u["first_name"])
                if nk and fk:
                    users_by_name[(nk, fk)] = u

            updates = []  # (badge_rouge, autonomie_bloc, raw_passports, user_id)
            file_badge_rouge_count = 0

            for idx, row in df.iterrows():
                stats["total_processed"] += 1
                raw_lic = str(row.get("N\u00b0 de licence", "")).strip()
                if raw_lic.endswith(".0"):
                    raw_lic = raw_lic[:-2]
                lic_num = "".join(c for c in raw_lic if c.isdigit())

                badge_rouge_raw = str(row.get("Badge rouge diff", "")).strip().upper()
                autonomie_bloc_raw = str(row.get("Autonomie Bloc", "")).strip().upper()
                if badge_rouge_raw == "X":
                    file_badge_rouge_count += 1
                badge_rouge = "Oui" if badge_rouge_raw == "X" else ("Non" if not badge_rouge_raw else row.get("Badge rouge diff", ""))
                autonomie_bloc = "Oui" if autonomie_bloc_raw == "X" else ("Non" if not autonomie_bloc_raw else row.get("Autonomie Bloc", ""))

                has_orange_raw = str(row.get("Passeport Orange", "")).strip().upper()
                orange_passport_val = "Escalade - Passeport orange" if has_orange_raw == "X" else ""

                matched = None
                if lic_num and lic_num in users_by_licence:
                    matched = users_by_licence[lic_num]
                if not matched:
                    nom_raw = str(row.get("NOM", "")).strip()
                    prenom_raw = str(row.get("Pr\u00e9nom", "")).strip()
                    if nom_raw and prenom_raw:
                        key = (normalize_name(nom_raw), normalize_name(prenom_raw))
                        if key in users_by_name:
                            matched = users_by_name[key]

                if matched:
                    existing_passports = str(matched.get("raw_passports") or "").strip()
                    if orange_passport_val and "orange" not in existing_passports.lower():
                        new_passports = f"{existing_passports}, {orange_passport_val}" if existing_passports else orange_passport_val
                    else:
                        new_passports = existing_passports
                    updates.append((badge_rouge, autonomie_bloc, new_passports, matched["id"]))
                    stats["matched"] += 1
                else:
                    stats["not_found"] += 1

            stats["file_badge_rouge_count"] = file_badge_rouge_count

            if updates:
                cursor.executemany("""
                    UPDATE users
                    SET badge_rouge = ?, autonomie_bloc = ?, raw_passports = ?
                    WHERE id = ?
                """, updates)
                conn.commit()

            cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE badge_rouge = 'Oui'")
            stats["db_total_badge_rouge"] = cursor.fetchone()["cnt"]
            cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE autonomie_bloc = 'Oui' AND (badge_rouge IS NULL OR badge_rouge != 'Oui')")
            stats["db_autonomes_without_badge_rouge"] = cursor.fetchone()["cnt"]
        except Exception as e:
            conn.rollback()
            stats["errors"].append(f"Erreur lors de la fusion en BDD : {e}")
        finally:
            conn.close()
        return stats

    def import_old_season_ffme(cls, excel_path: str, season_name: str = "2025-2026") -> dict:
        """
        Phase 5 - Importe les licencies d'une ancienne saison depuis un export FFME
        (.xlsx) et les rattache a la saison specifiee dans le schema v2.
        Cree les utilisateurs inexistants.
        """
        cls.create_db_backup()
        import pandas as pd
        from domain.utils import normalize_name

        stats = {"total_processed": 0, "created": 0, "linked": 0, "errors": []}

        if not os.path.exists(excel_path):
            stats["errors"].append(f"Fichier introuvable : {excel_path}")
            return stats

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
            print(f"[SQLITE] Erreur de lecture du fichier d'importation (fichier probablement verrouille) : {e}")
            stats["errors"].append(f"Erreur de lecture du fichier Excel : {e}")
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return stats

        required_cols = ["Nom", "Pr\u00e9nom"]
        for col in required_cols:
            if col not in df.columns:
                stats["errors"].append(f"Colonne requise manquante dans le fichier Excel : {col}")
                return stats

        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM seasons WHERE name = ?", (season_name,))
            row_s = cursor.fetchone()
            if not row_s:
                cursor.execute("INSERT INTO seasons (name, is_active) VALUES (?, 0)", (season_name,))
                season_id = cursor.lastrowid
            else:
                season_id = row_s["id"]

            cursor.execute("SELECT id, last_name_key, first_name_key, licence_ffme, raw_passports FROM users")
            users = [dict(row) for row in cursor.fetchall()]

            users_by_licence = {}
            users_by_name = {}
            for u in users:
                lic = str(u["licence_ffme"] or "").strip()
                if lic.endswith(".0"):
                    lic = lic[:-2]
                clean_lic = "".join(c for c in lic if c.isdigit())
                if clean_lic:
                    users_by_licence[clean_lic] = u

            for u in users:
                # Les cles normalisees sont deja en base (last_name_key / first_name_key)
                if u["last_name_key"] and u["first_name_key"]:
                    users_by_name[(u["last_name_key"], u["first_name_key"])] = u

            now_iso = datetime.datetime.now().isoformat(timespec="seconds")

            for idx, row in df.iterrows():
                stats["total_processed"] += 1
                nom = str(row.get("Nom", "")).strip()
                prenom = str(row.get("Pr\u00e9nom", "")).strip()
                if not nom or not prenom:
                    continue

                raw_lic = str(row.get("N\u00b0 de licence", "")).strip()
                if raw_lic.endswith(".0"):
                    raw_lic = raw_lic[:-2]
                lic_num = "".join(c for c in raw_lic if c.isdigit())

                matched = None
                if lic_num and lic_num in users_by_licence:
                    matched = users_by_licence[lic_num]
                if not matched:
                    key = (normalize_name(nom), normalize_name(prenom))
                    if key in users_by_name:
                        matched = users_by_name[key]

                passports_col = str(row.get("Passeports", "")).strip()
                has_orange_in_excel = "orange" in passports_col.lower()

                if matched:
                    user_id = matched["id"]
                    if lic_num and not str(matched["licence_ffme"] or "").strip():
                        cursor.execute("UPDATE users SET licence_ffme=?, updated_at=? WHERE id=?",
                                       (raw_lic, now_iso, user_id))
                    if has_orange_in_excel:
                        existing_passports = str(matched.get("raw_passports") or "").strip()
                        if "orange" not in existing_passports.lower():
                            new_passports = f"{existing_passports}, Escalade - Passeport orange" if existing_passports else "Escalade - Passeport orange"
                            cursor.execute("UPDATE users SET raw_passports=? WHERE id=?", (new_passports, user_id))
                else:
                    sexe = str(row.get("Sexe", "")).strip()
                    birth_raw = str(row.get("Date de naissance", "")).strip()
                    if birth_raw.endswith(" 00:00:00"):
                        birth_raw = birth_raw[:-9]
                    address = str(row.get("Adresse", "")).strip()
                    zip_code = str(row.get("Code postal", "")).strip()
                    if zip_code.endswith(".0"):
                        zip_code = zip_code[:-2]
                    city = str(row.get("Ville", "")).strip()
                    phone = str(row.get("T\u00e9l\u00e9phone", "")).strip()
                    email = str(row.get("Email", "")).strip()
                    passports = str(row.get("Passeports", "")).strip()
                    if passports.lower() in ("nan", "none", "aucune", ""):
                        passports = ""
                    diplomas = str(row.get("Dipl\u00f4mes", "")).strip()
                    if diplomas.lower() in ("nan", "none", "aucune", ""):
                        diplomas = ""
                    if has_orange_in_excel and "orange" not in passports.lower():
                        passports = f"{passports}, Escalade - Passeport orange" if passports else "Escalade - Passeport orange"

                    cursor.execute("""
                        INSERT INTO users (
                            last_name, first_name, last_name_key, first_name_key,
                            birth_date, birth_date_raw, gender, address, zip_code, city,
                            phone, email_primary, licence_ffme, raw_passports, raw_diplomas,
                            badge_rouge, autonomie_bloc, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Non', 'Non', ?, ?)
                    """, (
                        nom, prenom,
                        normalize_name(nom).upper(), normalize_name(prenom).lower(),
                        schema_v2.parse_iso_date(birth_raw), birth_raw, sexe, address, zip_code, city,
                        phone, email, raw_lic, passports, diplomas, now_iso, now_iso
                    ))
                    user_id = cursor.lastrowid
                    users_by_licence[lic_num] = {"id": user_id, "licence_ffme": raw_lic, "raw_passports": passports}
                    users_by_name[(normalize_name(nom), normalize_name(prenom))] = {"id": user_id}
                    stats["created"] += 1

                # Commande synthetique + achat rattache a la saison importee
                placeholder_ref = f"IMPORT-FFME-{season_name.replace('-', '')}-{user_id:04d}"
                cursor.execute("SELECT id FROM orders WHERE order_ref=?", (placeholder_ref,))
                row_o = cursor.fetchone()
                if row_o:
                    order_id = row_o["id"]
                else:
                    cursor.execute("""
                        INSERT INTO orders (order_ref, order_date, status, status_normalized, season_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (placeholder_ref, f"{season_name.split('-')[0]}-09-01", "Valid\u00e9", "Valid\u00e9",
                          season_id, now_iso, now_iso))
                    order_id = cursor.lastrowid

                tarif_name_val = str(row.get("Type de licence", "")).strip()
                if not tarif_name_val or tarif_name_val.lower() == "nan":
                    tarif_name_val = f"Import Historique (Saison {season_name})"

                cursor.execute("""
                    INSERT OR REPLACE INTO purchases (
                        order_id, user_id, tarif_name, amount, status, status_normalized,
                        is_modified, commentaires_correctif, legacy_adherent_id, legacy_season_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """, (
                    order_id, user_id, tarif_name_val, 0.0, "Valid\u00e9", "Valid\u00e9",
                    "Non",
                    f"Import\u00e9 automatiquement depuis le fichier FFME de la saison {season_name}",
                    season_id, now_iso, now_iso
                ))
                stats["linked"] += 1

            conn.commit()
            print(f"[SQLITE] Import de la saison {season_name} termine : {stats['created']} utilisateurs crees, {stats['linked']} achats etablis.")
            return stats
        except Exception as e:
            conn.rollback()
            stats["errors"].append(f"Erreur lors de l'import : {e}")
            raise
        finally:
            conn.close()

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
                    INSERT OR REPLACE INTO planning (id, groupe, type, categorie_age, whatsapp_link, jour, horaires, encadrants, helloasso_tarifs, naissance_min, naissance_max)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.get("id"),
                    item.get("groupe"),
                    item.get("type", "cours"),
                    item.get("categorie_age", ""),
                    item.get("whatsapp_link", ""),
                    item.get("jour", "Lundi"),
                    item.get("horaires", ""),
                    enc_json,
                    tarifs_json,
                    str(item.get("naissance_min") or ""),
                    str(item.get("naissance_max") or "")
                ))
                inserted += 1
            conn.commit()
            print(f"✅ [SQLITE] Migration réussie de {inserted} créneaux de planning avec leurs correspondances de tarifs.")
            
            # Archiver les fichiers json historiques
            try:
                if os.path.exists(json_path):
                    os.rename(json_path, json_path + ".migrated")
                    print("📦 [SQLITE] Fichier planning.json archivé en .migrated")
                if os.path.exists(tarif_mapping_path):
                    os.rename(tarif_mapping_path, tarif_mapping_path + ".migrated")
                    print("📦 [SQLITE] Fichier tarif_mapping.json archivé en .migrated")
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
    def load_planning_data(cls, log_debug: bool = True) -> list:
        """Charge l'ensemble du planning de créneaux depuis SQLite.

        log_debug=False évite l'écriture du journal de debug (appels fréquents IHM).
        """
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
            if log_debug:
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
                    INSERT OR REPLACE INTO planning (id, groupe, type, categorie_age, whatsapp_link, jour, horaires, encadrants, helloasso_tarifs, naissance_min, naissance_max)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.get("id"),
                    item.get("groupe"),
                    item.get("type", "cours"),
                    item.get("categorie_age", ""),
                    item.get("whatsapp_link", ""),
                    item.get("jour", "Lundi"),
                    item.get("horaires", ""),
                    enc_json,
                    tarifs_json,
                    str(item.get("naissance_min") or ""),
                    str(item.get("naissance_max") or "")
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
        Retourne une liste de dicts : [{"name": ..., "subject": ..., "body": ..., "sender_email": ..., "sender_name": ...}]
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT name, subject, body, sender_email, sender_name FROM email_templates ORDER BY name ASC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la récupération des templates d'emails : {e}")
            return []
        finally:
            conn.close()

    @classmethod
    def save_email_template(cls, name: str, subject: str, body: str, sender_email: str = "", sender_name: str = "") -> bool:
        """
        Enregistre ou met à jour un template d'email dans la BDD
        (avec son adresse et son nom d'affichage d'expédition).
        Une adresse / un nom vide retombe sur les valeurs par défaut du club.
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            sender = (sender_email or "").strip() or DEFAULT_SENDER_EMAIL
            sname = (sender_name or "").strip() or DEFAULT_SENDER_NAME
            cursor.execute("""
                INSERT INTO email_templates (name, subject, body, sender_email, sender_name)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET subject = excluded.subject, body = excluded.body,
                    sender_email = excluded.sender_email, sender_name = excluded.sender_name
            """, (name.strip(), subject.strip(), body.strip(), sender, sname))
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

    @classmethod
    def get_whatsapp_template(cls) -> str:
        """
        Récupère le texte d'invitation WhatsApp personnalisé enregistré en BDD.
        Retourne None si aucun texte n'a été sauvegardé.
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT value FROM app_settings WHERE key = ?", ("whatsapp_template",))
            row = cursor.fetchone()
            if row is None:
                return None
            value = row["value"]
            return value if value and value.strip() else None
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la récupération du texte WhatsApp : {e}")
            return None
        finally:
            conn.close()

    @classmethod
    def save_whatsapp_template(cls, text: str) -> bool:
        """
        Enregistre ou met à jour le texte d'invitation WhatsApp personnalisé dans la BDD.
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, ("whatsapp_template", text))
            conn.commit()
            return True
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de l'enregistrement du texte WhatsApp : {e}")
            return False
        finally:
            conn.close()

    @classmethod
    def get_app_setting(cls, key: str, default: str = None) -> str:
        """
        Récupère une valeur générique de réglage applicatif (clé/valeur) depuis la BDD.
        Retourne `default` si la clé est absente ou vide.
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row is None:
                return default
            value = row["value"]
            return value if value and str(value).strip() else default
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de la lecture du réglage '{key}' : {e}")
            return default
        finally:
            conn.close()

    @classmethod
    def save_app_setting(cls, key: str, value: str) -> bool:
        """
        Enregistre ou met à jour une valeur générique de réglage applicatif (clé/valeur) dans la BDD.
        """
        cls.setup_database()
        conn = cls.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))
            conn.commit()
            return True
        except Exception as e:
            print(f"❌ [SQLITE] Erreur lors de l'enregistrement du réglage '{key}' : {e}")
            return False
        finally:
            conn.close()
