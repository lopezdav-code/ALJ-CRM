"""Member list of the web pages (SQLite cache of the crm_* collections, one season at a time).

The fields the browser used to compute (age, slot group, category, normalized status…)
come from domain.member_view. Knows nothing about HTTP: failures are raised as
services.errors.
"""

from typing import Any, Dict, Optional

from domain import member_view
from infrastructure.sqlite_repository import SqliteRepository
from services.errors import NotFound
from services.season_service import SeasonService


class MemberService:

    @staticmethod
    def list_members(season: Optional[str] = None) -> Dict[str, Any]:
        """{season, members, creneaux} for `season` (the active season when not given)."""
        seasons = SeasonService.list_seasons()
        season = (season or "").strip() or seasons["active"]
        if season not in seasons["seasons"]:
            raise NotFound(f"Saison inconnue : {season}.")
        planning = SqliteRepository.load_planning_data(log_debug=False)
        rows = SqliteRepository.list_member_rows(season)
        return {
            "season": season,
            "members": member_view.build_members(rows, planning, season),
            "creneaux": member_view.creneaux(planning),
        }
