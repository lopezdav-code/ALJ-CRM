"""Bodies of the participant routes (api.participants)."""

from typing import Optional

from pydantic import Field, field_validator

from api.schemas.base import RequestBody
from domain.competition_models import PAIEMENT_ANNULE_PERDU, PAIEMENT_ANNULE_REPORTE

# Cancellation choice for a participant who already paid -> payment status
CANCEL_MODES = {"perdu": PAIEMENT_ANNULE_PERDU, "reporte": PAIEMENT_ANNULE_REPORTE}


class ParticipantAdd(RequestBody):
    adherent_id: int
    selectionne: bool = True


class ParticipantUpdate(RequestBody):
    selectionne: Optional[bool] = None
    present: Optional[bool] = None  # pass-through field (plan appendix B)


class ManualPayment(RequestBody):
    """Payment received outside HelloAsso (cheque, cash)."""
    montant: float = Field(gt=0)


class ParticipantCancel(RequestBody):
    mode: str
    note: str = Field(min_length=1)

    @field_validator("mode")
    @classmethod
    def _mode(cls, value):
        if value not in CANCEL_MODES:
            raise ValueError(f"mode must be one of {', '.join(CANCEL_MODES)}")
        return value
