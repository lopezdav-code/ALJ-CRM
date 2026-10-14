"""Participants of a competition (array embedded in the competition document).

Every write goes through the repository's optimistic lock (re-read and retried on a
concurrent change). Knows nothing about HTTP: failures are raised as services.errors.
"""

from typing import Optional, Tuple

from infrastructure.competition_firestore_repository import (
    CompetitionFirestoreRepository as Repo,
    ParticipantAlreadyPaid,
)
from services.competition_store import require_competition, write
from services.errors import Conflict, NotFound


class ParticipantService:

    @staticmethod
    @write
    def add_participant(competition_id: int, adherent_id: int, selectionne: bool) -> dict:
        require_competition(competition_id)
        Repo.add_participant(competition_id, adherent_id, selectionne)
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @write
    def update_participant(competition_id: int, adherent_id: int,
                           selectionne: Optional[bool] = None,
                           present: Optional[bool] = None) -> dict:
        """Unselecting a participant who paid is refused (Conflict `already_paid`): the
        coach must then choose whether the money is lost or carried over (cancel_participant)."""
        require_competition(competition_id)
        if selectionne is not None:
            try:
                Repo.set_selection(competition_id, adherent_id, selectionne, refuse_unselect_paid=True)
            except ParticipantAlreadyPaid as e:
                raise Conflict("Ce compétiteur a déjà payé : choisissez le sort de son paiement.",
                               "already_paid") from e
        if present is not None and not Repo.set_present(competition_id, adherent_id, present):
            raise NotFound("Compétiteur absent de cette compétition.")
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @write
    def record_manual_payment(competition_id: int, adherent_id: int, montant: float) -> dict:
        """Cheque or cash: the participant becomes selected and paid."""
        if not Repo.record_manual_payment(competition_id, adherent_id, montant):
            raise NotFound("Compétition ou compétiteur introuvable.")
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @write
    def cancel_participant(competition_id: int, adherent_id: int, payment_status: str,
                           note: str) -> dict:
        """`payment_status`: PAIEMENT_ANNULE_PERDU or PAIEMENT_ANNULE_REPORTE."""
        if not Repo.mark_cancelled(competition_id, adherent_id, payment_status, note):
            raise NotFound("Compétition ou compétiteur introuvable.")
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @write
    def remove_participant(competition_id: int, adherent_id: int) -> dict:
        if not Repo.remove_participant(competition_id, adherent_id):
            raise NotFound("Compétition ou compétiteur introuvable.")
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @write
    def load_competition_group(competition_id: int) -> Tuple[int, dict]:
        """Adds every member of the « Compétition » tariff not already listed (not invited).
        Returns (number added, competition)."""
        require_competition(competition_id)
        added = Repo.load_competition_group_into(competition_id)
        return added, Repo.get_competition_doc(competition_id)
