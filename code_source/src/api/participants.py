"""Participants of a competition (array embedded in the competition document)."""

from fastapi import APIRouter

from api.schemas.participants import CANCEL_MODES, ParticipantAdd, ParticipantCancel, ParticipantUpdate
from services.participant_service import ParticipantService as Service

router = APIRouter(prefix="/api/competitions/{competition_id}")


@router.post("/participants")
def add_participant(competition_id: int, body: ParticipantAdd):
    return Service.add_participant(competition_id, body.adherent_id, body.selectionne)


@router.patch("/participants/{adherent_id}")
def update_participant(competition_id: int, adherent_id: int, body: ParticipantUpdate):
    """409 `already_paid` when unselecting a participant who paid: the page then asks the
    coach whether the money is lost or carried over (cancel route)."""
    return Service.update_participant(competition_id, adherent_id,
                                      selectionne=body.selectionne, present=body.present)


@router.post("/participants/{adherent_id}/cancel")
def cancel_participant(competition_id: int, adherent_id: int, body: ParticipantCancel):
    return Service.cancel_participant(competition_id, adherent_id, CANCEL_MODES[body.mode], body.note)


@router.delete("/participants/{adherent_id}")
def remove_participant(competition_id: int, adherent_id: int):
    return Service.remove_participant(competition_id, adherent_id)


@router.post("/load-group")
def load_competition_group(competition_id: int):
    added, competition = Service.load_competition_group(competition_id)
    return {"added": added, "competition": competition}
