"""
Dépôt SQLite dédié au module de gestion des compétitions : database_Competition.db.

- Base distincte de database.db (adhérents), même dossier de cache local (data/).
- La table `adherents` est un instantané initialisé depuis la base principale
  (vue v_adherents_legacy) afin que le module reste autonome (page web, Drive).
- Schéma : competitions / participants / adherents / app_settings.
"""
import os
import sqlite3
import datetime

from paths import DATA_ROOT
from domain.competition_models import (
    Competition,
    Participant,
    PAIEMENT_NON_INVITE,
)

DB_FILENAME = "database_Competition.db"


class CompetitionRepository:
    """Gère la persistance locale de la base dédiée aux compétitions."""

    _db_path = os.path.join(DATA_ROOT, DB_FILENAME)
    _db_path_overridden = False
    _database_setup_done = False

    # ------------------------------------------------------------------
    # Chemins & connexion
    # ------------------------------------------------------------------
    @classmethod
    def get_db_path(cls) -> str:
        return cls._db_path

    @classmethod
    def set_db_path(cls, path: str):
        cls._db_path = path
        cls._db_path_overridden = True
        cls._database_setup_done = False

    @classmethod
    def get_connection(cls) -> sqlite3.Connection:
        conn = sqlite3.connect(cls._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.OperationalError:
            pass
        return conn

    @classmethod
    def setup_database(cls, force: bool = False):
        """Crée le fichier et les tables si nécessaire."""
        if not force and cls._database_setup_done and os.path.exists(cls._db_path):
            return
        os.makedirs(os.path.dirname(cls._db_path), exist_ok=True)
        conn = cls.get_connection()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS competitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_ffme TEXT DEFAULT '',
                nom TEXT NOT NULL,
                date_competition TEXT DEFAULT '',
                prix REAL DEFAULT 0.0,
                statut TEXT DEFAULT 'en_preparation',
                helloasso_ref TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS adherents (
                id INTEGER PRIMARY KEY,
                nom TEXT DEFAULT '',
                prenom TEXT DEFAULT '',
                num_licence TEXT DEFAULT '',
                email TEXT DEFAULT '',
                email_secondaire TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                tarif TEXT DEFAULT '',
                saison TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
                adherent_id INTEGER NOT NULL REFERENCES adherents(id) ON DELETE CASCADE,
                selectionne INTEGER DEFAULT 0,
                statut_paiement TEXT DEFAULT 'non_invite',
                date_synchro_helloasso TEXT DEFAULT '',
                montant_paye REAL DEFAULT 0.0,
                commande_helloasso TEXT DEFAULT '',
                UNIQUE(competition_id, adherent_id)
            );
            CREATE INDEX IF NOT EXISTS idx_participants_comp ON participants(competition_id);

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            /* Miroir des groupes de créneaux (groupe + tarifs HelloAsso du planning
               de database.db) : permet le regroupement par créneau dans la page web
               sans accès à la base principale. Rafraîchi par sync_adherents_from_main. */
            CREATE TABLE IF NOT EXISTS planning_groups (
                groupe TEXT DEFAULT '',
                tarif  TEXT DEFAULT ''
            );

            /* Miroir local de la campagne annuelle HelloAsso (jamais édité à la main :
               réécrasé à chaque synchronisation). Indépendant des compétitions. */
            CREATE TABLE IF NOT EXISTS helloasso_items (
                id_item            INTEGER PRIMARY KEY,
                order_id           INTEGER,
                payer_nom          TEXT DEFAULT '',
                payer_prenom       TEXT DEFAULT '',
                montant            REAL DEFAULT 0.0,
                etat               TEXT DEFAULT '',
                date_item          TEXT DEFAULT '',
                licence_saisie     TEXT DEFAULT '',
                competition_saisie TEXT DEFAULT '',
                campagne_slug      TEXT DEFAULT '',
                raw_json           TEXT DEFAULT '',
                synced_at          TEXT DEFAULT ''
            );

            /* Liens locaux corrigibles : 1 ligne par article -> (compétition, adhérent).
               source = 'auto' (recalculé à chaque synchro) ou 'manuel' (jamais écrasé). */
            CREATE TABLE IF NOT EXISTS item_links (
                id_item        INTEGER PRIMARY KEY REFERENCES helloasso_items(id_item) ON DELETE CASCADE,
                competition_id INTEGER REFERENCES competitions(id) ON DELETE SET NULL,
                adherent_id    INTEGER REFERENCES adherents(id) ON DELETE SET NULL,
                source         TEXT DEFAULT 'auto',
                updated_at     TEXT DEFAULT ''
            );
            """)
            # Migration légère : colonne commande_helloasso (bases existantes)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(participants)").fetchall()}
            if "commande_helloasso" not in cols:
                conn.execute("ALTER TABLE participants ADD COLUMN commande_helloasso TEXT DEFAULT ''")
            conn.commit()
        finally:
            conn.close()
        cls._database_setup_done = True

    # ------------------------------------------------------------------
    # Instantané des adhérents (source : database.db principale)
    # ------------------------------------------------------------------
    @classmethod
    def sync_adherents_from_main(cls, season_filter: str = "") -> dict:
        """Initialise / rafraîchit la table `adherents` depuis la base principale.

        Lit la vue v_adherents_legacy de database.db (source de vérité) et met à
        jour l'instantané local (insert ou update ; jamais de suppression, pour
        préserver l'historique des participants des saisons passées).
        Retourne un rapport {imported, updated, errors}.
        """
        from infrastructure.sqlite_repository import SqliteRepository
        from domain.constants import get_active_season

        report = {"imported": 0, "updated": 0, "errors": []}
        season = (season_filter or get_active_season() or "").strip()

        try:
            SqliteRepository.setup_database()
            main_conn = SqliteRepository.get_connection()
        except Exception as e:
            report["errors"].append(f"Base principale inaccessible : {e}")
            return report

        rows = []
        planning_pairs = []
        try:
            if season:
                rows = main_conn.execute(
                    'SELECT * FROM v_adherents_legacy WHERE season_name = ? '
                    'ORDER BY "user_id" ASC', (season,)
                ).fetchall()
            if not rows:
                # Repli : tout l'historique (utile en tout premier lancement ou si la
                # saison active n'existe pas encore dans la base principale).
                rows = main_conn.execute(
                    'SELECT * FROM v_adherents_legacy ORDER BY "user_id" ASC'
                ).fetchall()
            # Miroir des groupes de créneaux (planning -> (groupe, tarif)) pour la page web
            try:
                import json as _json
                for pr in main_conn.execute(
                    "SELECT groupe, helloasso_tarifs FROM planning"
                ).fetchall():
                    groupe = str(pr["groupe"] or "").strip()
                    if not groupe:
                        continue
                    try:
                        tarifs = _json.loads(str(pr["helloasso_tarifs"] or "[]"))
                    except (ValueError, TypeError):
                        tarifs = []
                    for t in tarifs or []:
                        t = str(t or "").strip()
                        if t:
                            planning_pairs.append((groupe, t))
            except sqlite3.Error:
                planning_pairs = []
        except Exception as e:
            report["errors"].append(f"Lecture de la base principale impossible : {e}")
            return report
        finally:
            main_conn.close()

        cls.setup_database()
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            for row in rows:
                d = dict(row)
                adherent_id = d.get("user_id") or d.get("id")
                if adherent_id is None:
                    continue
                existing = cur.execute(
                    "SELECT id FROM adherents WHERE id = ?", (adherent_id,)
                ).fetchone()
                values = (
                    str(d.get("last_name") or "").strip().upper(),
                    str(d.get("first_name") or "").strip().title(),
                    str(d.get("licence_ffme") or "").strip(),
                    str(d.get("email_primary") or "").strip(),
                    str(d.get("email_secondary") or "").strip(),
                    str(d.get("phone") or "").strip(),
                    str(d.get("tarif_name") or "").strip(),
                    str(d.get("season_name") or "").strip(),
                )
                if existing:
                    cur.execute(
                        """UPDATE adherents SET nom=?, prenom=?, num_licence=?, email=?,
                           email_secondaire=?, phone=?, tarif=?, saison=? WHERE id=?""",
                        values + (adherent_id,),
                    )
                    report["updated"] += 1
                else:
                    cur.execute(
                        """INSERT INTO adherents (id, nom, prenom, num_licence, email,
                           email_secondaire, phone, tarif, saison)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (adherent_id,) + values,
                    )
                    report["imported"] += 1
            # Miroir des groupes de créneaux (delete + insert : reflet du planning)
            cur.execute("DELETE FROM planning_groups")
            cur.executemany(
                "INSERT INTO planning_groups (groupe, tarif) VALUES (?, ?)",
                planning_pairs,
            )
            conn.commit()
        except Exception as e:
            report["errors"].append(f"Écriture dans database_Competition.db : {e}")
        finally:
            conn.close()
        return report

    @classmethod
    def list_planning_groups(cls) -> dict:
        """{tarif normalisé -> groupe de créneau} depuis le miroir local (page web)."""
        cls.setup_database()
        conn = cls.get_connection()
        try:
            rows = conn.execute("SELECT groupe, tarif FROM planning_groups").fetchall()
        finally:
            conn.close()
        from domain.utils import normalize_string
        return {normalize_string(r["tarif"]): r["groupe"] for r in rows if r["groupe"]}

    # ------------------------------------------------------------------
    # Lecture des adhérents (instantané local)
    # ------------------------------------------------------------------
    @classmethod
    def list_adherents(cls, search: str = "", competition_only: bool = False) -> list:
        """Liste les adhérents de l'instantané (recherche insensible aux accents).

        competition_only=True restreint au groupe « Compétition » (tarif contenant
        'compétition', comparaison normalisée) : les 20 compétiteurs par défaut.
        """
        cls.setup_database()
        conn = cls.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM adherents ORDER BY nom COLLATE NOCASE, prenom COLLATE NOCASE"
            ).fetchall()
        finally:
            conn.close()

        from domain.utils import normalize_string
        q = normalize_string(search) if search else ""
        result = []
        for r in rows:
            d = dict(r)
            if competition_only and "competition" not in normalize_string(d.get("tarif") or ""):
                continue
            if q:
                haystack = normalize_string(
                    f"{d.get('nom')} {d.get('prenom')} {d.get('num_licence')} {d.get('tarif')}"
                )
                if q not in haystack:
                    continue
            result.append(d)
        return result

    @classmethod
    def count_adherents(cls) -> int:
        cls.setup_database()
        conn = cls.get_connection()
        try:
            return conn.execute("SELECT COUNT(*) AS c FROM adherents").fetchone()["c"]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # CRUD Compétitions
    # ------------------------------------------------------------------
    @classmethod
    def list_competitions(cls) -> list:
        cls.setup_database()
        conn = cls.get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM competitions ORDER BY date_competition DESC, id DESC"
            ).fetchall()
        finally:
            conn.close()
        return [Competition.from_row(dict(r)) for r in rows]

    @classmethod
    def get_competition(cls, competition_id: int):
        cls.setup_database()
        conn = cls.get_connection()
        try:
            r = conn.execute(
                "SELECT * FROM competitions WHERE id = ?", (competition_id,)
            ).fetchone()
        finally:
            conn.close()
        return Competition.from_row(dict(r)) if r else None

    @classmethod
    def save_competition(cls, comp: Competition) -> int:
        """Insère ou met à jour une compétition ; retourne son identifiant."""
        cls.setup_database()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            if comp.id:
                cur.execute(
                    """UPDATE competitions SET id_ffme=?, nom=?, date_competition=?, prix=?,
                       statut=?, helloasso_ref=?, updated_at=? WHERE id=?""",
                    (comp.id_ffme, comp.nom, comp.date_competition, comp.prix,
                     comp.statut, comp.helloasso_ref, now, comp.id),
                )
                comp_id = comp.id
            else:
                cur.execute(
                    """INSERT INTO competitions (id_ffme, nom, date_competition, prix,
                       statut, helloasso_ref, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (comp.id_ffme, comp.nom, comp.date_competition, comp.prix,
                     comp.statut, comp.helloasso_ref, now, now),
                )
                comp_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        return comp_id

    @classmethod
    def set_competition_status(cls, competition_id: int, statut: str) -> bool:
        cls.setup_database()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE competitions SET statut=?, updated_at=? WHERE id=?",
                (statut, now, competition_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    @classmethod
    def delete_competition(cls, competition_id: int) -> bool:
        cls.setup_database()
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM competitions WHERE id=?", (competition_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    @classmethod
    def list_participants(cls, competition_id: int, selected_only: bool = False) -> list:
        cls.setup_database()
        sql = (
            """SELECT p.*, a.nom, a.prenom, a.num_licence, a.email, a.tarif
               FROM participants p
               JOIN adherents a ON a.id = p.adherent_id
               WHERE p.competition_id = ?"""
        )
        if selected_only:
            sql += " AND p.selectionne = 1"
        sql += " ORDER BY a.nom COLLATE NOCASE, a.prenom COLLATE NOCASE"
        conn = cls.get_connection()
        try:
            rows = conn.execute(sql, (competition_id,)).fetchall()
        finally:
            conn.close()
        return [Participant.from_row(dict(r)) for r in rows]

    @classmethod
    def add_participant(cls, competition_id: int, adherent_id: int,
                        selectionne: bool = True) -> int:
        """Ajoute un adhérent à une compétition (idempotent)."""
        cls.setup_database()
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            existing = cur.execute(
                "SELECT id FROM participants WHERE competition_id=? AND adherent_id=?",
                (competition_id, adherent_id),
            ).fetchone()
            if existing:
                return existing["id"]
            cur.execute(
                """INSERT INTO participants (competition_id, adherent_id, selectionne,
                   statut_paiement) VALUES (?,?,?,?)""",
                (competition_id, adherent_id, 1 if selectionne else 0, PAIEMENT_NON_INVITE),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    @classmethod
    def remove_participant(cls, competition_id: int, adherent_id: int) -> bool:
        cls.setup_database()
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM participants WHERE competition_id=? AND adherent_id=?",
                (competition_id, adherent_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    @classmethod
    def set_selection(cls, competition_id: int, adherent_id: int, selectionne: bool) -> bool:
        """Bascule Oui/Non sur la participation (crée la ligne si absente)."""
        cls.setup_database()
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT id, statut_paiement FROM participants WHERE competition_id=? AND adherent_id=?",
                (competition_id, adherent_id),
            ).fetchone()
            if row:
                cur.execute("UPDATE participants SET selectionne=? WHERE id=?",
                            (1 if selectionne else 0, row["id"]))
            else:
                cur.execute(
                    """INSERT INTO participants (competition_id, adherent_id, selectionne,
                       statut_paiement) VALUES (?,?,?,?)""",
                    (competition_id, adherent_id, 1 if selectionne else 0, PAIEMENT_NON_INVITE),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    @classmethod
    def set_payment_status(cls, competition_id: int, adherent_id: int, statut_paiement: str) -> bool:
        cls.setup_database()
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE participants SET statut_paiement=? WHERE competition_id=? AND adherent_id=?""",
                (statut_paiement, competition_id, adherent_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    @classmethod
    def apply_helloasso_payment(cls, competition_id: int, adherent_id: int,
                                montant_paye: float, date_synchro: str = "",
                                order_ref: str = "") -> bool:
        """Marque un participant comme payé après rapprochement HelloAsso."""
        cls.setup_database()
        date_val = date_synchro or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """UPDATE participants SET statut_paiement='paye', montant_paye=?,
                   date_synchro_helloasso=?, commande_helloasso=?
                   WHERE competition_id=? AND adherent_id=?""",
                (montant_paye, date_val, str(order_ref or ""), competition_id, adherent_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    @classmethod
    def load_competition_group_into(cls, competition_id: int) -> int:
        """Pré-remplit la liste des participants avec le groupe « Compétition »."""
        count = 0
        for a in cls.list_adherents(competition_only=True):
            cls.add_participant(competition_id, a["id"], selectionne=True)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Bilan de fin d'année (tableau croisé élèves × compétitions)
    # ------------------------------------------------------------------
    @staticmethod
    def season_of_date(date_iso: str) -> str:
        """Déduit la saison sportive (septembre → août) d'une date ISO."""
        raw = str(date_iso or "").strip()[:10]
        try:
            y, m = int(raw[:4]), int(raw[5:7])
        except (ValueError, IndexError):
            return ""
        start = y if m >= 8 else y - 1
        return f"{start}-{start + 1}"

    @classmethod
    def get_bilan(cls, season: str = "") -> dict:
        """Données du tableau croisé : lignes = élèves, colonnes = compétitions."""
        cls.setup_database()
        conn = cls.get_connection()
        try:
            comps = [Competition.from_row(dict(r)) for r in conn.execute(
                "SELECT * FROM competitions ORDER BY date_competition ASC, id ASC"
            ).fetchall()]
            rows = [dict(r) for r in conn.execute(
                """SELECT p.adherent_id, p.statut_paiement, p.selectionne,
                          c.id AS competition_id, c.date_competition,
                          a.nom, a.prenom, a.num_licence, a.tarif
                   FROM participants p
                   JOIN competitions c ON c.id = p.competition_id
                   JOIN adherents a ON a.id = p.adherent_id
                   WHERE p.selectionne = 1
                   ORDER BY a.nom COLLATE NOCASE, a.prenom COLLATE NOCASE"""
            ).fetchall()]
        finally:
            conn.close()

        if season:
            comps = [c for c in comps if cls.season_of_date(c.date_competition) == season]
            comp_ids = {c.id for c in comps}
            rows = [r for r in rows if r["competition_id"] in comp_ids]

        participants_map = {}
        students = {}
        for r in rows:
            key = r["adherent_id"]
            students.setdefault(key, {
                "nom": r["nom"], "prenom": r["prenom"],
                "num_licence": r["num_licence"], "tarif": r["tarif"],
            })
            participants_map[(key, r["competition_id"])] = r["statut_paiement"]

        seasons = sorted({cls.season_of_date(c.date_competition) for c in comps if c.date_competition}, reverse=True)
        return {"competitions": comps, "students": students,
                "participations": participants_map, "seasons": seasons}

    # ------------------------------------------------------------------
    # Paramètres applicatifs (mémorisation des campagnes HelloAsso, etc.)
    # ------------------------------------------------------------------
    @classmethod
    def get_app_setting(cls, key: str, default: str = "") -> str:
        cls.setup_database()
        conn = cls.get_connection()
        try:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
        return row["value"] if row and row["value"] is not None else default

    @classmethod
    def save_app_setting(cls, key: str, value: str) -> bool:
        cls.setup_database()
        conn = cls.get_connection()
        try:
            conn.execute(
                """INSERT INTO app_settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (key, value),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Miroir HelloAsso (campagne annuelle) + liens article -> (compétition, adhérent)
    # ------------------------------------------------------------------
    @classmethod
    def sync_helloasso_mirror(cls, summarized: list, raw_items: list,
                              campagne_slug: str) -> int:
        """Upsert du miroir : la copie locale remplace ce que dit HelloAsso.

        `summarized` (projection) et `raw_items` (réponse brute) sont alignés 1:1.
        Retourne le nombre d'articles écrits."""
        import json
        cls.setup_database()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = cls.get_connection()
        written = 0
        try:
            cur = conn.cursor()
            for s, raw in zip(summarized or [], raw_items or [], strict=False):
                id_item = s.get("id_item")
                if id_item is None:
                    continue
                payeur = str(s.get("payeur") or "")
                nom, _, prenom = payeur.partition(" ")
                cur.execute(
                    """INSERT INTO helloasso_items (id_item, order_id, payer_nom, payer_prenom,
                           montant, etat, date_item, licence_saisie, competition_saisie,
                           campagne_slug, raw_json, synced_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id_item) DO UPDATE SET
                           order_id=excluded.order_id, payer_nom=excluded.payer_nom,
                           payer_prenom=excluded.payer_prenom, montant=excluded.montant,
                           etat=excluded.etat, date_item=excluded.date_item,
                           licence_saisie=excluded.licence_saisie,
                           competition_saisie=excluded.competition_saisie,
                           campagne_slug=excluded.campagne_slug, raw_json=excluded.raw_json,
                           synced_at=excluded.synced_at""",
                    (id_item, s.get("commande") or None, nom.strip(), prenom.strip(),
                     float(s.get("montant") or 0.0), str(s.get("etat") or ""),
                     str(s.get("date_item") or ""), str(s.get("licence") or ""),
                     str(s.get("competition") or ""), str(campagne_slug or ""),
                     json.dumps(raw, ensure_ascii=False, default=str), now),
                )
                written += 1
            conn.commit()
        finally:
            conn.close()
        return written

    @classmethod
    def list_helloasso_links(cls) -> dict:
        """{id_item: {"competition_id", "adherent_id", "source"}}."""
        cls.setup_database()
        conn = cls.get_connection()
        try:
            rows = conn.execute(
                "SELECT id_item, competition_id, adherent_id, source FROM item_links"
            ).fetchall()
        finally:
            conn.close()
        return {r["id_item"]: {"competition_id": r["competition_id"],
                               "adherent_id": r["adherent_id"],
                               "source": r["source"]} for r in rows}

    @classmethod
    def set_item_link(cls, id_item: int, competition_id, adherent_id,
                      source: str = "manuel") -> bool:
        """Crée / met à jour le lien d'un article (correction manuelle)."""
        cls.setup_database()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = cls.get_connection()
        try:
            conn.execute(
                """INSERT INTO item_links (id_item, competition_id, adherent_id, source, updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(id_item) DO UPDATE SET competition_id=excluded.competition_id,
                       adherent_id=excluded.adherent_id, source=excluded.source,
                       updated_at=excluded.updated_at""",
                (id_item, competition_id, adherent_id, source, now),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    @classmethod
    def replace_auto_links(cls, links: dict) -> int:
        """Remplace tous les liens 'auto' par le calcul courant ; les liens
        'manuel' sont intacts. `links` : retour de auto_link_items()."""
        cls.setup_database()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = cls.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM item_links WHERE source != 'manuel'")
            n = 0
            for id_item, link in (links or {}).items():
                cur.execute(
                    """INSERT OR REPLACE INTO item_links
                       (id_item, competition_id, adherent_id, source, updated_at)
                       VALUES (?,?,?,?,?)""",
                    (id_item, link.get("competition_id"), link.get("adherent_id"),
                     "auto", now),
                )
                n += 1
            conn.commit()
        finally:
            conn.close()
        return n

    @classmethod
    def list_mirror_items(cls) -> list:
        """Miroir + rattachements, prêt pour l'affichage."""
        cls.setup_database()
        conn = cls.get_connection()
        try:
            rows = conn.execute(
                """SELECT h.*, l.competition_id, l.adherent_id, l.source,
                          c.nom AS competition_nom, a.nom AS adherent_nom,
                          a.prenom AS adherent_prenom
                   FROM helloasso_items h
                   LEFT JOIN item_links l ON l.id_item = h.id_item
                   LEFT JOIN competitions c ON c.id = l.competition_id
                   LEFT JOIN adherents a ON a.id = l.adherent_id
                   ORDER BY h.date_item DESC, h.id_item DESC"""
            ).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    @classmethod
    def list_unlinked_items(cls) -> list:
        """Articles payés sans rattachement complet (compétition ou adhérent manquant),
        au format des lignes de correction manuelle (pré-sélection par licence)."""
        cls.setup_database()
        from domain.competition_matching import STATUTS_PAYES
        conn = cls.get_connection()
        try:
            rows = conn.execute(
                """SELECT h.*, l.competition_id, l.adherent_id
                   FROM helloasso_items h
                   LEFT JOIN item_links l ON l.id_item = h.id_item
                   WHERE lower(h.etat) IN (?, ?, ?)
                     AND (l.id_item IS NULL OR l.competition_id IS NULL OR l.adherent_id IS NULL)
                   ORDER BY h.payer_nom COLLATE NOCASE, h.id_item""",
                tuple(STATUTS_PAYES),
            ).fetchall()
            adherents = {a["id"]: a for a in cls.list_adherents()}
        finally:
            conn.close()

        import re
        result = []
        for r in rows:
            lic = re.sub(r"\D", "", str(r["licence_saisie"] or ""))
            preselect = r["adherent_id"]
            if preselect is None and lic:
                preselect = next((aid for aid, a in adherents.items()
                                  if re.sub(r"\D", "", str(a.get("num_licence") or "")) == lic), None)
            payer = f"{r['payer_nom']} {r['payer_prenom']}".strip()
            result.append({
                "id_item": r["id_item"],
                "payer": payer or "Inconnu",
                "montant": float(r["montant"] or 0.0),
                "order_ref": str(r["order_id"] or ""),
                "licence": str(r["licence_saisie"] or ""),
                "valeur_champ": str(r["competition_saisie"] or ""),
                "adherent_id": preselect,
                "participant": "",
            })
        return result

    @classmethod
    def apply_links_to_participants(cls) -> int:
        """Reporte les liens valides sur les participants : rattache l'adhérent à la
        compétition (si besoin) et marque « Payé » avec le montant cumulé des
        articles Validated liés. Retourne le nombre de (compétition, adhérent) mis à jour."""
        cls.setup_database()
        from domain.competition_matching import STATUTS_PAYES
        conn = cls.get_connection()
        try:
            rows = conn.execute(
                """SELECT l.competition_id, l.adherent_id, h.montant, h.order_id
                   FROM item_links l JOIN helloasso_items h ON h.id_item = l.id_item
                   WHERE l.competition_id IS NOT NULL AND l.adherent_id IS NOT NULL
                     AND lower(h.etat) IN (?, ?, ?)""",
                tuple(STATUTS_PAYES),
            ).fetchall()
        finally:
            conn.close()

        groupes = {}
        for r in rows:
            key = (r["competition_id"], r["adherent_id"])
            montant, orders = groupes.get(key, (0.0, []))
            groupes[key] = (montant + float(r["montant"] or 0.0),
                            orders + [str(r["order_id"] or "")])

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        applied = 0
        for (comp_id, adherent_id), (montant, orders) in groupes.items():
            cls.add_participant(comp_id, adherent_id, selectionne=True)
            if cls.apply_helloasso_payment(comp_id, adherent_id, round(montant, 2), now,
                                           order_ref=", ".join(o for o in orders if o)):
                applied += 1
        return applied
