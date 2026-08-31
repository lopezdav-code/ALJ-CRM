"""
Migration du schéma legacy (adherents / adherents_seasons, user_version=1)
vers le schéma cible v2 : users / orders / purchases / purchase_options.

Principes :
- Non destructif : les tables legacy ne sont jamais modifiées ni supprimées.
- Idempotent : si user_version >= 2, la migration est déjà appliquée (simple vérification).
- Atomique : tout est exécuté dans une transaction, rollback si les comptages de
  vérification ne correspondent pas aux données legacy.
- Récupération des payeurs/manquants (moyen de paiement, code promo, commentaires)
  depuis l'archive Excel HelloAsso (import/helloAsso/export-adhesion-*.xlsx).

Usage :
    python src/migrate_schema_v2.py [chemin_database.db] [--skip-excel]
"""
import os
import sys
import argparse
import datetime
import sqlite3

_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from paths import ROOT_DIR  # noqa: E402
from domain.utils import normalize_name  # noqa: E402
from infrastructure.sqlite_repository import SqliteRepository  # noqa: E402

SCHEMA_TARGET_VERSION = 2

SEASON_ACTIVE = "2026-2027"

STATUS_NORMALIZATION = {
    "processed": "Traité",
    "validated": "Validé",
    "validé": "Validé",
    "valide": "Validé",
    "terminé": "Terminé",
    "termine": "Terminé",
    "annulé": "Annulé",
    "annule": "Annulé",
    "canceled": "Annulé",
    "en cours": "En cours",
}

STATUS_PRIORITY = {
    "processed": 10, "traité": 10, "traite": 10,
    "validated": 9, "validé": 8, "valide": 8,
    "terminé": 7, "termine": 7,
    "en cours": 5,
    "canceled": 1, "annulé": 1, "annule": 1,
}

# (nom d'option cible, colonne has legacy, colonne montant legacy)
OPTION_PAIRS = [
    ("Assurance Base", "opt_Assurance Base", "opt_Montant Assurance Base"),
    ("Assurance Base +", "opt_Assurance Base +", "opt_Montant Assurance Base +"),
    ("Assurance Base ++", "opt_Assurance Base ++", "opt_Montant Assurance Base ++"),
    ("Assurance Option ski de piste", "opt_Assurance Option ski de piste", "opt_Montant Assurance Option ski de piste"),
    ("Assurance Option VTT", "opt_Assurance Option VTT", "opt_Montant Assurance Option VTT"),
    ("Assurance Option Trail", "opt_Assurance Option Trail", "opt_Montant Assurance Option Trail"),
]

# colonnes legacy adherents -> colonnes users
USER_FIELD_MAP = {
    "user_lastName": "last_name",
    "user_firstName": "first_name",
    "champ_Sexe": "gender",
    "champ_Nationalité": "nationality",
    "champ_Adresse : numéro et nom de rue": "address",
    "champ_Code postal": "zip_code",
    "champ_Ville": "city",
    "champ_Pays": "country",
    "champ_Téléphone ": "phone",
    "champ_Adresse mail pour la réception des informations du club": "email_primary",
    "champ_Deuxième adresse mail pour la réception des informations du club": "email_secondary",
    "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule": "emergency1_name",
    "champ_Personne à prévenir en cas d'urgence - Téléphone": "emergency1_phone",
    "champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)": "emergency2_name",
    "champ_Parent 2 - Numéro de téléphone portable": "emergency2_phone",
    "champ_Numéro de Licence FFME (6 chiffres)": "licence_ffme",
    "badge_rouge": "badge_rouge",
    "autonomie_bloc": "autonomie_bloc",
    "raw_passports": "raw_passports",
    "raw_diplomas": "raw_diplomas",
    "parental_auth_autonomous": "parental_auth_autonomous",
    "parental_auth_family": "parental_auth_family",
}

# Colonnes à libellés très longs (photo / questionnaire de santé) : résolues dynamiquement
# car leur texte exact dépend de CORRECTIVE_MAP.
DYNAMIC_USER_FIELDS = [
    ("champ_En cas de prise de vue", "photo_auth"),
    ("champ_Je m'engage", "health_commitment"),
]

DOB_COLUMN = "champ_Date de naissance de l'adhérent"


