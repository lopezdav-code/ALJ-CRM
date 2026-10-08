"""
Migration de database.db (SQLite) vers Firestore (collections crm_<table>).

    python migrate_sqlite_to_firestore.py chemin/database.db --dry-run
    python migrate_sqlite_to_firestore.py chemin/database.db --apply [--force]
    python migrate_sqlite_to_firestore.py chemin/database.db --verify

- La base source est d'abord copiée puis mise au schéma courant de l'application
  (comme au démarrage de l'appli) ; l'original n'est jamais modifié.
- --apply écrit un document par ligne (ID = clé primaire) : ré-exécutable sans
  doublon. Refuse d'écrire si les collections contiennent déjà des données
  (sauf --force).
- --verify reconstruit un cache depuis Firestore et le compare à la source :
  chaque table ligne à ligne, puis la liste des adhérents (load_direct_data)
  pour chaque saison.

Jeton : variable ALJ_FIRESTORE_ACCESS_TOKEN (ex. `gcloud auth print-access-token`),
sinon le compte Google du club configuré dans l'application.
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from infrastructure import cloud_database as cdb  # noqa: E402
from infrastructure.sqlite_repository import SqliteRepository  # noqa: E402


def normalized_copy(src: str, workdir: str) -> str:
    dst = os.path.join(workdir, "source_normalisee.db")
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    s.backup(d)
    d.close()
    s.close()
    saved = SqliteRepository.get_db_path()
    try:
        SqliteRepository.set_db_path(dst)
        SqliteRepository.setup_database(force=True)
    finally:
        SqliteRepository.set_db_path(saved)
    return dst


def counts(path: str) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in cdb.tracked_tables(conn)}
    finally:
        conn.close()


def load_view(path: str, season: str) -> list:
    saved = SqliteRepository.get_db_path()
    try:
        SqliteRepository.set_db_path(path)
        return SqliteRepository.load_direct_data(season)
    finally:
        SqliteRepository.set_db_path(saved)


def compare(source: str, cache: str) -> list:
    problems = []
    s = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    c = sqlite3.connect(f"file:{cache}?mode=ro", uri=True)
    try:
        for t in cdb.tracked_tables(s):
            pk = cdb.table_pk(s, t)
            cols = cdb.table_columns(s, t)
            order = ", ".join(f'"{k}"' for k in pk)
            col_sql = ", ".join(f'"{k}"' for k in cols)
            a = s.execute(f'SELECT {col_sql} FROM "{t}" ORDER BY {order}').fetchall()
            b = c.execute(f'SELECT {col_sql} FROM "{t}" ORDER BY {order}').fetchall()
            if len(a) != len(b):
                problems.append(f"{t} : {len(a)} lignes en source, {len(b)} dans Firestore")
            diff = 0
            for ra, rb in zip(a, b, strict=False):
                if any(x != y or type(x) is not type(y) for x, y in zip(ra, rb, strict=False)):
                    diff += 1
                    if diff <= 3:
                        problems.append(f"{t} : écart {ra[:3]} / {rb[:3]}")
            if diff:
                problems.append(f"{t} : {diff} ligne(s) différente(s)")
        seasons = [r[0] for r in s.execute("SELECT name FROM seasons ORDER BY name")]
    finally:
        s.close()
        c.close()
    for season in seasons:
        va, vb = load_view(source, season), load_view(cache, season)
        if va != vb:
            problems.append(f"Adhérents {season} : {len(va)} vs {len(vb)} lignes, contenu différent")
        else:
            print(f"   ✅ Adhérents {season} : {len(va)} lignes identiques (load_direct_data)")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    ap.add_argument("--force", action="store_true", help="écrire même si Firestore contient déjà des données")
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    workdir = tempfile.mkdtemp(prefix="alj_migration_")
    store = cdb.RestStore(project_id=args.project)
    print(f"📦 Source : {args.source}")
    print(f"☁️  Projet Firestore : {store.project_id}")
    src = normalized_copy(args.source, workdir)
    n = counts(src)
    for t, k in n.items():
        print(f"   {t:<18} {k:>5} ligne(s) -> {cdb.collection_for(t)}")
    print(f"   Total : {sum(n.values())} documents")

    if args.dry_run:
        print("ℹ️  Simulation : rien n'a été écrit.")
        return 0

    if args.apply:
        existing = {t: len(store.list_all(cdb.collection_for(t))) for t in n}
        if any(existing.values()) and not args.force:
            print(f"❌ Firestore contient déjà des données : {existing}. Relancer avec --force pour écraser.")
            return 2
        written = cdb.import_database(src, store)
        print(f"✅ Écrit : {written}")

    cache = os.path.join(workdir, "cache_firestore.db")
    cdb.build_cache(cache, store)
    print("🔎 Vérification Firestore -> cache -> comparaison avec la source…")
    problems = compare(src, cache)
    if problems:
        print("❌ Écarts détectés :")
        for p in problems:
            print("   - " + p)
        return 1
    print("✅ Vérification OK : Firestore contient exactement la base source.")
    shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
