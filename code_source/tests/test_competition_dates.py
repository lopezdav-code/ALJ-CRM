import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from domain.competition_models import Competition
from domain.utils import format_periode


def test_periode_un_jour_ou_deux():
    assert format_periode("2026-03-12") == "12/03/2026"
    assert format_periode("2026-03-12", "2026-03-12") == "12/03/2026"
    assert format_periode("2026-03-12", "") == "12/03/2026"
    assert format_periode("2026-03-12", "2026-03-13") == "12/03/2026 au 13/03/2026"
    assert format_periode("", "2026-03-13") == ""


def test_date_fin_modele_roundtrip_et_ancien_format():
    c = Competition.from_row({"id": 1, "nom": "X", "date_competition": "2026-03-12", "date_fin": "2026-03-13"})
    assert c.to_dict()["date_fin"] == "2026-03-13"
    ancien = Competition.from_row({"id": 2, "nom": "Y", "date_competition": "2026-03-12"})
    assert ancien.date_fin == ""
