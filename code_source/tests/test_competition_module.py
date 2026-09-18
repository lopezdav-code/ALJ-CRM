"""Tests du module de gestion des compétitions (dépôt dédié + rapprochement HelloAsso)."""
import os
import sys
import sqlite3
import tempfile
import unittest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure import competition_repository as cr
from infrastructure.sqlite_repository import SqliteRepository
from infrastructure import schema_v2
from domain.competition_models import Competition, STATUT_EN_COURS
from domain.competition_matching import (
    parse_campaign_identifier,
    match_items_to_participants,
    extract_competition_number,
    competition_number_ok,
    summarize_items,
)


def _make_item(state="Validated", first="Jean", last="DUPONT", amount=1000, licence=None, order_id=1):
    item = {
        "state": state,
        "amount": amount,
        "user": {"firstName": first, "lastName": last},
        "order": {"id": order_id},
        "customFields": [],
    }
    if licence is not None:
        item["customFields"].append({"name": "Numéro de Licence FFME", "answer": licence})
    return item


class TestCampaignIdentifier(unittest.TestCase):
    def test_full_event_url(self):
        res = parse_campaign_identifier(
            "https://www.helloasso.com/associations/amicale-laique-de-jonage/evenements/competition-escalade-2026"
        )
        self.assertEqual(res["form_type"], "Event")
        self.assertEqual(res["slug"], "competition-escalade-2026")

    def test_full_form_url(self):
        res = parse_campaign_identifier(
            "https://www.helloasso.com/associations/amicale-laique-de-jonage/formulaires/Event/compete-u11"
        )
        self.assertEqual(res["form_type"], "Event")
        self.assertEqual(res["slug"], "compete-u11")

    def test_explicit_prefix(self):
        res = parse_campaign_identifier("Membership:ma-campagne")
        self.assertEqual(res["form_type"], "Membership")
        self.assertEqual(res["slug"], "ma-campagne")

    def test_bare_slug_defaults_to_event(self):
        res = parse_campaign_identifier(" competition-u13 ")
        self.assertEqual(res["form_type"], "Event")
        self.assertEqual(res["slug"], "competition-u13")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parse_campaign_identifier("  ")


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.participants = [
            {"adherent_id": 1, "nom": "DUPONT", "prenom": "Jean", "num_licence": "123456",
             "selectionne": 1, "statut_paiement": "en_attente", "montant_paye": 0.0},
            {"adherent_id": 2, "nom": "MARTIN", "prenom": "Léa", "num_licence": "789012",
             "selectionne": 1, "statut_paiement": "non_invite", "montant_paye": 0.0},
            {"adherent_id": 3, "nom": "BERTRAND", "prenom": "Anne-Sophie", "num_licence": "",
             "selectionne": 1, "statut_paiement": "en_attente", "montant_paye": 0.0},
        ]

    def test_match_by_licence(self):
        res = match_items_to_participants(
            [_make_item(licence="123456", order_id=101)], self.participants, prix_attendu=10.0
        )
        self.assertEqual(res["updates"], [(1, 10.0)])
        self.assertEqual(res["stats"]["nb_anomalies"], 0)

    def test_match_by_name_when_no_licence_field(self):
        # Anne-Sophie n'a pas de licence : le rapprochement par nom doit fonctionner
        res = match_items_to_participants(
            [_make_item(first="Anne-Sophie", last="BERTRAND", order_id=102)],
            self.participants, prix_attendu=10.0
        )
        self.assertEqual([(u[0]) for u in res["updates"]], [3])
        types = [a["type"] for a in res["anomalies"]]
        self.assertIn("paiement_sans_licence", types)

    def test_payment_with_unknown_licence(self):
        res = match_items_to_participants(
            [_make_item(licence="999999", first="X", last="Y", order_id=103)],
            self.participants, prix_attendu=10.0
        )
        self.assertEqual(res["updates"], [])
        self.assertIn("paiement_inconnu", [a["type"] for a in res["anomalies"]])

    def test_amount_mismatch(self):
        res = match_items_to_participants(
            [_make_item(licence="123456", amount=800, order_id=104)],
            self.participants, prix_attendu=10.0
        )
        self.assertEqual(res["updates"], [(1, 8.0)])
        self.assertIn("ecart_tarif", [a["type"] for a in res["anomalies"]])

    def test_duplicate_payments(self):
        res = match_items_to_participants(
            [_make_item(licence="123456", order_id=1), _make_item(licence="123456", order_id=2)],
            self.participants, prix_attendu=10.0
        )
        self.assertIn("doublon", [a["type"] for a in res["anomalies"]])

    def test_canceled_and_refunded_ignored(self):
        res = match_items_to_participants(
            [_make_item(state="Canceled", licence="123456", order_id=1),
             _make_item(state="Refunded", licence="789012", order_id=2)],
            self.participants, prix_attendu=10.0
        )
        self.assertEqual(res["updates"], [])
        self.assertIn("remboursement", [a["type"] for a in res["anomalies"]])

    def test_waiting_state_reported(self):
        res = match_items_to_participants(
            [_make_item(state="Waiting", licence="123456", order_id=1)],
            self.participants, prix_attendu=10.0
        )
        self.assertEqual(res["updates"], [])
        self.assertIn("paiement_non_finalise", [a["type"] for a in res["anomalies"]])


