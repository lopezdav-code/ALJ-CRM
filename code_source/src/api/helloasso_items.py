"""HelloAsso mirror items: manual links and ignored items (coach only)."""

from fastapi import APIRouter, Request

from api.responses import SUCCESS, json_with_etag
from api.schemas.helloasso_items import ItemIgnore, ItemLink
from services.helloasso_item_service import HelloAssoItemService as Service

router = APIRouter(prefix="/api/helloasso/items")


@router.get("")
def list_helloasso_items(request: Request):
    return json_with_etag(request, Service.list_items())


@router.put("/{id_item}/link")
def link_helloasso_item(id_item: int, body: ItemLink):
    linked = Service.link_item(id_item, body.competition_id, body.adherent_id, body.commentaire)
    return {**SUCCESS, "linked": linked}


@router.put("/{id_item}/ignore")
def ignore_helloasso_item(id_item: int, body: ItemIgnore, request: Request):
    claims = getattr(request.state, "user", None) or {}
    Service.ignore_item(id_item, body.ignore, body.motif, body.commentaire,
                        by=str(claims.get("email") or ""))
    return SUCCESS
