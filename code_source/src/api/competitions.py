"""Competitions: list, create, partial update, delete, archive.

Controllers in src/api handle HTTP in and out only: business rules are in src/services,
whose errors become HTTP errors in api.responses.service_error_handler. Roles are checked
by the auth middleware (infrastructure.api_auth.required_role): reads are open to
readonly, writes need coach.
"""

from fastapi import APIRouter, Request

from api.responses import SUCCESS, json_with_etag
from api.schemas.competitions import CompetitionCreate, CompetitionUpdate
from services.competition_service import CompetitionService as Service

router = APIRouter(prefix="/api/competitions")


@router.get("")
def list_competitions(request: Request):
    return json_with_etag(request, Service.list_competitions())


@router.post("", status_code=201)
def create_competition(body: CompetitionCreate):
    return Service.create_competition(body.model_dump(exclude_none=True))


@router.patch("/{competition_id}")
def update_competition(competition_id: int, body: CompetitionUpdate):
    return Service.update_competition(competition_id, body.model_dump(exclude_unset=True))


@router.delete("/{competition_id}")
def delete_competition(competition_id: int):
    Service.delete_competition(competition_id)
    return SUCCESS


@router.post("/archive-past")
def archive_past_competitions():
    return {**SUCCESS, "archived": Service.archive_past_competitions()}
