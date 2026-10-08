"""Tests du cache database.db adossé à Firestore (infrastructure/cloud_database.py)."""
import copy
import os
import sqlite3
import sys
import tempfile
import unittest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure import cloud_database as cdb  # noqa: E402
from infrastructure.sqlite_repository import SqliteRepository  # noqa: E402


class FakeStore:
    """Firestore en mémoire : préconditions, horodatages, requêtes par date."""
    project_id = "test-project"

    def __init__(self):
        self.docs = {}  # (collection, id) -> doc
        self.clock = 0
        self.commits = 0
        self.before_commit = None

    def _ts(self):
        self.clock += 1
        return f"2026-10-08T10:{self.clock // 60 % 60:02d}:{self.clock % 60:02d}.{self.clock:06d}Z"

    def _out(self, coll, doc_id):
        d = self.docs[(coll, doc_id)]
        return {"id": doc_id, "fields": copy.deepcopy(d["fields"]), "deleted": d["deleted"],
                "update_time": d["update_time"], "modified_at": d["modified_at"]}

    def list_all(self, coll):
        return [self._out(c, i) for (c, i) in sorted(self.docs) if c == coll]

    def list_modified_since(self, coll, since):
        return [self._out(c, i) for (c, i), d in sorted(self.docs.items())
                if c == coll and cdb.ts_key(d["modified_at"]) >= cdb.ts_key(since)]

    def get_many(self, coll, ids):
        return {i: (self._out(coll, i) if (coll, i) in self.docs else None) for i in ids}

    def max_int_id(self, coll, field):
        vals = [d["fields"].get(field) for (c, _), d in self.docs.items() if c == coll]
        return max([v for v in vals if isinstance(v, int)] or [0])

    def commit(self, writes):
        if self.before_commit:
            hook, self.before_commit = self.before_commit, None
            hook()
        for w in writes:  # vérification atomique des préconditions
            key = (w["collection"], w["doc_id"])
            pre = w.get("precondition") or {}
            cur = self.docs.get(key)
            if "exists" in pre and bool(cur) != pre["exists"]:
                raise cdb.CloudConflictError("exists")
            if "updateTime" in pre and (not cur or cur["update_time"] != pre["updateTime"]):
                raise cdb.CloudConflictError("updateTime")
        self.commits += 1
        out = []
        for w in writes:
            key = (w["collection"], w["doc_id"])
            ts = self._ts()
            if w.get("mask") is None:
                fields = dict(w["fields"])
            else:
                fields = dict(self.docs[key]["fields"]) if key in self.docs else {}
                fields.update({k: w["fields"][k] for k in w["mask"]})
            self.docs[key] = {"fields": fields, "deleted": bool(w.get("deleted")),
                              "update_time": ts, "modified_at": ts}
            out.append({"update_time": ts, "modified_at": ts})
        return out

    # aide aux tests : modification « par un autre poste »
    def remote_patch(self, table, doc_id, **fields):
        key = (cdb.collection_for(table), str(doc_id))
        ts = self._ts()
        self.docs[key]["fields"].update(fields)
        self.docs[key].update(update_time=ts, modified_at=ts)


def _seed(path):
    cdb.create_schema(path)
    conn = sqlite3.connect(path)
    conn.executescript("""
        DELETE FROM seasons;
        INSERT INTO seasons (id, name, is_active) VALUES (1, '2025-2026', 0), (2, '2026-2027', 1);
        INSERT INTO users (id, last_name, first_name, last_name_key, first_name_key, birth_date, city, phone)
            VALUES (1, 'MARTIN', 'Leo', 'MARTIN', 'LEO', '2010-05-10', 'Jonage', '0600000001'),
                   (2, 'DURAND', 'Zoé', 'DURAND', 'ZOE', '2012-01-02', 'Meyzieu', '0600000002');
        INSERT INTO orders (id, order_ref, order_date, status, season_id) VALUES
            (10, 'A10', '2026-09-01', 'Validated', 2), (11, 'A11', '2025-09-01', 'Validated', 1);
        INSERT INTO purchases (id, order_id, user_id, tarif_name, amount, status) VALUES
            (100, 10, 1, 'Loisir', 150.0, 'Validated'), (101, 10, 2, 'Compétition', 210.5, 'Validated'),
            (102, 11, 1, 'Loisir', 140.0, 'Validated');
        INSERT INTO purchase_options (id, purchase_id, option_name, amount) VALUES (1, 100, 'Assurance Base', 11.0);
        INSERT INTO app_settings (key, value) VALUES ('default_sender_name', 'ALJ');
        INSERT INTO geocache (address, lat, lon) VALUES ('1 rue de la Paix, 69330, JONAGE, France', 45.79, 5.04);
    """)
    conn.commit()
    conn.close()


