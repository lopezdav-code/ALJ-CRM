"""Bodies of the HelloAsso item routes (api.helloasso_items)."""

from typing import Optional

from api.schemas.base import RequestBody


class ItemLink(RequestBody):
    competition_id: Optional[int] = None
    adherent_id: Optional[int] = None
    commentaire: str = ""


class ItemIgnore(RequestBody):
    ignore: bool
    motif: str = ""
    commentaire: str = ""
