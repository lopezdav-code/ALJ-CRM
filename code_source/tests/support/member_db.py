"""Temporary member database (SQLite, schema v2) for the member route and repository tests."""

import os
import tempfile
import unittest

from infrastructure.sqlite_repository import SqliteRepository

BASE_MEMBER = {
    "order_date": "2026-09-01T10:00:00",
    "status": "Validated",
    "amount": 150.0,
    "payer_lastName": "MARTIN",
    "payer_firstName": "Claire",
    "champ_Date de naissance de l'adhérent": "2017-03-10",
    "is_modified": "Non",
    "commentaires_correctif": "",
}


class MemberDbTestCase(unittest.TestCase):

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        original = SqliteRepository.get_db_path()

        def restore():
            SqliteRepository.set_db_path(original)
            SqliteRepository._database_setup_done = False
        self.addCleanup(restore)
        SqliteRepository.set_db_path(os.path.join(self._tmp.name, "members.db"))
        SqliteRepository._database_setup_done = False
        SqliteRepository.setup_database()

    def seed(self, ref, first_name, last_name, tarif, season="2026-2027", **extra):
        member = dict(BASE_MEMBER, order_ref=ref, user_firstName=first_name, user_lastName=last_name,
                      tarif_name=tarif, payer_email=f"{ref}@test.com", **extra)
        SqliteRepository.upsert_members([member], season_name=season)

    def seed_planning(self, groupe, tarifs, **extra):
        import json
        conn = SqliteRepository.get_connection()
        try:
            conn.execute("INSERT INTO planning (groupe, helloasso_tarifs, jour, horaires, categorie_age, type)"
                         " VALUES (?, ?, ?, ?, ?, ?)",
                         (groupe, json.dumps(tarifs), extra.get("jour", ""), extra.get("horaires", ""),
                          extra.get("categorie_age", ""), extra.get("type", "")))
            conn.commit()
        finally:
            conn.close()
