"""
Schéma cible v2 (users / orders / purchases / purchase_options) — module partagé.

Source unique de vérité pour :
- le DDL des tables v2 (migration et écritures applicatives),
- les normalisations (statuts, dates, textes legacy NULL/'' ),
- la table de priorité des statuts (centralisée, anciennement dupliquée dans
  sqlite_repository.py et create_excel.py),
- les upserts users / orders / purchases / purchase_options.

Importé par sqlite_repository (écritures miroir phase 3) et migrate_schema_v2.
Aucune dépendance à SqliteRepository pour éviter toute importation circulaire.
"""
import datetime
import sqlite3

from domain.utils import normalize_name

SCHEMA_TARGET_VERSION = 2
SEASON_ACTIVE = "2026-2027"

# Table de priorité des statuts — CENTRALISÉE (phase 3)
STATUS_PRIORITY = {
    "processed": 10,
    "traité": 10,
    "traite": 10,
    "validated": 9,
    "validé": 8,
    "valide": 8,
    "terminé": 7,
    "termine": 7,
    "en cours": 5,
    "canceled": 1,
    "annulé": 1,
    "annule": 1,
}

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

V2_DDL = """
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
"""

# Colonnes legacy adherents -> colonnes users (libellés courts certains)
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

# Colonnes à très longs libellés : résolues dynamiquement via PRAGMA table_info
DYNAMIC_USER_FIELDS = [
    ("champ_En cas de prise de vue", "photo_auth"),
    ("champ_Je m'engage", "health_commitment"),
]

DOB_COLUMN = "champ_Date de naissance de l'adhérent"

# (nom d'option cible, colonne has legacy, colonne montant legacy)
OPTION_PAIRS = [
    ("Assurance Base", "opt_Assurance Base", "opt_Montant Assurance Base"),
    ("Assurance Base +", "opt_Assurance Base +", "opt_Montant Assurance Base +"),
    ("Assurance Base ++", "opt_Assurance Base ++", "opt_Montant Assurance Base ++"),
    ("Assurance Option ski de piste", "opt_Assurance Option ski de piste", "opt_Montant Assurance Option ski de piste"),
    ("Assurance Option VTT", "opt_Assurance Option VTT", "opt_Montant Assurance Option VTT"),
    ("Assurance Option Trail", "opt_Assurance Option Trail", "opt_Montant Assurance Option Trail"),
]

# Clés IHM (update_member_in_db) -> noms d'options v2
IHM_TO_OPTIONS = {
    "opt_assurance_base": "Assurance Base",
    "opt_assurance_base_plus": "Assurance Base +",
    "opt_assurance_base_plus_plus": "Assurance Base ++",
    "opt_assurance_ski": "Assurance Option ski de piste",
    "opt_assurance_vtt": "Assurance Option VTT",
    "opt_assurance_trail": "Assurance Option Trail",
}

# Clés IHM -> colonnes users (miroir des correctifs manuels)
IHM_TO_USERS = {
    "user_last_name": "last_name",
    "user_first_name": "first_name",
    "primary_email": "email_primary",
    "secondary_email": "email_secondary",
    "phone": "phone",
    "city": "city",
    "emergency_contact_name_1": "emergency1_name",
    "emergency_contact_phone_1": "emergency1_phone",
    "licence_ffme": "licence_ffme",
    "photo_auth": "photo_auth",
    "health_q_auth": "health_commitment",
    "badge_rouge": "badge_rouge",
    "autonomie_bloc": "autonomie_bloc",
    "raw_passports": "raw_passports",
    "raw_diplomas": "raw_diplomas",
    "parental_auth_autonomous": "parental_auth_autonomous",
    "parental_auth_family": "parental_auth_family",
}


def clean_legacy_text(val):
    """
    Préserve la distinction NULL / chaîne vide du legacy : le générateur CSV historique
    applique str(None) ('None') sur les valeurs NULL — les restituer telles quelles
    garantit un export octet-pour-octet identique.
    """
    if val is None:
        return None
    return str(val).strip()


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


