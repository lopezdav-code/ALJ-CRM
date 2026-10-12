"""Members as seen by the competition pages (read-only projection)."""

from fastapi import APIRouter, Request

from api.responses import json_with_etag
from services.competition_member_service import CompetitionMemberService as Service

router = APIRouter(prefix="/api/competition-members")


@router.get("")
def list_competition_members(request: Request):
    return json_with_etag(request, Service.list_members())
