"""Membership seasons (SQLite cache of the crm_* collections).

Knows nothing about HTTP: failures are raised as services.errors.
"""

from typing import Dict, List

from infrastructure.sqlite_repository import SqliteRepository


class SeasonService:

    @staticmethod
    def list_seasons() -> Dict[str, object]:
        """{seasons: names most recent first, active: the active season}. Without a season
        flagged active, the most recent one is."""
        seasons: List[dict] = SqliteRepository.list_seasons()
        names = [s["name"] for s in seasons]
        active = next((s["name"] for s in seasons if s["is_active"]), names[0] if names else "")
        return {"seasons": names, "active": active}