def _load(path, season):
    SqliteRepository.set_db_path(path)
    return SqliteRepository.load_direct_data(season)


class CloudDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "source.db")
        _seed(self.src)
        self.store = FakeStore()
        cdb.import_database(self.src, self.store)
        self.a = os.path.join(self.tmp, "a.db")
        self.b = os.path.join(self.tmp, "b.db")
        cdb.build_cache(self.a, self.store)
        cdb.build_cache(self.b, self.store)
        self._saved_path = SqliteRepository.get_db_path()

    def tearDown(self):
        SqliteRepository.set_db_path(self._saved_path)

    def sync(self, path):
        conn = cdb.connect(path)
        try:
            rep = cdb.pull(conn, self.store)
            cdb.flush(conn, self.store, "test", rep)
            return rep
        finally:
            conn.close()

    def write(self, path, sql, *params):
        SqliteRepository.set_db_path(path)
        conn = SqliteRepository.get_connection()
        conn.execute(sql, params)
        conn.commit()
        conn.close()

    def row(self, path, sql, *params):
        conn = sqlite3.connect(path)
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def test_round_trip_identical_view(self):
        for season in ("2025-2026", "2026-2027"):
            self.assertEqual(_load(self.src, season), _load(self.a, season))
        self.assertEqual(len([k for k in self.store.docs if k[0] == "crm_users"]), 2)
        self.assertIn(("crm_purchases", "100"), self.store.docs)
        self.assertIsInstance(self.store.docs[("crm_purchases", "101")]["fields"]["amount"], float)

    def test_local_update_sends_only_changed_fields(self):
        self.write(self.a, "UPDATE users SET city = 'Lyon' WHERE id = 1")
        conn = cdb.connect(self.a)
        self.assertEqual(cdb.pending_count(conn), 1)
        conn.close()
        rep = self.sync(self.a)
        self.assertEqual(rep.get("pushed"), 1)
        self.assertEqual(self.store.docs[("crm_users", "1")]["fields"]["city"], "Lyon")
        conn = cdb.connect(self.a)
        self.assertEqual(cdb.pending_count(conn), 0)
        conn.close()
        self.sync(self.b)
        self.assertEqual(self.row(self.b, "SELECT city FROM users WHERE id = 1")[0], "Lyon")

    def test_concurrent_edits_of_different_fields_are_merged(self):
        self.write(self.a, "UPDATE users SET city = 'Lyon' WHERE id = 1")
        self.write(self.b, "UPDATE users SET phone = '0700000000' WHERE id = 1")
        self.sync(self.a)
        self.sync(self.b)  # B : pull fusionne la ville, puis envoie le téléphone
        self.sync(self.a)
        for p in (self.a, self.b):
            self.assertEqual(self.row(p, "SELECT city, phone FROM users WHERE id = 1"), ("Lyon", "0700000000"))
        f = self.store.docs[("crm_users", "1")]["fields"]
        self.assertEqual((f["city"], f["phone"]), ("Lyon", "0700000000"))

    def test_conflict_during_flush_is_retried_with_merge(self):
        self.write(self.a, "UPDATE purchases SET email_sent_date = '2026-10-08' WHERE id = 100")
        # Un autre poste modifie le même document entre la préparation et l'envoi
        self.store.before_commit = lambda: self.store.remote_patch("purchases", 100, is_modified="Oui")
        conn = cdb.connect(self.a)
        rep = cdb.flush(conn, self.store, "test")
        conn.close()
        self.assertGreaterEqual(rep.get("conflicts", 0), 1)
        f = self.store.docs[("crm_purchases", "100")]["fields"]
        self.assertEqual((f["email_sent_date"], f["is_modified"]), ("2026-10-08", "Oui"))
        self.assertEqual(self.row(self.a, "SELECT is_modified FROM purchases WHERE id = 100")[0], "Oui")

    def test_delete_is_propagated(self):
        self.write(self.a, "DELETE FROM purchase_options WHERE id = 1")
        self.sync(self.a)
        self.assertTrue(self.store.docs[("crm_purchase_options", "1")]["deleted"])
        self.sync(self.b)
        self.assertIsNone(self.row(self.b, "SELECT * FROM purchase_options WHERE id = 1"))
        # une base reconstruite ne contient pas la tombe
        c = os.path.join(self.tmp, "c.db")
        cdb.build_cache(c, self.store)
        self.assertIsNone(self.row(c, "SELECT * FROM purchase_options WHERE id = 1"))

    def test_insert_or_replace_logs_replaced_row(self):
        # (order 10, user 2) existe sous l'ID 101 : REPLACE la supprime et crée l'ID 200
        self.write(self.a, "INSERT OR REPLACE INTO purchases (id, order_id, user_id, tarif_name, amount) "
                           "VALUES (200, 10, 2, 'Compétition', 210.5)")
        self.sync(self.a)
        self.assertTrue(self.store.docs[("crm_purchases", "101")]["deleted"])
        self.assertFalse(self.store.docs[("crm_purchases", "200")]["deleted"])
        self.sync(self.b)
        self.assertIsNone(self.row(self.b, "SELECT id FROM purchases WHERE id = 101"))
        self.assertEqual(self.row(self.b, "SELECT user_id FROM purchases WHERE id = 200")[0], 2)

    def test_same_new_id_on_two_posts_is_renumbered(self):
        for p, name in ((self.a, "PETIT"), (self.b, "GRAND")):
            self.write(p, "INSERT INTO users (last_name, first_name, last_name_key, first_name_key) "
                          f"VALUES ('{name}', 'Max', '{name}', 'MAX')")
            self.write(p, "INSERT INTO purchases (order_id, user_id, tarif_name, amount) "
                          f"SELECT 10, id, 'Loisir', 1.0 FROM users WHERE last_name = '{name}'")
        self.sync(self.a)
        rep = self.sync(self.b)
        self.assertTrue(rep.get("renumbered"))
        self.sync(self.a)
        for p in (self.a, self.b):
            ids = dict((n, i) for n, i in sqlite3.connect(p).execute(
                "SELECT last_name, id FROM users WHERE first_name = 'Max'"))
            self.assertEqual(set(ids), {"PETIT", "GRAND"})
            self.assertNotEqual(ids["PETIT"], ids["GRAND"])
            # l'inscription suit son adhérent renuméroté
            got = sqlite3.connect(p).execute(
                "SELECT u.last_name FROM purchases pu JOIN users u ON u.id = pu.user_id "
                "WHERE pu.order_id = 10 AND u.first_name = 'Max' ORDER BY 1").fetchall()
            self.assertEqual([g[0] for g in got], ["GRAND", "PETIT"])

    def test_repository_write_path_is_tracked(self):
        SqliteRepository.set_db_path(self.a)
        ok = SqliteRepository.save_app_setting("default_sender_name", "ALJ Escalade")
        self.assertTrue(ok)
        self.sync(self.a)
        docs = [d for (c, _), d in self.store.docs.items() if c == "crm_app_settings"]
        self.assertIn("ALJ Escalade", [d["fields"].get("value") for d in docs])

    def test_pull_does_not_reapply_own_writes(self):
        self.write(self.a, "UPDATE users SET city = 'Lyon' WHERE id = 1")
        self.sync(self.a)
        rep = self.sync(self.a)
        self.assertFalse(rep.get("pulled"))
        self.assertFalse(rep.get("pushed"))


if __name__ == "__main__":
    unittest.main()
