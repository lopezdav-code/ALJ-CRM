"""Members as seen by the competition pages (Firestore `adherents` projection, read-only).

The full member records are served by the member routes (plan phase 2), not here.
"""

from typing import List

from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
from services.competition_store import storage


class CompetitionMemberService:

    @staticmethod
    @storage
    def list_members() -> List[dict]:
        return Repo.list_adherents()