class TestCompetitionNumberCheck(unittest.TestCase):
    """Contrôle du champ « Compétition concernée » (n° d'épreuve) sur HelloAsso."""

    def setUp(self):
        self.participants = [
            {"adherent_id": 1, "nom": "DUPONT", "prenom": "Jean", "num_licence": "123456",
             "selectionne": 1, "statut_paiement": "en_attente", "montant_paye": 0.0},
        ]

    def test_extract_competition_number(self):
        item = {"customFields": [{"name": "Compétition concernée", "answer": " EVT-2026-001 "}]}
        self.assertEqual(extract_competition_number(item), "EVT-2026-001")
        item2 = {"customFields": [{"name": "Competition concernee", "value": "EVT-2026-002"}]}
        self.assertEqual(extract_competition_number(item2), "EVT-2026-002")
        # Test du nouveau champ d'identifiant précis ("Numéro de la compétition") (Nouveau !)
        item3 = {"customFields": [{"name": "Numéro de la compétition", "answer": "18866"}]}
        self.assertEqual(extract_competition_number(item3), "18866")
        # Champ absent ou autre champ : chaîne vide
        self.assertEqual(extract_competition_number({"customFields": []}), "")
        self.assertEqual(extract_competition_number({}), "")
        self.assertEqual(
            extract_competition_number({"customFields": [{"name": "Numéro de Licence FFME", "answer": "123"}]}),
            ""
        )

    def test_competition_number_ok(self):
        self.assertTrue(competition_number_ok("EVT-2026-001", "EVT-2026-001"))
        self.assertTrue(competition_number_ok("Compétition n° EVT-2026-001", "EVT-2026-001"))
        self.assertTrue(competition_number_ok("", ""))          # contrôle désactivé
        self.assertFalse(competition_number_ok("", "EVT-2026-001"))   # champ vide
        self.assertFalse(competition_number_ok("EVT-2026-002", "EVT-2026-001"))

    def test_missing_number_goes_to_manual_review(self):
        res = match_items_to_participants(
            [_make_item(licence="123456", order_id=110)],
            self.participants, prix_attendu=10.0, no_competition="EVT-2026-001"
        )
        # PAS de mise à jour automatique : le paiement part en correction manuelle
        self.assertEqual(res["updates"], [])
        self.assertEqual(len(res["manual_review"]), 1)
        entry = res["manual_review"][0]
        self.assertEqual(entry["adherent_id"], 1)        # pré-sélectionné via la licence
        self.assertEqual(entry["montant"], 10.0)
        self.assertEqual(entry["valeur_champ"], "")
        self.assertIn("competition_manquante", [a["type"] for a in res["anomalies"]])
        self.assertEqual(res["stats"]["nb_manual_review"], 1)

    def test_wrong_number_goes_to_manual_review(self):
        item = _make_item(licence="123456", order_id=111)
        item["customFields"].append({"name": "Compétition concernée", "answer": "EVT-2026-002"})
        res = match_items_to_participants(
            [item], self.participants, prix_attendu=10.0, no_competition="EVT-2026-001"
        )
        self.assertEqual(res["updates"], [])
        self.assertEqual(res["manual_review"][0]["valeur_champ"], "EVT-2026-002")
        self.assertIn("competition_ecartee", [a["type"] for a in res["anomalies"]])

    def test_correct_number_applies_payment(self):
        item = _make_item(licence="123456", order_id=112)
        item["customFields"].append(
            {"name": "Compétition concernée", "value": "Compétition n° EVT-2026-001"}
        )
        res = match_items_to_participants(
            [item], self.participants, prix_attendu=10.0, no_competition="EVT-2026-001"
        )
        self.assertEqual(res["updates"], [(1, 10.0)])
        self.assertEqual(res["manual_review"], [])

    def test_check_skipped_without_expected_number(self):
        # id_ffme vide en base : le contrôle est désactivé (comportement historique)
        res = match_items_to_participants(
            [_make_item(licence="123456", order_id=113)],
            self.participants, prix_attendu=10.0, no_competition=""
        )
        self.assertEqual(res["updates"], [(1, 10.0)])
        self.assertEqual(res["manual_review"], [])


