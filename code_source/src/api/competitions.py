"""Competitions, participants, coaches and HelloAsso links (Firestore collections).

Controller: HTTP in and out only. Business rules are in services.competition_service; its
errors become HTTP errors in api.responses.service_error_handler. Roles are checked by the
auth middleware (infrastructure.api_auth.required_role): reads are open to readonly,
writes need coach.
"""

from fastapi import APIRouter, Request

from api.responses import json_with_etag
from api.schemas import (
    CANCEL_MODES,
    CoachIn,
    CompetitionCreate,
    CompetitionUpdate,
    ItemIgnore,
    ItemLink,
    ParticipantAdd,
    ParticipantCancel,
    ParticipantUpdate,
)
from services.competition_service import CompetitionService as Service

router = APIRouter()

SUCCESS = {"status": "success"}


# ---------------------------------------------------------------------------
# Competitions
# ---------------------------------------------------------------------------
@router.get("/api/competitions")
def list_competitions(request: Request):
    return json_with_etag(request, Service.list_competitions())


@router.post("/api/competitions", status_code=201)
def create_competition(body: CompetitionCreate):
    return Service.create_competition(body.model_dump(exclude_none=True))


@router.patch("/api/competitions/{competition_id}")
def update_competition(competition_id: int, body: CompetitionUpdate):
    return Service.update_competition(competition_id, body.model_dump(exclude_unset=True))


@router.delete("/api/competitions/{competition_id}")
def delete_competition(competition_id: int):
    Service.delete_competition(competition_id)
    return SUCCESS


@router.post("/api/competitions/archive-past")
def archive_past_competitions():
    return {**SUCCESS, "archived": Service.archive_past_competitions()}


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------
@router.post("/api/competitions/{competition_id}/participants")
def add_participant(competition_id: int, body: ParticipantAdd):
    return Service.add_participant(competition_id, body.adherent_id, body.selectionne)


@router.patch("/api/competitions/{competition_id}/participants/{adherent_id}")
def update_participant(competition_id: int, adherent_id: int, body: ParticipantUpdate):
    """409 `already_paid` when unselecting a participant who paid: the page then asks the
    coach whether the money is lost or carried over (cancel route)."""
    return Service.update_participant(competition_id, adherent_id,
                                      selectionne=body.selectionne, present=body.present)


@router.post("/api/competitions/{competition_id}/participants/{adherent_id}/cancel")
def cancel_participant(competition_id: int, adherent_id: int, body: ParticipantCancel):
    return Service.cancel_participant(competition_id, adherent_id, CANCEL_MODES[body.mode], body.note)


@router.delete("/api/competitions/{competition_id}/participants/{adherent_id}")
def remove_participant(competition_id: int, adherent_id: int):
    return Service.remove_participant(competition_id, adherent_id)


@router.post("/api/competitions/{competition_id}/load-group")
def load_competition_group(competition_id: int):
    added, competition = Service.load_competition_group(competition_id)
    return {"added": added, "competition": competition}


# ---------------------------------------------------------------------------
# Coaches
# ---------------------------------------------------------------------------
@router.get("/api/coaches")
def list_coaches(request: Request):
    return json_with_etag(request, Service.list_coaches())


@router.post("/api/coaches", status_code=201)
def create_coach(body: CoachIn):
    return {"id": Service.create_coach(body.nom), "nom": body.nom}


@router.put("/api/coaches/{coach_id}")
def update_coach(coach_id: int, body: CoachIn):
    Service.rename_coach(coach_id, body.nom)
    return {"id": coach_id, "nom": body.nom}


@router.delete("/api/coaches/{coach_id}")
def delete_coach(coach_id: int):
    Service.delete_coach(coach_id)
    return SUCCESS


# ---------------------------------------------------------------------------
# Members as seen by the competition pages
# ---------------------------------------------------------------------------
@router.get("/api/competition-members")
def list_competition_members(request: Request):
    return json_with_etag(request, Service.list_members())


# ---------------------------------------------------------------------------
# HelloAsso mirror: manual links and ignored items (coach only)
# ---------------------------------------------------------------------------
@router.get("/api/helloasso/items")
def list_helloasso_items(request: Request):
    return json_with_etag(request, Service.list_helloasso_items())


@router.put("/api/helloasso/items/{id_item}/link")
def link_helloasso_item(id_item: int, body: ItemLink):
    linked = Service.link_helloasso_item(id_item, body.competition_id, body.adherent_id,
                                         body.commentaire)
    return {**SUCCESS, "linked": linked}


@router.put("/api/helloasso/items/{id_item}/ignore")
def ignore_helloasso_item(id_item: int, body: ItemIgnore, request: Request):
    claims = getattr(request.state, "user", None) or {}
    Service.ignore_helloasso_item(id_item, body.ignore, body.motif, body.commentaire,
                                  by=str(claims.get("email") or ""))
    return SUCCESS
