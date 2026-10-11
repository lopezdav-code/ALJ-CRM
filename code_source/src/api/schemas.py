"""Request bodies of the API routes used by the web front end (validated by FastAPI)."""

import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from domain.competition_models import (
    PAIEMENT_ANNULE_PERDU,
    PAIEMENT_ANNULE_REPORTE,
    STATUT_EN_PREPARATION,
    STATUTS_COMPETITION,
)

_ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})?$")
MAX_COACHES = 3  # the domain model stores coach1_id..coach3_id

# Cancellation choice for a participant who already paid -> payment status
CANCEL_MODES = {"perdu": PAIEMENT_ANNULE_PERDU, "reporte": PAIEMENT_ANNULE_REPORTE}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check_statut(value):
    if value is not None and value not in STATUTS_COMPETITION:
        raise ValueError(f"statut must be one of {', '.join(STATUTS_COMPETITION)}")
    return value


def _check_date(value):
    if value is not None and not _ISO_DATE.match(value):
        raise ValueError("date must be YYYY-MM-DD or empty")
    return value


class CompetitionCreate(_Body):
    nom: str = Field(min_length=1)
    id_ffme: str = ""
    date_competition: str = ""
    date_fin: str = ""
    prix: float = Field(0.0, ge=0)
    statut: str = STATUT_EN_PREPARATION
    coach_ids: List[int] = Field(default_factory=list, max_length=MAX_COACHES)
    helloasso_ref: str = ""
    # Pass-through fields of the bureau page, stored without validation (plan appendix B)
    lieu: Optional[str] = None
    type: Optional[str] = None

    _statut = field_validator("statut")(_check_statut)
    _dates = field_validator("date_competition", "date_fin")(_check_date)


class CompetitionUpdate(_Body):
    """Partial update: only the fields sent are changed."""
    nom: Optional[str] = Field(None, min_length=1)
    id_ffme: Optional[str] = None
    date_competition: Optional[str] = None
    date_fin: Optional[str] = None
    prix: Optional[float] = Field(None, ge=0)
    statut: Optional[str] = None
    coach_ids: Optional[List[int]] = Field(None, max_length=MAX_COACHES)
    helloasso_ref: Optional[str] = None
    lieu: Optional[str] = None
    type: Optional[str] = None

    _statut = field_validator("statut")(_check_statut)
    _dates = field_validator("date_competition", "date_fin")(_check_date)


class ParticipantAdd(_Body):
    adherent_id: int
    selectionne: bool = True


class ParticipantUpdate(_Body):
    selectionne: Optional[bool] = None
    present: Optional[bool] = None  # pass-through field (plan appendix B)


class ParticipantCancel(_Body):
    mode: str
    note: str = Field(min_length=1)

    @field_validator("mode")
    @classmethod
    def _mode(cls, value):
        if value not in CANCEL_MODES:
            raise ValueError(f"mode must be one of {', '.join(CANCEL_MODES)}")
        return value


class CoachIn(_Body):
    nom: str = Field(min_length=1)


class ItemLink(_Body):
    competition_id: Optional[int] = None
    adherent_id: Optional[int] = None
    commentaire: str = ""


class ItemIgnore(_Body):
    ignore: bool
    motif: str = ""
    commentaire: str = ""