class TestCompetitionRepository(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_main = tempfile.TemporaryDirectory()
        self.comp_db_path = os.path.join(self._tmp.name, "database_Competition.db")
        self.main_db_path = os.path.join(self._tmp_main.name, "database.db")
        # Sauvegarder les chemins d'origine : les tests ne doivent jamais fuiter
        # leur base temporaire vers les tests suivants (ordre de la suite).
        self._original_comp_path = cr.CompetitionRepository.get_db_path()
        self._original_main_path = SqliteRepository.get_db_path()
        cr.CompetitionRepository.set_db_path(self.comp_db_path)
        self.repo = cr.CompetitionRepository

    def tearDown(self):
        cr.CompetitionRepository.set_db_path(self._original_comp_path)
        SqliteRepository.set_db_path(self._original_main_path)
        self._tmp.cleanup()
        self._tmp_main.cleanup()

    def _seed_main_db(self):
        """Crée une base principale v2 minimale avec 2 compétiteurs + 1 loisir."""
        SqliteRepository.set_db_path(self.main_db_path)
        SqliteRepository.setup_database()
        conn = sqlite3.connect(self.main_db_path)
        conn.execute("INSERT OR IGNORE INTO seasons (name, is_active) VALUES ('2026-2027', 1)")
        conn.execute(
            "INSERT INTO users (id, last_name, first_name, last_name_key, first_name_key, "
            "birth_date, licence_ffme, email_primary, phone) VALUES "
            "(1, 'DUPONT', 'Jean', 'DUPONT', 'jean', '2010-05-01', '123456', 'jean@ex.fr', '0600000001'),"
            "(2, 'MARTIN', 'Léa', 'MARTIN', 'lea', '2011-03-12', '789012', 'lea@ex.fr', '0600000002'),"
            "(3, 'LOISIR', 'Bob', 'LOISIR', 'bob', '1990-01-01', '', 'bob@ex.fr', '0600000003')"
        )
        conn.execute("INSERT INTO orders (id, order_ref, season_id) VALUES (1, 'CMD1', 1), (2, 'CMD2', 1), (3, 'CMD3', 1)")
        conn.execute(
            "INSERT INTO purchases (order_id, user_id, tarif_name, amount, status) VALUES "
            "(1, 1, 'Compétition - U13/U15', 10.0, 'Validé'),"
            "(2, 2, 'Compétition - U13/U15', 10.0, 'Validé'),"
            "(3, 3, 'Enfants 2016-2018', 5.0, 'Validé')"
        )
        schema_v2.recreate_compat_view(conn.cursor())
        conn.commit()
        conn.close()
        # Rétablir le dépôt compétition (le setup principal peut avoir réinitialisé des états)
        cr.CompetitionRepository.set_db_path(self.comp_db_path)

    def test_schema_and_competition_crud(self):
        self.repo.setup_database()
        self.assertTrue(os.path.exists(self.comp_db_path))

        comp = Competition(id_ffme="EVT-2026-001", nom="Championnat U13",
                           date_competition="2026-11-15", prix=10.0)
        comp_id = self.repo.save_competition(comp)
        self.assertTrue(comp_id)

        loaded = self.repo.get_competition(comp_id)
        self.assertEqual(loaded.nom, "Championnat U13")
        self.assertEqual(loaded.statut, "en_preparation")
        self.assertEqual(loaded.prix, 10.0)

        loaded.statut = STATUT_EN_COURS
        self.repo.save_competition(loaded)
        self.assertEqual(self.repo.get_competition(comp_id).statut, "en_cours")

        self.repo.set_competition_status(comp_id, "close")
        self.assertEqual(self.repo.get_competition(comp_id).statut, "close")

        comps = self.repo.list_competitions()
        self.assertEqual(len(comps), 1)

        self.assertTrue(self.repo.delete_competition(comp_id))
        self.assertEqual(self.repo.list_competitions(), [])

    def test_participants_selection_and_payment(self):
        self.repo.setup_database()
        comp_id = self.repo.save_competition(Competition(nom="Test", prix=10.0))
        # L'instantané adhérents est vide ici : l'insertion directe simule la synchro
        conn = self.repo.get_connection()
        conn.execute("INSERT INTO adherents (id, nom, prenom, num_licence, tarif) VALUES (1,'DUPONT','Jean','123456','Compétition - U13')")
        conn.execute("INSERT INTO adherents (id, nom, prenom, num_licence, tarif) VALUES (2,'MARTIN','Léa','789012','Compétition - U15')")
        conn.execute("INSERT INTO adherents (id, nom, prenom, num_licence, tarif) VALUES (3,'LOISIR','Bob','','Enfants')")
        conn.commit()
        conn.close()

        group = self.repo.list_adherents(competition_only=True)
        self.assertEqual(len(group), 2)

        n = self.repo.load_competition_group_into(comp_id)
        self.assertEqual(n, 2)

        participants = self.repo.list_participants(comp_id)
        self.assertEqual(len(participants), 2)
        self.assertTrue(all(p.selectionne for p in participants))

        # Bascule Oui/Non
        self.repo.set_selection(comp_id, 1, False)
        p1 = [p for p in self.repo.list_participants(comp_id) if p.adherent_id == 1][0]
        self.assertFalse(p1.selectionne)
        self.repo.set_selection(comp_id, 1, True)

        # Ajout hors groupe via recherche étendue
        self.repo.add_participant(comp_id, 3)
        self.assertEqual(len(self.repo.list_participants(comp_id)), 3)

        # Paiement
        self.repo.set_payment_status(comp_id, 3, "en_attente")
        self.repo.apply_helloasso_payment(comp_id, 3, 9.5, "2026-11-16 10:00:00", order_ref="CMD99")
        p3 = [p for p in self.repo.list_participants(comp_id) if p.adherent_id == 3][0]
        self.assertEqual(p3.statut_paiement, "paye")
        self.assertEqual(p3.montant_paye, 9.5)
        self.assertEqual(p3.date_synchro_helloasso, "2026-11-16 10:00:00")
        self.assertEqual(p3.commande_helloasso, "CMD99")

        # Suppression
        self.assertTrue(self.repo.remove_participant(comp_id, 3))
        self.assertEqual(len(self.repo.list_participants(comp_id)), 2)

    def test_migration_commande_helloasso(self):
        """Une base ancienne sans la colonne commande_helloasso est migrée à l'ouverture."""
        self.repo.setup_database()
        conn = self.repo.get_connection()
        conn.executescript(
            """DROP TABLE participants;
               CREATE TABLE participants (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   competition_id INTEGER NOT NULL,
                   adherent_id INTEGER NOT NULL,
                   selectionne INTEGER DEFAULT 0,
                   statut_paiement TEXT DEFAULT 'non_invite',
                   date_synchro_helloasso TEXT DEFAULT '',
                   montant_paye REAL DEFAULT 0.0,
                   UNIQUE(competition_id, adherent_id)
               );"""
        )
        conn.commit()
        conn.close()
        self.repo.setup_database(force=True)
        conn = self.repo.get_connection()
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(participants)").fetchall()}
        finally:
            conn.close()
        self.assertIn("commande_helloasso", cols)

    def test_sync_adherents_from_main(self):
        self._seed_main_db()
        self.repo.setup_database()
        report = self.repo.sync_adherents_from_main("2026-2027")
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["imported"], 3)

        adherents = self.repo.list_adherents()
        self.assertEqual(len(adherents), 3)
        dupont = [a for a in adherents if a["nom"] == "DUPONT"][0]
        self.assertEqual(dupont["num_licence"], "123456")
        self.assertEqual(dupont["tarif"], "Compétition - U13/U15")

        # Idempotence : une seconde synchro met à jour sans dupliquer
        report2 = self.repo.sync_adherents_from_main("2026-2027")
        self.assertEqual(report2["imported"], 0)
        self.assertEqual(report2["updated"], 3)
        self.assertEqual(self.repo.count_adherents(), 3)

    def test_planning_groups_mirror(self):
        """Le miroir planning_groups (pour la page web) est rempli depuis database.db."""
        self._seed_main_db()
        conn = sqlite3.connect(self.main_db_path)
        conn.execute("INSERT INTO planning (id, groupe, jour, horaires, helloasso_tarifs) VALUES "
                     "(1,'Compétition - U13','mercredi','18h','[\"Compétition - U13/U15\"]'),"
                     "(2,'Autonome','lundi','20h','[\"Adultes autonomes\"]')")
        conn.commit()
        conn.close()
        report = self.repo.sync_adherents_from_main("2026-2027")
        self.assertEqual(report["errors"], [])
        mapping = self.repo.list_planning_groups()
        self.assertEqual(mapping["competition - u13/u15"], "Compétition - U13")
        self.assertEqual(mapping["adultes autonomes"], "Autonome")

    def test_bilan_pivot(self):
        self.repo.setup_database()
        conn = self.repo.get_connection()
        conn.execute("INSERT INTO adherents (id, nom, prenom, num_licence, tarif) VALUES (1,'DUPONT','Jean','123456','Compétition'), (2,'MARTIN','Léa','789012','Compétition')")
        conn.commit()
        conn.close()
        c1 = self.repo.save_competition(Competition(nom="Comp A", date_competition="2026-11-15", prix=10.0))
        c2 = self.repo.save_competition(Competition(nom="Comp B", date_competition="2027-02-20", prix=12.0))
        for a in (1, 2):
            self.repo.add_participant(c1, a)
            self.repo.add_participant(c2, a)
        self.repo.apply_helloasso_payment(c1, 1, 10.0)
        self.repo.set_payment_status(c1, 2, "en_attente")

        bilan = self.repo.get_bilan("2026-2027")
        self.assertEqual(len(bilan["competitions"]), 2)
        self.assertEqual(len(bilan["students"]), 2)
        self.assertEqual(bilan["participations"][(1, c1)], "paye")
        self.assertEqual(bilan["participations"][(2, c1)], "en_attente")
        # Saison inconnue → bilan vide
        self.assertEqual(len(self.repo.get_bilan("1999-2000")["competitions"]), 0)

    def test_season_of_date(self):
        self.assertEqual(self.repo.season_of_date("2026-09-01"), "2026-2027")
        self.assertEqual(self.repo.season_of_date("2027-02-20"), "2026-2027")
        self.assertEqual(self.repo.season_of_date("2026-07-15"), "2025-2026")
        self.assertEqual(self.repo.season_of_date(""), "")


