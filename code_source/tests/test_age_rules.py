"""Tests unitaires des règles de contrôle d'âge (bornes de naissance par groupe)."""
import datetime
import unittest
import sys
import os

# Ajustement du chemin d'import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from domain.age_rules import (
    check_age_conflict,
    extract_birth_years,
    get_season_start_date,
    parse_birth_date,
    resolve_birth_bounds,
    bounds_from_tarif_name,
    find_planning_item_for_tarif,
    is_youth_group,
    age_at,
)


PLANNING_ITEM_COMPET = {
    "groupe": "Compétition - U15-U17-U19",
    "type": "compétition",
    "helloasso_tarifs": ["Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014"],
    "naissance_min": "2011-01-01",
    "naissance_max": "2014-12-31",
}

PLANNING_ITEM_COLLEGE = {
    "groupe": "Loisir - Collège (Groupe A)",
    "type": "cours",
    "helloasso_tarifs": ["Loisir collège - jeunes nés en 2012, 2013, 2014, 2015 - lundi 18h30"],
    "naissance_min": "",
    "naissance_max": "",
}

PLANNING_ITEM_ADULTES = {
    "groupe": "Autonome",
    "type": "autonome",
    "helloasso_tarifs": ["Adultes autonomes", "Jeunes Adultes autonomes - nés entre 2001 et 2008"],
    "naissance_min": "",
    "naissance_max": "",
}

PLANNING_ITEM_ADULTE_DEBUTANT = {
    "groupe": "Loisir - Adultes débutants",
    "type": "cours",
    "helloasso_tarifs": ["Cours Adultes débutants"],
    "naissance_min": "",
    "naissance_max": "",
}


class TestParsingUtils(unittest.TestCase):
    def test_get_season_start_date(self):
        self.assertEqual(get_season_start_date("2026-2027"), datetime.date(2026, 9, 1))

    def test_parse_birth_date_formats(self):
        self.assertEqual(parse_birth_date("2012-08-20"), datetime.date(2012, 8, 20))
        self.assertEqual(parse_birth_date("20/08/2012"), datetime.date(2012, 8, 20))
        self.assertEqual(parse_birth_date("2012-08-20T00:00:00"), datetime.date(2012, 8, 20))
        self.assertIsNone(parse_birth_date(""))
        self.assertIsNone(parse_birth_date(None))
        self.assertIsNone(parse_birth_date("inconnu"))

    def test_age_at(self):
        ref = datetime.date(2026, 9, 1)
        self.assertEqual(age_at(datetime.date(2008, 8, 31), ref), 18)
        self.assertEqual(age_at(datetime.date(2008, 9, 2), ref), 17)
        self.assertEqual(age_at(datetime.date(2014, 5, 1), ref), 12)

    def test_extract_birth_years(self):
        self.assertEqual(
            extract_birth_years("Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014"),
            [2011, 2012, 2013, 2014],
        )
        self.assertEqual(
            extract_birth_years("Jeunes Adultes autonomes - nés entre 2001 et 2008"),
            [2001, 2008],
        )
        self.assertEqual(extract_birth_years("Cours Adultes débutants"), [])
        # Les horaires ne doivent pas être capturés comme des années
        self.assertEqual(extract_birth_years("cours 18h30 de 2026"), [2026])

    def test_bounds_from_tarif_name(self):
        bmin, bmax = bounds_from_tarif_name("Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014")
        self.assertEqual(bmin, datetime.date(2011, 1, 1))
        self.assertEqual(bmax, datetime.date(2014, 12, 31))

    def test_resolve_birth_bounds_prefers_planning_columns(self):
        bmin, bmax = resolve_birth_bounds(
            PLANNING_ITEM_COMPET, "Compétition U15 U17 U19- jeunes nés en 2009, 2010, 2011, 2012, 2013, 2014"
        )
        self.assertEqual(bmin, datetime.date(2011, 1, 1))
        self.assertEqual(bmax, datetime.date(2014, 12, 31))

    def test_resolve_birth_bounds_falls_back_to_tarif(self):
        bmin, bmax = resolve_birth_bounds(PLANNING_ITEM_COLLEGE, "Loisir collège - jeunes nés en 2012, 2013, 2014, 2015 - lundi 18h30")
        self.assertEqual(bmin, datetime.date(2012, 1, 1))
        self.assertEqual(bmax, datetime.date(2015, 12, 31))

    def test_find_planning_item_for_tarif(self):
        planning = [PLANNING_ITEM_COMPET, PLANNING_ITEM_ADULTES]
        item = find_planning_item_for_tarif("Adultes autonomes", planning)
        self.assertEqual(item["groupe"], "Autonome")
        self.assertIsNone(find_planning_item_for_tarif("Tarif inexistant", planning))