def build_user_field_map(cur):
    """Construit la map legacy->users en résolvant dynamiquement les colonnes à longs libellés."""
    cols = [r["name"] for r in cur.execute("PRAGMA table_info(adherents)").fetchall()]
    field_map = {}
    for src, dst in USER_FIELD_MAP.items():
        if src in cols:
            field_map[src] = dst
        else:
            raise KeyError(f"Colonne legacy absente de la table adherents : {src!r}")
    for prefix, dst in DYNAMIC_USER_FIELDS:
        matches = [c for c in cols if c.startswith(prefix)]
        if matches:
            field_map[matches[0]] = dst
        else:
            raise KeyError(f"Aucune colonne legacy commençant par {prefix!r}")
    return field_map


def parse_iso_date(val):
    """Normalise une date legacy ('20/08/2012', '2012-08-20T00:00:00', ...) en ISO '2012-08-20'."""
    s = str(val or "").strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%y"):
        try:
            dt = datetime.datetime.strptime(s[:19] if "T" in s else s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def normalize_status(status):
    return STATUS_NORMALIZATION.get(str(status or "").strip().lower(), str(status or "").strip())


def status_score(status):
    return STATUS_PRIORITY.get(str(status or "").strip().lower(), 0)


def is_true(val):
    return str(val or "").strip().lower() in ("oui", "true", "vrai", "1", "yes")


def create_target_schema(cur):
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        last_name TEXT NOT NULL,
        first_name TEXT NOT NULL,
        last_name_key TEXT NOT NULL,
        first_name_key TEXT NOT NULL,
        birth_date TEXT,
        birth_date_raw TEXT,
        gender TEXT, nationality TEXT,
        address TEXT, zip_code TEXT, city TEXT, country TEXT,
        phone TEXT,
        email_primary TEXT, email_secondary TEXT,
        emergency1_name TEXT, emergency1_phone TEXT,
        emergency2_name TEXT, emergency2_phone TEXT,
        licence_ffme TEXT,
        photo_auth TEXT, health_commitment TEXT,
        badge_rouge TEXT DEFAULT 'Non',
        autonomie_bloc TEXT DEFAULT 'Non',
        raw_passports TEXT DEFAULT '',
        raw_diplomas TEXT DEFAULT '',
        parental_auth_autonomous TEXT DEFAULT 'Non',
        parental_auth_family TEXT DEFAULT 'Non',
        legacy_adherent_id INTEGER UNIQUE,
        created_at TEXT, updated_at TEXT,
        UNIQUE(last_name_key, first_name_key, birth_date)
    );
    CREATE INDEX IF NOT EXISTS idx_users_names ON users(last_name_key, first_name_key);

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_ref TEXT UNIQUE NOT NULL,
        order_date TEXT,
        status TEXT,
        status_normalized TEXT,
        payment_method TEXT,
        payer_last_name TEXT, payer_first_name TEXT, payer_email TEXT,
        promo_code TEXT, promo_amount REAL,
        comment TEXT,
        season_id INTEGER REFERENCES seasons(id),
        created_at TEXT, updated_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_orders_season ON orders(season_id);

    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        tarif_name TEXT, amount REAL,
        status TEXT, status_normalized TEXT,
        is_tribe TEXT DEFAULT 'Non',
        email_sent_date TEXT,
        is_modified TEXT DEFAULT 'Non',
        commentaires_correctif TEXT DEFAULT '',
        legacy_adherent_id INTEGER,
        legacy_season_id INTEGER,
        created_at TEXT, updated_at TEXT,
        UNIQUE(order_id, user_id)
    );
    CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id);
    CREATE INDEX IF NOT EXISTS idx_purchases_order ON purchases(order_id);

    CREATE TABLE IF NOT EXISTS purchase_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
        option_name TEXT NOT NULL,
        amount REAL DEFAULT 0.0,
        UNIQUE(purchase_id, option_name)
    );
    """)


def upsert_user(cur, adherent_row, now_iso, field_map):
    """Crée ou complète un user à partir d'une ligne legacy. Retourne (user_id, created)."""
    last = str(adherent_row["user_lastName"] or "").strip()
    first = str(adherent_row["user_firstName"] or "").strip()
    dob_raw = str(adherent_row[DOB_COLUMN] or "").strip()
    dob_iso = parse_iso_date(dob_raw)
    k_last = normalize_name(last).upper()
    k_first = normalize_name(first).lower()

    cur.execute(
        "SELECT id FROM users WHERE last_name_key=? AND first_name_key=? AND birth_date=?",
        (k_last, k_first, dob_iso),
    )
    found = cur.fetchone()
    if found:
        user_id = found["id"]
        # Compléter les champs vides (ne jamais écraser une valeur existante)
        for src_col, dst_col in field_map.items():
            new_val = str(adherent_row[src_col] or "").strip()
            if new_val:
                cur.execute(
                    f'UPDATE users SET "{dst_col}" = ?, updated_at = ? '
                    f'WHERE id = ? AND (("{dst_col}" IS NULL) OR (TRIM("{dst_col}") = ""))',
                    (new_val, now_iso, user_id),
                )
        return user_id, False

    values = {dst: str(adherent_row[src] or "").strip() for src, dst in field_map.items()}
    values["last_name_key"] = k_last
    values["first_name_key"] = k_first
    values["birth_date"] = dob_iso
    values["birth_date_raw"] = dob_raw
    values["legacy_adherent_id"] = adherent_row["adherent_id"]
    cols = list(values.keys())
    try:
        cur.execute(
            f'INSERT INTO users ({", ".join(cols)}) VALUES ({", ".join("?" for _ in cols)})',
            [values[c] for c in cols],
        )
        user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        # Naissance absente sur un homonyme : rattacher au user existant
        cur.execute(
            "SELECT id FROM users WHERE last_name_key=? AND first_name_key=? AND birth_date=?",
            (k_last, k_first, dob_iso),
        )
        user_id = cur.fetchone()["id"]
        return user_id, False
    cur.execute("UPDATE users SET created_at=?, updated_at=? WHERE id=?", (now_iso, now_iso, user_id))
    return user_id, True