class TestSummarizeItems(unittest.TestCase):
    """Projection tabulaire des articles HelloAsso (valeurs à vide si absentes)."""

    def test_fields_left_blank_when_not_filled(self):
        item = {"id": 777, "state": "Validated", "amount": 1500, "date": "2026-09-16T10:00:00+02:00",
                "user": {"firstName": "Jean", "lastName": "DUPONT"},
                "order": {"id": 1912194742}, "customFields": []}
        rows = summarize_items([item])
        self.assertEqual(rows, [{
            "id_item": 777, "payeur": "DUPONT Jean", "montant": 15.0,
            "commande": "1912194742", "licence": "", "competition": "",
            "etat": "Validated", "date_item": "2026-09-16T10:00:00+02:00",
        }])

    def test_fields_extracted_when_present(self):
        item = {"id": 42, "state": "Processed", "amount": 1500,
                "user": {"firstName": "Léa", "lastName": "MARTIN"},
                "order": {"id": 42},
                "customFields": [
                    {"name": "Numéro de Licence FFME", "answer": "789012"},
                    {"name": "Compétition concernée", "answer": "EVT-2026-001"},
                ]}
        r = summarize_items([item])[0]
        self.assertEqual(r["licence"], "789012")
        self.assertEqual(r["competition"], "EVT-2026-001")

    def test_empty_input(self):
        self.assertEqual(summarize_items(None), [])
        self.assertEqual(summarize_items([]), [])