class TestYouthGroupDetection(unittest.TestCase):
    season_start = datetime.date(2026, 9, 1)

    def test_college_is_youth(self):
        self.assertTrue(is_youth_group(PLANNING_ITEM_COLLEGE, "Loisir collège - jeunes nés en 2012, 2013, 2014, 2015", season_start=self.season_start))

    def test_adult_groups_are_not_youth(self):
        self.assertFalse(is_youth_group(PLANNING_ITEM_ADULTES, "Adultes autonomes", season_start=self.season_start))
        self.assertFalse(is_youth_group(PLANNING_ITEM_ADULTE_DEBUTANT, "Cours Adultes débutants", season_start=self.season_start))

    def test_jeunes_adultes_is_not_youth(self):
        # « Jeunes Adultes » = adultes de 18 ans et plus : ne doit pas être un groupe enfants
        self.assertFalse(is_youth_group(PLANNING_ITEM_ADULTES, "Jeunes Adultes autonomes - nés entre 2001 et 2008", season_start=self.season_start))

    def test_youth_by_bounds(self):
        # Groupe sans mot-clé jeune mais dont l'éligible le plus âgé est mineur
        item = {"groupe": "Groupe X", "naissance_min": "2012-01-01", "naissance_max": "2014-12-31"}
        self.assertTrue(is_youth_group(item, "", season_start=self.season_start))


class TestAgeConflicts(unittest.TestCase):
    def test_adult_in_college_group_is_conflict(self):
        messages = check_age_conflict(
            "20/03/1990", "Loisir collège - jeunes nés en 2012, 2013, 2014, 2015 - lundi 18h30",
            PLANNING_ITEM_COLLEGE, season="2026-2027",
        )
        self.assertTrue(any("Adulte" in m for m in messages))
        self.assertTrue(any("hors bornes" in m or "borne du groupe" in m for m in messages))

    def test_adult_in_adult_group_is_ok(self):
        messages = check_age_conflict("12/01/1985", "Adultes autonomes", PLANNING_ITEM_ADULTES, season="2026-2027")
        self.assertEqual(messages, [])

    def test_young_child_in_adult_only_group_not_flagged(self):
        # Hors périmètre demandé : pas de conflit déclaré pour un tarif adulte sans bornes
        messages = check_age_conflict("10/06/2015", "Cours Adultes débutants", PLANNING_ITEM_ADULTE_DEBUTANT, season="2026-2027")
        self.assertEqual(messages, [])

    def test_correct_age_in_competition_group_is_ok(self):
        messages = check_age_conflict(
            "15/04/2012", "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014",
            PLANNING_ITEM_COMPET, season="2026-2027",
        )
        self.assertEqual(messages, [])

    def test_too_young_for_competition_group(self):
        messages = check_age_conflict(
            "05/06/2016", "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014",
            PLANNING_ITEM_COMPET, season="2026-2027",
        )
        self.assertTrue(any("postérieur à la borne" in m for m in messages))

    def test_too_old_for_competition_group(self):
        messages = check_age_conflict(
            "05/06/2008", "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014",
            PLANNING_ITEM_COMPET, season="2026-2027",
        )
        self.assertTrue(any("antérieur à la borne" in m for m in messages))

    def test_missing_birth_date_is_flagged(self):
        messages = check_age_conflict("", "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014", PLANNING_ITEM_COMPET)
        self.assertEqual(len(messages), 1)
        self.assertIn("Date de naissance absente", messages[0])

    def test_unmapped_tarif_uses_tarif_name_years(self):
        # Aucun créneau associé : le contrôle se replie sur les années du libellé tarif
        messages = check_age_conflict(
            "20/03/1990", "Loisir collège - jeunes nés en 2012, 2013, 2014, 2015 - lundi 18h30",
            None, season="2026-2027",
        )
        self.assertTrue(any("Adulte" in m for m in messages))
        self.assertTrue(any("borne du groupe" in m for m in messages))

    def test_adult_fallback_on_name_when_no_bounds(self):
        # Groupe collège sans bornes configurées : la règle adulte s'applique via le nom
        messages = check_age_conflict("20/03/1990", "Cours inconnu", PLANNING_ITEM_COLLEGE, season="2026-2027")
        self.assertTrue(any("Adulte" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
