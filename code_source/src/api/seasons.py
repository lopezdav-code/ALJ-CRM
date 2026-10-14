"""Membership seasons (coach)."""

from fastapi import APIRouter, Request

from api.responses import json_with_etag
from services.season_service import SeasonService as Service

router = APIRouter(prefix="/api/seasons")


@router.get("")
def list_seasons(request: Request):
    return json_with_etag(request, Service.list_seasons())
