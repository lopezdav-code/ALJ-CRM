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

La logique partagée (DDL, normalisations, upserts) vit dans infrastructure/schema_v2.py,
réutilisée par les écritures applicatives depuis la phase 3.

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
from infrastructure.sqlite_repository import SqliteRepository  # noqa: E402
from infrastructure.schema_v2 import (  # noqa: E402
    SCHEMA_TARGET_VERSION, SEASON_ACTIVE,
    normalize_status, status_score, clean_legacy_text, is_true,
    DOB_COLUMN, build_user_field_map, ensure_v2_schema,
    upsert_user_v2, upsert_order_v2, insert_options_v2,
)


def migrate(skip_excel=False):
    db_path = SqliteRepository.get_db_path()
    print(f"[MIGRATION V2] Base cible : {db_path}")

    SqliteRepository.setup_database()
    conn = SqliteRepository.get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("PRAGMA user_version")
    version = cur.fetchone()[0]
    if version >= SCHEMA_TARGET_VERSION:
        # Idempotent : garantir la présence de la vue de compatibilité (ex: bases migrées
        # avant l'introduction de la vue), puis vérifier les comptages.
        recreate_compat_view(cur)
        conn.commit()
        counts = {
            "users": cur.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "orders": cur.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "purchases": cur.execute("SELECT COUNT(*) FROM purchases").fetchone()[0],
        }
        print(f"[MIGRATION V2] Base déjà migrée (user_version={version}) : {counts}")
        conn.close()
        return True

    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    seasons = {r["name"]: r["id"] for r in cur.execute("SELECT id, name FROM seasons")}
    active_season_id = seasons.get(SEASON_ACTIVE)

    # Phase 5 — la migration ne s'applique qu'aux bases contenant encore les tables legacy
    has_legacy = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='adherents'"
    ).fetchone() is not None
    if not has_legacy:
        recreate_compat_view(cur)
        cur.execute(f"PRAGMA user_version = {SCHEMA_TARGET_VERSION}")
        conn.commit()
        conn.close()
        print("[MIGRATION V2] Base v2 native (pas de tables legacy) : vue vérifiée, version taguée.")
        return True

    try:
        ensure_v2_schema(cur)
        field_map = build_user_field_map(cur)

        # Garde-fou : tables v2 déjà peuplées (ex: double-écriture phase 3 sur base fraîche)
        existing_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing_users > 0:
            recreate_compat_view(cur)
            cur.execute(f"PRAGMA user_version = {SCHEMA_TARGET_VERSION}")
            conn.commit()
            conn.close()
            print(f"[MIGRATION V2] Tables v2 déjà peuplées ({existing_users} users) : "
                  f"vue vérifiée, version taguée, pas de re-migration.")
            return True

        rows = cur.execute("""
            SELECT las.adherent_id, las.season_id, las.order_ref, las.order_date,
                   las.tarif_name, las.amount, las.status, las.is_modified,
                   las.commentaires_correctif, las.email_sent_date,
                   a.*
            FROM adherents_seasons las
            JOIN adherents a ON a.id = las.adherent_id
            ORDER BY las.adherent_id, las.season_id
        """).fetchall()
        print(f"[MIGRATION V2] {len(rows)} inscriptions legacy à migrer...")

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

            user_id, created = upsert_user_v2(cur, r, now_iso, field_map)
            if created:
                stats["users_created"] += 1
            else:
                stats["users_merged"] += 1

            order_id = upsert_order_v2(
                cur, order_ref, r["order_date"], r["status"],
                r["payer_lastName"], r["payer_firstName"], r["payer_email"],
                r["season_id"], now_iso,
            )

            # Insertion directe (la migration ne ré-applique pas la priorité : les données
            # legacy sont déjà dédupliquées en amont par le pipeline de synchronisation)
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
                      r["email_sent_date"], r["is_modified"], clean_legacy_text(r["commentaires_correctif"]) or "",
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
                stats["options"] += insert_options_v2(cur, purchase_id, r)
                options_attached.add(aid)

        # ---- Récupération payeurs / moyen de paiement / promo depuis l'archive Excel
        if not skip_excel:
            recover_from_excel(cur)

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
        if stats["anomalies"]:
            print(f"  Anomalies ({len(stats['anomalies'])}) :")
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
            print("\n[MIGRATION V2] Écart détecté : ROLLBACK effectué, base inchangée.")
            return False

        recreate_compat_view(cur)
        cur.execute(f"PRAGMA user_version = {SCHEMA_TARGET_VERSION}")
        conn.commit()
        conn.close()
        print(f"\n[MIGRATION V2] Migration validée et commitée (user_version={SCHEMA_TARGET_VERSION}).")
        return True

    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"\n[MIGRATION V2] Erreur : {e} — ROLLBACK effectué.")
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
        print("[MIGRATION V2] Archive Excel HelloAsso introuvable : payeurs non récupérés.")
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

    print(f"[MIGRATION V2] Récupération Excel : {os.path.basename(excel_path)}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Migration schéma BDD v2 (users/orders/purchases)")
    parser.add_argument("db_path", nargs="?", default=None, help="Chemin de database.db (défaut : base active)")
    parser.add_argument("--skip-excel", action="store_true", help="Ne pas lire l'archive Excel HelloAsso")
    args = parser.parse_args()

    if args.db_path:
        SqliteRepository.set_db_path(args.db_path)
    elif not os.path.exists(SqliteRepository.get_db_path()):
        print(f"Base introuvable : {SqliteRepository.get_db_path()}")
        sys.exit(1)

    ok = migrate(skip_excel=args.skip_excel)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