def upsert_order(cur, order_ref, order_date, status, payer_row, season_id, now_iso):
    """Crée ou met à jour la commande. Retourne order_id."""
    cur.execute("SELECT id, status, payer_last_name, payer_first_name, payer_email, season_id "
                "FROM orders WHERE order_ref=?", (order_ref,))
    found = cur.fetchone()
    if found:
        order_id = found["id"]
        # Conserver le statut le plus « actif » (priorité métier)
        if status_score(status) > status_score(found["status"]):
            cur.execute("UPDATE orders SET status=?, status_normalized=?, updated_at=? WHERE id=?",
                        (status, normalize_status(status), now_iso, order_id))
        # Compléter le payeur s'il manque
        for col, val in (("payer_last_name", payer_row["payer_lastName"]),
                         ("payer_first_name", payer_row["payer_firstName"]),
                         ("payer_email", payer_row["payer_email"])):
            v = str(val or "").strip()
            if v and not str(found[col] or "").strip():
                cur.execute(f"UPDATE orders SET {col}=?, updated_at=? WHERE id=?", (v, now_iso, order_id))
        if season_id and not found["season_id"]:
            cur.execute("UPDATE orders SET season_id=? WHERE id=?", (season_id, order_id))
        return order_id

    cur.execute("""
        INSERT INTO orders (order_ref, order_date, status, status_normalized,
                            payer_last_name, payer_first_name, payer_email,
                            season_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (order_ref, order_date, status, normalize_status(status),
          str(payer_row["payer_lastName"] or "").strip(),
          str(payer_row["payer_firstName"] or "").strip(),
          str(payer_row["payer_email"] or "").strip(),
          season_id, now_iso, now_iso))
    return cur.lastrowid


def migrate(skip_excel=False):
    db_path = SqliteRepository.get_db_path()
    print(f"🔄 [MIGRATION V2] Base cible : {db_path}")

    SqliteRepository.setup_database()
    conn = SqliteRepository.get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("PRAGMA user_version")
    version = cur.fetchone()[0]
    if version >= SCHEMA_TARGET_VERSION:
        counts = {
            "users": cur.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "orders": cur.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "purchases": cur.execute("SELECT COUNT(*) FROM purchases").fetchone()[0],
        }
        print(f"ℹ️ [MIGRATION V2] Base déjà migrée (user_version={version}) : {counts}")
        conn.close()
        return True

    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    seasons = {r["name"]: r["id"] for r in cur.execute("SELECT id, name FROM seasons")}
    active_season_id = seasons.get(SEASON_ACTIVE)

    try:
        create_target_schema(cur)
        field_map = build_user_field_map(cur)

        rows = cur.execute("""
            SELECT las.adherent_id, las.season_id, las.order_ref, las.order_date,
                   las.tarif_name, las.amount, las.status, las.is_modified,
                   las.commentaires_correctif, las.email_sent_date,
                   a.*
            FROM adherents_seasons las
            JOIN adherents a ON a.id = las.adherent_id
            ORDER BY las.adherent_id, las.season_id
        """).fetchall()
        print(f"📦 [MIGRATION V2] {len(rows)} inscriptions legacy à migrer...")

        stats = {"users_created": 0, "users_merged": 0, "purchases": 0,
                 "options": 0, "anomalies": []}

        # Un adhérent possède-t-il un achat sur la saison active ? (pour rattacher les assurances)
        has_active_season = {}
        for r in rows:
            has_active_season[r["adherent_id"]] = (
                has_active_season.get(r["adherent_id"], False) or r["season_id"] == active_season_id
            )
        options_attached = set()

        for r in rows:
            order_ref = str(r["order_ref"] or "").strip()
            if not order_ref:
                stats["anomalies"].append(f"Inscription sans order_ref (adherent_id={r['adherent_id']})")
                continue

            user_id, created = upsert_user(cur, r, now_iso, field_map)
            if created:
                stats["users_created"] += 1
            else:
                stats["users_merged"] += 1

            order_id = upsert_order(cur, order_ref, r["order_date"], r["status"], r, r["season_id"], now_iso)

            try:
                cur.execute("""
                    INSERT INTO purchases (order_id, user_id, tarif_name, amount, status,
                                           status_normalized, is_tribe, email_sent_date,
                                           is_modified, commentaires_correctif,
                                           legacy_adherent_id, legacy_season_id,
                                           created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (order_id, user_id, r["tarif_name"], r["amount"], r["status"],
                      normalize_status(r["status"]),
                      "Oui" if is_true(r["champ_Famille : nous sommes une tribu de 3 ou plus inscrits ce qui permet un code de réduction : FAMILLE"]) else "Non",
                      r["email_sent_date"], r["is_modified"], r["commentaires_correctif"],
                      r["adherent_id"], r["season_id"], now_iso, now_iso))
                purchase_id = cur.lastrowid
                stats["purchases"] += 1
            except sqlite3.IntegrityError as e:
                stats["anomalies"].append(f"Achat dupliqué ignoré ({r['user_lastName']} {order_ref}) : {e}")
                continue

            # Options d'assurance : rattachées à l'achat de la saison active
            # (fallback : premier achat rencontré pour les adhérents sans saison active)
            aid = r["adherent_id"]
            is_porteur = (r["season_id"] == active_season_id) or (
                aid not in options_attached and not has_active_season.get(aid, False)
            )
            if is_porteur:
                for opt_name, col_has, col_amount in OPTION_PAIRS:
                    if is_true(r[col_has]):
                        try:
                            cur.execute(
                                "INSERT INTO purchase_options (purchase_id, option_name, amount) VALUES (?, ?, ?)",
                                (purchase_id, opt_name, float(r[col_amount] or 0.0)),
                            )
                            stats["options"] += 1
                        except sqlite3.IntegrityError:
                            pass
                options_attached.add(aid)

        # ---- Récupération payeurs / moyen de paiement / promo depuis l'archive Excel
        excel_stats = {"orders_found": 0, "payer_filled": 0, "payment_method": 0,
                       "promo": 0, "comment": 0}
        if not skip_excel:
            excel_stats = recover_from_excel(cur)

        # ---- Vérifications avant validation
        nb_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        nb_orders = cur.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        nb_purchases = cur.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
        nb_options = cur.execute("SELECT COUNT(*) FROM purchase_options").fetchone()[0]
        sum_new = cur.execute("SELECT ROUND(SUM(amount),2) FROM purchases").fetchone()[0] or 0.0
        sum_legacy = cur.execute("SELECT ROUND(SUM(amount),2) FROM adherents_seasons").fetchone()[0] or 0.0

        expected_users = cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT UPPER(TRIM(user_lastName)) a, LOWER(TRIM(user_firstName)) b,
                       COUNT(*) n
                FROM adherents GROUP BY a, b HAVING n > 1
            )
        """).fetchone()[0]
        expected_orders = cur.execute(
            "SELECT COUNT(DISTINCT order_ref) FROM adherents_seasons WHERE TRIM(order_ref)<>''"
        ).fetchone()[0]
        expected_purchases = cur.execute("SELECT COUNT(*) FROM adherents_seasons").fetchone()[0]

        print("\n========== RAPPORT DE MIGRATION V2 ==========")
        print(f"  users              : {nb_users} (attendu ~{nb_users + expected_users} si {expected_users} doublon(s) fusionné(s))")
        print(f"  orders             : {nb_orders} (attendu {expected_orders})")
        print(f"  purchases          : {nb_purchases} (attendu {expected_purchases})")
        print(f"  purchase_options   : {nb_options}")
        print(f"  Somme montants     : {sum_new} (legacy {sum_legacy})")
        print(f"  users créés/fusionnés : {stats['users_created']} / {stats['users_merged']}")
        print(f"  Excel : {excel_stats}")
        if stats["anomalies"]:
            print(f"  ⚠️ Anomalies ({len(stats['anomalies'])}) :")
            for a in stats["anomalies"][:10]:
                print(f"     - {a}")

        ok = (
            nb_purchases == expected_purchases
            and nb_orders == expected_orders
            and abs(sum_new - sum_legacy) < 0.01
        )
        if not ok:
            conn.rollback()
            conn.close()
            print("\n❌ [MIGRATION V2] Écart détecté : ROLLBACK effectué, base inchangée.")
            return False

        cur.execute(f"PRAGMA user_version = {SCHEMA_TARGET_VERSION}")
        conn.commit()
        conn.close()
        print(f"\n✅ [MIGRATION V2] Migration validée et commitée (user_version={SCHEMA_TARGET_VERSION}).")
        return True

    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"\n❌ [MIGRATION V2] Erreur : {e} — ROLLBACK effectué.")
        raise


def recover_from_excel(cur):
    """Complète orders (payeur, moyen de paiement, promo, commentaire) depuis l'export HelloAsso."""
    import pandas as pd
    import unicodedata

    excel_path = None
    import_dir = os.path.join(ROOT_DIR, "import", "helloAsso")
    for root, _dirs, files in os.walk(import_dir):
        for f in files:
            if f.startswith("export-adhesion") and f.endswith(".xlsx"):
                excel_path = os.path.join(root, f)
    if not excel_path or not os.path.exists(excel_path):
        print("⚠️ [MIGRATION V2] Archive Excel HelloAsso introuvable : payeurs non récupérés.")
        return {"orders_found": 0, "payer_filled": 0, "payment_method": 0, "promo": 0, "comment": 0}

    def norm(s):
        s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
        return s.strip().lower()

    df = pd.read_excel(excel_path)
    df = df.fillna("")
    colmap = {norm(c): c for c in df.columns}

    def col(*names):
        for n in names:
            if n in colmap:
                return colmap[n]
        return None

    c_ref = col("reference commande")
    c_pnom = col("nom payeur")
    c_pprenom = col("prenom payeur")
    c_pemail = col("email payeur")
    c_paiement = col("moyen de paiement")
    c_promo = col("code promo")
    c_promo_amt = col("montant code promo")
    c_comment = col("commentaires (hors ligne)", "commentaires")

    stats = {"orders_found": 0, "payer_filled": 0, "payment_method": 0, "promo": 0, "comment": 0}
    seen = set()

    for _, row in df.iterrows():
        ref = str(row[c_ref] or "").strip() if c_ref else ""
        if not ref or ref in seen:
            continue
        seen.add(ref)
        cur.execute("SELECT id, payer_last_name, payer_first_name, payer_email FROM orders WHERE order_ref=?", (ref,))
        found = cur.fetchone()
        if not found:
            continue
        stats["orders_found"] += 1
        now_iso = datetime.datetime.now().isoformat(timespec="seconds")

        for col_db, col_x in (("payer_last_name", c_pnom), ("payer_first_name", c_pprenom), ("payer_email", c_pemail)):
            v = str(row[col_x] or "").strip() if col_x else ""
            if v and not str(found[col_db] or "").strip():
                cur.execute(f"UPDATE orders SET {col_db}=?, updated_at=? WHERE id=?", (v, now_iso, found["id"]))
                stats["payer_filled"] += 1

        for col_db, col_x, key in (("payment_method", c_paiement, "payment_method"),
                                   ("promo_code", c_promo, "promo"),
                                   ("comment", c_comment, "comment")):
            v = str(row[col_x] or "").strip() if col_x else ""
            if v:
                cur.execute(f"UPDATE orders SET {col_db}=? WHERE id=?", (v, found["id"]))
                stats[key] += 1

        if c_promo_amt:
            try:
                amt = float(str(row[c_promo_amt]).replace(",", ".") or 0)
                if amt:
                    cur.execute("UPDATE orders SET promo_amount=? WHERE id=?", (amt, found["id"]))
            except ValueError:
                pass

    print(f"📧 [MIGRATION V2] Récupération Excel : {os.path.basename(excel_path)}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Migration schéma BDD v2 (users/orders/purchases)")
    parser.add_argument("db_path", nargs="?", default=None, help="Chemin de database.db (défaut : base active)")
    parser.add_argument("--skip-excel", action="store_true", help="Ne pas lire l'archive Excel HelloAsso")
    args = parser.parse_args()

    if args.db_path:
        SqliteRepository.set_db_path(args.db_path)
    elif not os.path.exists(SqliteRepository.get_db_path()):
        print(f"❌ Base introuvable : {SqliteRepository.get_db_path()}")
        sys.exit(1)

    ok = migrate(skip_excel=args.skip_excel)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
