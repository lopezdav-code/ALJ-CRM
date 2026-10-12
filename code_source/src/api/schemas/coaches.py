"""Bodies of the coach routes (api.coaches)."""

from pydantic import Field

from api.schemas.base import RequestBody


class CoachIn(RequestBody):
    nom: str = Field(min_length=1)
