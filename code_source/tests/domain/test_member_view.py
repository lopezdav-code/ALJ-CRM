"""domain.member_view: the member list the web pages used to compute in the browser."""

import datetime
import unittest

from domain import member_view

PLANNING = [
    {"id": 2, "groupe": "Enfants 2015-2016", "categorie_age": "U11", "type": "Cours",
     "jour": "Mercredi", "horaires": "14h-15h30", "helloasso_tarifs": '["Enfant mercredi", "Commun"]'},
    {"id": 1, "groupe": "Adultes", "categorie_age": "", "type": "Loisir",
     "jour": "Lundi", "horaires": "19h-21h", "helloasso_tarifs": ["Adulte lundi", "Commun"]},
    {"id": 3, "groupe": "", "helloasso_tarifs": ["Orphelin"]},
]


def row(**over):
    base = {"user_id": 7, "purchase_id": 70, "last_name": "Martin", "first_name": "Léo",
            "birth_date": "2015-09-02", "gender": "m", "tarif_name": "Enfant mercredi",
            "amount": 150.0, "status": "validated", "payer_first_name": "Claire",
            "payer_last_name": "MARTIN", "season_name": "2026-2027", "phone": None}
    base.update(over)
    return base


class TestMemberView(unittest.TestCase):

    def test_tariff_in_two_groups_belongs_to_first_row_by_id(self):
        slots = member_view.tarif_slots(PLANNING)
        self.assertEqual(slots["commun"]["groupe"], "Adultes")        # id 1 before id 2
        self.assertEqual(slots["enfant mercredi"]["groupe"], "Enfants 2015-2016")
        self.assertNotIn("orphelin", slots)                            # row without group

    def test_creneaux(self):
        groups = member_view.creneaux(PLANNING)
        self.assertEqual([g["groupe"] for g in groups], ["Adultes", "Enfants 2015-2016"])
        self.assertEqual(groups[0]["tarifs"], ["Adulte lundi", "Commun"])
        self.assertEqual(groups[1]["categorie_age"], "U11")

    def test_member_row(self):
        m = member_view.member_row(row(), member_view.tarif_slots(PLANNING), datetime.date(2026, 9, 1))
        self.assertEqual((m["user_id"], m["purchase_id"]), (7, 70))
        self.assertEqual(m["age"], 10)                                # 11 on 2 September only
        self.assertEqual(m["gender"], "Homme")
        self.assertEqual(m["status_norm"], "Validé")
        self.assertEqual(m["payer"], "Claire MARTIN")
        self.assertEqual((m["creneau_groupe"], m["categorie"], m["creneau_details"]),
                         ("Enfants 2015-2016", "U11", "Mercredi 14h-15h30"))
        self.assertEqual(m["phone"], "")                               # None -> ""
        self.assertEqual((m["last_name"], m["first_name"]), ("MARTIN", "Léo"))

    def test_member_without_slot_or_birth_date(self):
        m = member_view.member_row(row(tarif_name="Inconnu", birth_date=""), {}, datetime.date(2026, 9, 1))
        self.assertEqual((m["creneau_groupe"], m["categorie"], m["creneau_details"], m["age"]), ("", "", "", None))

    def test_category_falls_back_to_type(self):
        m = member_view.member_row(row(tarif_name="Adulte lundi"), member_view.tarif_slots(PLANNING),
                                   datetime.date(2026, 9, 1))
        self.assertEqual(m["categorie"], "Loisir")

    def test_build_members_sorted_and_aged_at_season_start(self):
        members = member_view.build_members(
            [row(last_name="Zola"), row(last_name="élan", birth_date="2000-09-01"), row(last_name="Durand")],
            PLANNING, "2025-2026")
        self.assertEqual([m["last_name"] for m in members], ["DURAND", "ÉLAN", "ZOLA"])
        self.assertEqual(members[1]["age"], 25)                        # at 2025-09-01

    def test_formatters(self):
        """Same output as fmtLastName / fmtFirstName / fmtCity / fmtPhone (alj-members.js)."""
        self.assertEqual(member_view.fmt_last_name(" de lima ferreira "), "DE LIMA FERREIRA")
        self.assertEqual(member_view.fmt_first_name("JEAN-PIERRE"), "Jean-Pierre")
        self.assertEqual(member_view.fmt_first_name("marie claire"), "Marie Claire")
        self.assertEqual(member_view.fmt_city("CHARVIEU-CHAVAGNEUX"), "Charvieu-Chavagneux")
        self.assertEqual(member_view.fmt_city("VILLETTE  D’ANTHON"), "Villette d'Anthon")
        self.assertEqual(member_view.fmt_city("de jonage"), "De Jonage")      # first word keeps its capital
        self.assertEqual(member_view.fmt_phone("+33619984329"), "06 19 98 43 29")
        self.assertEqual(member_view.fmt_phone("619984329"), "06 19 98 43 29")
        self.assertEqual(member_view.fmt_phone("06.01.82.18.25"), "06 01 82 18 25")
        self.assertEqual(member_view.fmt_phone("123"), "123")
        self.assertEqual(member_view.fmt_phone(None), "")

    def test_member_row_passes_comments_and_passports(self):
        m = member_view.member_row(row(commentaires_correctif="Certificat papier", raw_passports="Orange"),
                                   {}, datetime.date(2026, 9, 1))
        self.assertEqual((m["commentaires_correctif"], m["raw_passports"], m["raw_diplomas"]),
                         ("Certificat papier", "Orange", ""))

    def test_normalizers(self):
        self.assertEqual(member_view.normalize_status(" Canceled "), "Annulé")
        self.assertEqual(member_view.normalize_status("Autre"), "Autre")
        self.assertEqual(member_view.normalize_gender("Féminin"), "Femme")


if __name__ == "__main__":
    unittest.main()