def purchase_priority_score(status, tarif_name, amount):
    """Score de priorité d'une inscription : statut + pénalité liste d'attente / montant nul."""
    base = status_score(status)
    tarif_lower = str(tarif_name or "").strip().lower()
    try:
        amt_val = float(amount) if amount else 0.0
    except (ValueError, TypeError):
        amt_val = 0.0
    if "attente" in tarif_lower or amt_val == 0.0:
        base -= 20
    return base


def is_true(val):
    return str(val or "").strip().lower() in ("oui", "true", "vrai", "1", "yes")


def _get(rec, key):
    """Accès tolérant : fonctionne avec les dict HelloAsso et les sqlite3.Row."""
    try:
        return rec[key]
    except (KeyError, IndexError):
        return None


def build_user_field_map(cur=None):
    """Map legacy->users (phase 1 : validation PRAGMA ; phase 5 : map statique, la table
    legacy pouvant ne plus exister)."""
    return dict(USER_FIELD_MAP)


def _dynamic_field_values(rec):
    """Résout sur l'enregistrement les champs à longs libellés (photo / questionnaire de santé),
    dont la clé exacte dépend du formulaire HelloAsso."""
    out = {}
    try:
        rec_keys = list(rec.keys())
    except Exception:
        rec_keys = []
    for prefix, dst in DYNAMIC_USER_FIELDS:
        for k in rec_keys:
            if k.startswith(prefix):
                out[dst] = clean_legacy_text(_get(rec, k))
                break
    return out


def ensure_v2_schema(cur):
    """Crée les tables v2 si absentes (idempotent)."""
    cur.executescript(V2_DDL)


def resolve_season_id(cur, season_name):
    cur.execute("SELECT id FROM seasons WHERE name=?", (season_name,))
    row = cur.fetchone()
    if row:
        return row["id"] if isinstance(row, sqlite3.Row) else row[0]
    cur.execute("INSERT INTO seasons (name, is_active) VALUES (?, 0)", (season_name,))
    return cur.lastrowid


def upsert_user_v2(cur, rec, now_iso, field_map):
    """Crée ou complète un user. rec = dict HelloAsso ou ligne legacy (adherents JOIN seasons).
    Retourne (user_id, created)."""
    last = str(_get(rec, "user_lastName") or "").strip()
    first = str(_get(rec, "user_firstName") or "").strip()
    dob_raw = str(_get(rec, DOB_COLUMN) or "").strip()
    dob_iso = parse_iso_date(dob_raw)
    k_last = normalize_name(last).upper()
    k_first = normalize_name(first).lower()

    cur.execute(
        "SELECT id FROM users WHERE last_name_key=? AND first_name_key=? AND birth_date=?",
        (k_last, k_first, dob_iso),
    )
    found = cur.fetchone()
    if found:
        user_id = found["id"] if isinstance(found, sqlite3.Row) else found[0]
        # Rattacher l'identifiant legacy si connu (fusion utilisateur migrée + sync)
        legacy_id = _get(rec, "adherent_id")
        if legacy_id is not None:
            cur.execute("UPDATE users SET legacy_adherent_id=? WHERE id=? AND legacy_adherent_id IS NULL",
                        (legacy_id, user_id))
        dyn = _dynamic_field_values(rec)
        for src_col, dst_col in field_map.items():
            new_val = clean_legacy_text(_get(rec, src_col))
            if new_val:
                cur.execute(
                    f'UPDATE users SET "{dst_col}" = ?, updated_at = ? '
                    f'WHERE id = ? AND (("{dst_col}" IS NULL) OR (TRIM("{dst_col}") = ""))',
                    (new_val, now_iso, user_id),
                )
        for dst_col, new_val in dyn.items():
            if new_val:
                cur.execute(
                    f'UPDATE users SET "{dst_col}" = ?, updated_at = ? '
                    f'WHERE id = ? AND (("{dst_col}" IS NULL) OR (TRIM("{dst_col}") = ""))',
                    (new_val, now_iso, user_id),
                )
        return user_id, False

    values = {dst: clean_legacy_text(_get(rec, src)) for src, dst in field_map.items()}
    values["last_name"] = last
    values["first_name"] = first
    values["last_name_key"] = k_last
    values["first_name_key"] = k_first
    values["birth_date"] = dob_iso
    values["birth_date_raw"] = dob_raw if dob_raw else None
    values.update(_dynamic_field_values(rec))
    legacy_id = _get(rec, "adherent_id")
    if legacy_id is not None:
        values["legacy_adherent_id"] = legacy_id
    cols = list(values.keys())
    try:
        cur.execute(
            f'INSERT INTO users ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
            f'VALUES ({", ".join("?" for _ in cols)})',
            [values[c] for c in cols],
        )
        user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        cur.execute(
            "SELECT id FROM users WHERE last_name_key=? AND first_name_key=? AND birth_date=?",
            (k_last, k_first, dob_iso),
        )
        row = cur.fetchone()
        user_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]
        return user_id, False
    cur.execute("UPDATE users SET created_at=?, updated_at=? WHERE id=?", (now_iso, now_iso, user_id))
    return user_id, True