class TestAutoLinkAndMirror(unittest.TestCase):
    """Miroir HelloAsso + liens article -> (compétition, adhérent)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._original_comp_path = cr.CompetitionRepository.get_db_path()
        cr.CompetitionRepository.set_db_path(os.path.join(self._tmp.name, "database_Competition.db"))
        self.repo = cr.CompetitionRepository
        self.repo.setup_database()
        conn = self.repo.get_connection()
        conn.execute("INSERT INTO adherents (id, nom, prenom, num_licence) VALUES (1,'DUPONT','Jean','123456'), (2,'MARTIN','Léa','789012')")
        conn.commit()
        conn.close()
        self.c1 = self.repo.save_competition(Competition(id_ffme="EVT-2026-001", nom="Coupe du Rhône", date_competition="2026-09-26", prix=15.0))
        self.c2 = self.repo.save_competition(Competition(id_ffme="EVT-2026-002", nom="Championnat", date_competition="2026-11-14", prix=15.0))
        self.comps = [{"id": c.id, "id_ffme": c.id_ffme, "nom": c.nom}
                      for c in self.repo.list_competitions()]
        self.adherents = self.repo.list_adherents()

    def tearDown(self):
        cr.CompetitionRepository.set_db_path(self._original_comp_path)
        self._tmp.cleanup()

    @staticmethod
    def _item(id_item, etat="Validated", licence="", competition="", payeur="DUPONT Jean"):
        return {"id_item": id_item, "payeur": payeur, "montant": 15.0,
                "commande": str(1000 + id_item), "licence": licence,
                "competition": competition, "etat": etat, "date_item": "2026-09-16"}

    def test_auto_link_by_champ_then_licence(self):
        from domain.competition_matching import auto_link_items
        items = [
            self._item(1, licence="123456", competition="EVT-2026-001"),
            self._item(2, licence="789012", competition="Championnat EVT-2026-002"),
        ]
        links = auto_link_items(items, self.comps, self.adherents)
        self.assertEqual(links[1], {"competition_id": self.c1, "adherent_id": 1, "source": "auto"})
        self.assertEqual(links[2], {"competition_id": self.c2, "adherent_id": 2, "source": "auto"})

    def test_auto_link_no_competition_skipped(self):
        from domain.competition_matching import auto_link_items
        # champ vide ou inconnu : pas de lien automatique (rattachement manuel requis)
        items = [self._item(3, licence="123456", competition=""),
                 self._item(4, licence="123456", competition="Compétition inconnue")]
        links = auto_link_items(items, self.comps, self.adherents)
        self.assertEqual(links, {})

    def test_auto_link_preserves_manual_and_ignores_invalid_state(self):
        from domain.competition_matching import auto_link_items
        items = [self._item(5, licence="123456", competition="EVT-2026-001"),
                 self._item(6, licence="789012", competition="EVT-2026-002"),
                 self._item(7, etat="Refunded", licence="789012", competition="EVT-2026-001")]
        links = auto_link_items(items, self.comps, self.adherents, {5: "manuel"})
        # 5 : manuel préservé ; 6 : auto ; 7 : état non payé ignoré
        self.assertEqual(list(links.keys()), [6])

    def test_mirror_upsert_and_manual_link_persistence(self):
        items = [self._item(10, licence="123456", competition="EVT-2026-001")]
        self.assertEqual(self.repo.sync_helloasso_mirror(items, [{"id": 10}], "competition-saison"), 1)
        # Lien manuel posé puis nouvelle synchro : le lien doit survivre
        self.repo.set_item_link(10, self.c1, 1, source="manuel")
        self.repo.sync_helloasso_mirror(items, [{"id": 10}], "competition-saison")
        links = self.repo.list_helloasso_links()
        self.assertEqual(links[10]["source"], "manuel")
        self.assertEqual(links[10]["competition_id"], self.c1)

        # replace_auto_links écrase les auto, jamais les manuels
        from domain.competition_matching import auto_link_items
        other = [self._item(11, licence="789012", competition="EVT-2026-002")]
        self.repo.sync_helloasso_mirror(other, [{"id": 11}], "competition-saison")
        auto = auto_link_items(other, self.comps, self.adherents, self.repo.list_helloasso_links())
        self.repo.replace_auto_links(auto)
        links = self.repo.list_helloasso_links()
        self.assertEqual(links[10]["source"], "manuel")
        self.assertEqual(links[11]["source"], "auto")

    def test_apply_links_to_participants_aggregates(self):
        items = [self._item(20, licence="123456", competition="EVT-2026-001"),
                 self._item(21, licence="123456", competition="EVT-2026-001")]
        self.repo.sync_helloasso_mirror(items, [{"id": 20}, {"id": 21}], "slug")
        self.repo.set_item_link(20, self.c1, 1, source="manuel")
        self.repo.set_item_link(21, self.c1, 1, source="manuel")
        applied = self.repo.apply_links_to_participants()
        self.assertEqual(applied, 1)
        parts = [p for p in self.repo.list_participants(self.c1) if p.adherent_id == 1]
        self.assertEqual(len(parts), 1)
        p = parts[0]
        self.assertEqual(p.statut_paiement, "paye")
        self.assertEqual(p.montant_paye, 30.0)          # cumul des 2 articles
        self.assertEqual(p.commande_helloasso, "1020, 1021")

    def test_unlinked_items_listing(self):
        items = [self._item(30, licence="123456", competition=""),          # pas de lien
                 self._item(31, licence="", competition="EVT-2026-001"),    # compétition sans adhérent
                 self._item(32, etat="Waiting", competition="")]            # état non payé : ignoré
        self.repo.sync_helloasso_mirror(items, [{"id": 30}, {"id": 31}, {"id": 32}], "slug")
        unlinked = self.repo.list_unlinked_items()
        ids = [u["id_item"] for u in unlinked]
        self.assertIn(30, ids)
        self.assertIn(31, ids)
        self.assertNotIn(32, ids)
        # pré-sélection adhérent via licence pour l'article 30
        u30 = [u for u in unlinked if u["id_item"] == 30][0]
        self.assertEqual(u30["adherent_id"], 1)


class TestMatchAdherentByName(unittest.TestCase):
    """Pré-sélection du compétiteur par nom + prénom (ordre inversé accepté)."""

    ADHERENTS = [
        {"id": 1, "nom": "FANJAT", "prenom": "Gabin"},
        {"id": 2, "nom": "LOMBARD", "prenom": "Théo"},
        {"id": 3, "nom": "POLSNIELLI ROUSSET", "prenom": "Julie"},
    ]

    def test_exact_and_case_insensitive(self):
        from domain.competition_matching import match_adherent_by_name
        self.assertEqual(match_adherent_by_name("FANJAT Gabin", self.ADHERENTS), 1)
        self.assertEqual(match_adherent_by_name("fanjat gabin", self.ADHERENTS), 1)

    def test_reversed_order(self):
        from domain.competition_matching import match_adherent_by_name
        self.assertEqual(match_adherent_by_name("Gabin FANJAT", self.ADHERENTS), 1)

    def test_composed_names_and_no_match(self):
        from domain.competition_matching import match_adherent_by_name
        self.assertEqual(match_adherent_by_name("POLSNIELLI ROUSSET Julie", self.ADHERENTS), 3)
        self.assertIsNone(match_adherent_by_name("Inconnu Total", self.ADHERENTS))
        self.assertIsNone(match_adherent_by_name("", self.ADHERENTS))
        self.assertIsNone(match_adherent_by_name("FANJAT Gabin", None))


class TestGroupForTarif(unittest.TestCase):
    """Rapprochement tarif -> groupe de créneau (regroupement de la liste Compétiteurs)."""

    PLANNING = [
        {"groupe": "Compétition - U11-U13", "helloasso_tarifs": ["Compétition U11-U13 - jeunes nés 2014-2016"]},
        {"groupe": "Compétition - U15-U17", "helloasso_tarifs": ["Compétition U15-U17"]},
        {"groupe": "Autonome - adultes", "helloasso_tarifs": ["Adultes autonomes"]},
    ]

    def test_group_found(self):
        from domain.planning_groups import group_for_tarif
        self.assertEqual(group_for_tarif("Compétition U11-U13 - jeunes nés 2014-2016", self.PLANNING),
                         "Compétition - U11-U13")
        self.assertEqual(group_for_tarif("ADULTES AUTONOMES", self.PLANNING), "Autonome - adultes")

    def test_group_not_found_or_empty(self):
        from domain.planning_groups import group_for_tarif
        self.assertEqual(group_for_tarif("Tarif inconnu", self.PLANNING), "")
        self.assertEqual(group_for_tarif("", self.PLANNING), "")
        self.assertEqual(group_for_tarif("Adultes autonomes", None), "")


if __name__ == "__main__":
    unittest.main()
