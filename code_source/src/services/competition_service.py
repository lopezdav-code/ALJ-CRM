"""Competitions: list, create, partial update, delete, archive.

Over CompetitionFirestoreRepository (shared with the desktop app and the HelloAsso
webhook, so all three write with the same rules). Knows nothing about HTTP: failures are
raised as services.errors.
"""

import datetime
from typing import Any, Dict, List

from domain.competition_models import Competition
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
from services.competition_store import cached_competitions, competition_not_found, storage, write

# Fields stored as given, outside the domain model (plan appendix B)
PASS_THROUGH_FIELDS = ("lieu", "type")
COMPETITION_FIELDS = ("nom", "id_ffme", "date_competition", "date_fin", "prix", "statut",
                      "helloasso_ref")


def _apply_coaches(comp: Competition, coach_ids):
    ids = list(coach_ids) + [None] * 3
    comp.coach1_id, comp.coach2_id, comp.coach3_id = ids[0], ids[1], ids[2]


def _extra(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {k: fields[k] for k in PASS_THROUGH_FIELDS if k in fields}


class CompetitionService:

    @staticmethod
    @storage
    def list_competitions() -> List[dict]:
        return cached_competitions(Repo.list_competition_docs)

    @staticmethod
    @write
    def create_competition(fields: Dict[str, Any]) -> dict:
        """`fields`: validated body (api.schemas.competitions.CompetitionCreate)."""
        comp = Competition(**{k: fields[k] for k in COMPETITION_FIELDS if k in fields})
        _apply_coaches(comp, fields.get("coach_ids") or [])
        new_id = Repo.save_competition(comp, _extra(fields))
        return Repo.get_competition_doc(new_id)

    @staticmethod
    @write
    def update_competition(competition_id: int, fields: Dict[str, Any]) -> dict:
        """Partial update: only the fields given are changed (participants untouched)."""
        comp = Repo.get_competition(competition_id)
        if comp is None:
            raise competition_not_found()
        for field in COMPETITION_FIELDS:
            if fields.get(field) is not None:
                setattr(comp, field, fields[field])
        if "coach_ids" in fields:
            _apply_coaches(comp, fields["coach_ids"] or [])
        Repo.save_competition(comp, _extra(fields))
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @write
    def delete_competition(competition_id: int) -> None:
        if not Repo.delete_competition(competition_id):
            raise competition_not_found()

    @staticmethod
    @write
    def archive_past_competitions() -> List[int]:
        """Closes the competitions that are over; returns their ids."""
        return Repo.archive_past_competitions(datetime.date.today().isoformat())