def upsert_order_v2(cur, order_ref, order_date, status,
                    payer_last="", payer_first="", payer_email="",
                    season_id=None, now_iso=None):
    """Crée ou met à jour la commande (statut le plus actif conservé, payeur complété)."""
    cur.execute("SELECT id, status, payer_last_name, payer_first_name, payer_email, season_id "
                "FROM orders WHERE order_ref=?", (order_ref,))
    found = cur.fetchone()
    if found:
        order_id = found["id"] if isinstance(found, sqlite3.Row) else found[0]
        ex_status = found["status"] if isinstance(found, sqlite3.Row) else found[1]
        if status_score(status) > status_score(ex_status):
            cur.execute("UPDATE orders SET status=?, status_normalized=?, updated_at=? WHERE id=?",
                        (status, normalize_status(status), now_iso, order_id))
        cols = (("payer_last_name", payer_last), ("payer_first_name", payer_first), ("payer_email", payer_email))
        for i, (col, val) in enumerate(cols):
            v = str(val or "").strip()
            existing = found[col] if isinstance(found, sqlite3.Row) else found[2 + i]
            if v and not str(existing or "").strip():
                cur.execute(f"UPDATE orders SET {col}=?, updated_at=? WHERE id=?", (v, now_iso, order_id))
        if season_id and not (found["season_id"] if isinstance(found, sqlite3.Row) else found[5]):
            cur.execute("UPDATE orders SET season_id=? WHERE id=?", (season_id, order_id))
        return order_id

    cur.execute("""
        INSERT INTO orders (order_ref, order_date, status, status_normalized,
                            payer_last_name, payer_first_name, payer_email,
                            season_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (order_ref, str(order_date or ""), str(status or ""), normalize_status(status),
          str(payer_last or "").strip(), str(payer_first or "").strip(), str(payer_email or "").strip(),
          season_id, now_iso, now_iso))
    return cur.lastrowid


def _has_better_sibling_purchase(cur, user_id, order_id, score):
    """Vrai si une autre purchase du même user dans la même saison a un score de statut
    strictement supérieur. Reproduit la sémantique legacy : une inscription moins
    prioritaire (annulée / liste d'attente) ne doit jamais masquer une inscription active."""
    cur.execute("""
        SELECT p.status, p.tarif_name, p.amount
        FROM purchases p JOIN orders o ON o.id = p.order_id
        WHERE p.user_id = ? AND o.season_id = (SELECT season_id FROM orders WHERE id = ?)
          AND p.id != ?
    """, (user_id, order_id, order_id))
    for r in cur.fetchall():
        ex_s = r["status"] if isinstance(r, sqlite3.Row) else r[0]
        ex_t = r["tarif_name"] if isinstance(r, sqlite3.Row) else r[1]
        ex_a = r["amount"] if isinstance(r, sqlite3.Row) else r[2]
        if purchase_priority_score(ex_s, ex_t, ex_a) > score:
            return True
    return False


def insert_purchase_v2(cur, order_id, user_id, rec, now_iso,
                       legacy_adherent_id=None, legacy_season_id=None):
    """Insère ou met à jour l'achat avec la règle de priorité de statut centralisée.
    Retourne purchase_id, ou None si une inscription plus prioritaire existe déjà."""
    try:
        amt_val = float(_get(rec, "amount") or 0.0)
    except (ValueError, TypeError):
        amt_val = 0.0
    new_status = str(_get(rec, "status") or "Validé").strip()
    tarif = str(_get(rec, "tarif_name") or "")
    new_score = purchase_priority_score(new_status, tarif, amt_val)

    cur.execute("SELECT id, status, tarif_name, amount FROM purchases WHERE order_id=? AND user_id=?",
                (order_id, user_id))
    found = cur.fetchone()
    if found:
        ex_status = str(found["status"] or "").strip() if isinstance(found, sqlite3.Row) else str(found[1] or "")
        ex_tarif = str(found["tarif_name"] or "") if isinstance(found, sqlite3.Row) else str(found[2] or "")
        ex_amt = float(found["amount"] or 0.0) if isinstance(found, sqlite3.Row) else float(found[3] or 0.0)
        purchase_id = found["id"] if isinstance(found, sqlite3.Row) else found[0]
        if purchase_priority_score(ex_status, ex_tarif, ex_amt) > new_score:
            return None
        if _has_better_sibling_purchase(cur, user_id, order_id, new_score):
            return None
        cur.execute("""
            UPDATE purchases SET tarif_name=?, amount=?, status=?, status_normalized=?,
                                 is_modified=?, commentaires_correctif=?, email_sent_date=?, updated_at=?
            WHERE id=?
        """, (tarif, amt_val, new_status, normalize_status(new_status),
              _get(rec, "is_modified") or "Non", clean_legacy_text(_get(rec, "commentaires_correctif")) or "",
              _get(rec, "email_sent_date"), now_iso, purchase_id))
        return purchase_id

    if _has_better_sibling_purchase(cur, user_id, order_id, new_score):
        return None

    # Sémantique legacy d'écrasement : la nouvelle inscription plus prioritaire remplace
    # les inscriptions STRICTEMENT moins prioritaires du même user dans la même saison.
    cur.execute("""
        SELECT p.id, p.status, p.tarif_name, p.amount
        FROM purchases p JOIN orders o ON o.id = p.order_id
        WHERE p.user_id = ? AND o.season_id = (SELECT season_id FROM orders WHERE id = ?)
          AND p.id != ?
    """, (user_id, order_id, order_id))
    for r in cur.fetchall():
        sib_id = r["id"] if isinstance(r, sqlite3.Row) else r[0]
        sib_s = r["status"] if isinstance(r, sqlite3.Row) else r[1]
        sib_t = r["tarif_name"] if isinstance(r, sqlite3.Row) else r[2]
        sib_a = r["amount"] if isinstance(r, sqlite3.Row) else r[3]
        if purchase_priority_score(sib_s, sib_t, sib_a) < new_score:
            cur.execute("DELETE FROM purchase_options WHERE purchase_id=?", (sib_id,))
            cur.execute("DELETE FROM purchases WHERE id=?", (sib_id,))

    cur.execute("""
        INSERT INTO purchases (order_id, user_id, tarif_name, amount, status, status_normalized,
                               is_tribe, email_sent_date, is_modified, commentaires_correctif,
                               legacy_adherent_id, legacy_season_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (order_id, user_id, tarif, amt_val, new_status, normalize_status(new_status),
          "Oui" if is_true(_get(rec, "champ_Famille : nous sommes une tribu de 3 ou plus inscrits ce qui permet un code de réduction : FAMILLE")) else "Non",
          _get(rec, "email_sent_date"),
          _get(rec, "is_modified") or "Non",
          clean_legacy_text(_get(rec, "commentaires_correctif")) or "",
          legacy_adherent_id, legacy_season_id, now_iso, now_iso))
    return cur.lastrowid


def insert_options_v2(cur, purchase_id, rec):
    """Insère les options d'assurance souscrites (1 ligne par option). Retourne le nombre ajouté."""
    added = 0
    for opt_name, col_has, col_amount in OPTION_PAIRS:
        if is_true(_get(rec, col_has)):
            try:
                amt = float(_get(rec, col_amount) or 0.0)
            except (ValueError, TypeError):
                amt = 0.0
            try:
                cur.execute("INSERT INTO purchase_options (purchase_id, option_name, amount) VALUES (?, ?, ?)",
                            (purchase_id, opt_name, amt))
                added += 1
            except sqlite3.IntegrityError:
                pass
    return added


def sync_members_to_v2(cur, members, season_name=SEASON_ACTIVE):
    """
    Phase 3 — Écriture applicative des adhésions dans le schéma v2.
    Appelé par SqliteRepository.upsert_members en miroir du flux legacy (même transaction).
    Écrit désormais les payeurs (payer_*) perdus par l'ancien upsert.
    """
    ensure_v2_schema(cur)
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    season_id = resolve_season_id(cur, season_name)
    field_map = build_user_field_map(cur)

    stats = {"users": 0, "orders": 0, "purchases": 0, "options": 0, "skipped_priority": 0}
    for m in members:
        order_ref = str(_get(m, "order_ref") or "").strip()
        if not order_ref:
            continue
        user_id, _created = upsert_user_v2(cur, m, now_iso, field_map)
        stats["users"] += 1
        order_id = upsert_order_v2(
            cur, order_ref, _get(m, "order_date"), _get(m, "status"),
            _get(m, "payer_lastName"), _get(m, "payer_firstName"), _get(m, "payer_email"),
            season_id, now_iso,
        )
        stats["orders"] += 1
        purchase_id = insert_purchase_v2(cur, order_id, user_id, m, now_iso, legacy_season_id=season_id)
        if purchase_id is None:
            stats["skipped_priority"] += 1
            continue
        stats["purchases"] += 1
        stats["options"] += insert_options_v2(cur, purchase_id, m)
    return stats


def _resolve_user_id(cur, adherent_id=None, last_name="", first_name=""):
    """Résout un user v2 : d'abord par legacy_adherent_id, sinon par identité normalisée.
    Le fallback identité est indispensable : les users créés par la synchronisation
    (upsert_members) n'ont pas encore de legacy_adherent_id au moment du miroir."""
    if adherent_id is not None:
        cur.execute("SELECT id FROM users WHERE legacy_adherent_id=?", (adherent_id,))
        row = cur.fetchone()
        if row:
            return row["id"] if isinstance(row, sqlite3.Row) else row[0]
    k_last = normalize_name(str(last_name or "")).upper()
    k_first = normalize_name(str(first_name or "")).lower()
    cur.execute("SELECT id FROM users WHERE last_name_key=? AND first_name_key=?", (k_last, k_first))
    row = cur.fetchone()
    if row:
        return row["id"] if isinstance(row, sqlite3.Row) else row[0]
    return None


def apply_member_update(cur, user_id, order_ref, updated_fields, comment_text):
    """
    Phase 5 — Applique les correctifs manuels d'un adhérent dans le schéma v2 :
    champs personnels -> users, champs de saison -> purchases, bascule des options.
    """
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")

    # Champs personnels -> users
    for ihm_key, users_col in IHM_TO_USERS.items():
        if ihm_key in updated_fields:
            cur.execute(f'UPDATE users SET "{users_col}"=?, updated_at=? WHERE id=?',
                        (updated_fields[ihm_key], now_iso, user_id))
    if "user_last_name" in updated_fields:
        cur.execute("UPDATE users SET last_name=?, last_name_key=? WHERE id=?",
                    (str(updated_fields["user_last_name"]),
                     normalize_name(str(updated_fields["user_last_name"])).upper(), user_id))
    if "user_first_name" in updated_fields:
        cur.execute("UPDATE users SET first_name=?, first_name_key=? WHERE id=?",
                    (str(updated_fields["user_first_name"]),
                     normalize_name(str(updated_fields["user_first_name"])).lower(), user_id))
    if "birth_date" in updated_fields:
        raw = str(updated_fields["birth_date"] or "")
        cur.execute("UPDATE users SET birth_date=?, birth_date_raw=? WHERE id=?",
                    (parse_iso_date(raw), raw, user_id))

    # Champs de saison -> purchases
    sets = ["is_modified=?", "commentaires_correctif=?", "updated_at=?"]
    params = ["Oui", clean_legacy_text(comment_text) or "", now_iso]
    if "status" in updated_fields:
        sets += ["status=?", "status_normalized=?"]
        params += [str(updated_fields["status"]), normalize_status(updated_fields["status"])]
    cur.execute(
        f'UPDATE purchases SET {", ".join(sets)} '
        f'WHERE user_id=? AND order_id IN (SELECT id FROM orders WHERE order_ref=?)',
        params + [user_id, str(order_ref or "").strip()],
    )

    # Bascule des options d'assurance
    cur.execute(
        "SELECT id FROM purchases WHERE user_id=? AND order_id IN (SELECT id FROM orders WHERE order_ref=?)",
        (user_id, str(order_ref or "").strip()),
    )
    prow = cur.fetchone()
    if prow:
        purchase_id = prow["id"] if isinstance(prow, sqlite3.Row) else prow[0]
        for ihm_key, opt_name in IHM_TO_OPTIONS.items():
            if ihm_key not in updated_fields:
                continue
            if is_true(updated_fields[ihm_key]):
                cur.execute("INSERT OR IGNORE INTO purchase_options (purchase_id, option_name, amount) "
                            "VALUES (?, ?, 0.0)", (purchase_id, opt_name))
            else:
                cur.execute("DELETE FROM purchase_options WHERE purchase_id=? AND option_name=?",
                            (purchase_id, opt_name))


def mirror_email_sent_date(cur, order_ref, date_str):
    """Phase 3 — Miroir de la date d'envoi d'email sur les achats v2 de la commande."""
    cur.execute(
        "UPDATE purchases SET email_sent_date=? WHERE order_id IN (SELECT id FROM orders WHERE order_ref=?)",
        (date_str, str(order_ref or "").strip()),
    )


def mirror_adherent_personal(cur, adherent_id, **fields):
    """Phase 3 — Miroir générique de mises à jour adherents -> users (merges FFME/autonomes)."""
    cols = []
    params = []
    for col, val in fields.items():
        cols.append(f'"{col}"=?')
        params.append(val)
    if not cols:
        return
    cols.append("updated_at=?")
    params.append(datetime.datetime.now().isoformat(timespec="seconds"))
    params.append(adherent_id)
    cur.execute(f'UPDATE users SET {", ".join(cols)} WHERE legacy_adherent_id=?', params)


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
    u.last_name AS "last_name",
    u.first_name AS "first_name",
    u.birth_date AS "birth_date",
    u.birth_date_raw AS "birth_date_raw",
    u.gender AS "gender",
    u.nationality AS "nationality",
    u.address AS "address",
    u.zip_code AS "zip_code",
    u.city AS "city",
    u.country AS "country",
    u.phone AS "phone",
    u.email_primary AS "email_primary",
    u.email_secondary AS "email_secondary",
    u.emergency1_name AS "emergency1_name",
    u.emergency1_phone AS "emergency1_phone",
    u.emergency2_name AS "emergency2_name",
    u.emergency2_phone AS "emergency2_phone",
    u.licence_ffme AS "licence_ffme",
    u.photo_auth AS "photo_auth",
    u.health_commitment AS "health_commitment",
    p.is_tribe AS "is_tribe",
    o.payer_last_name AS "payer_last_name",
    o.payer_first_name AS "payer_first_name",
    o.payer_email AS "payer_email",
    o.payment_method AS "payment_method",
    o.promo_code AS "promo_code",
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


def recreate_compat_view(cur):
    """Recree la vue de compatibilite avec la definition du code courant
    (CREATE VIEW IF NOT EXISTS ne met pas a jour une definition existante)."""
    cur.execute("DROP VIEW IF EXISTS v_adherents_legacy")
    cur.execute(COMPAT_VIEW_SQL)
