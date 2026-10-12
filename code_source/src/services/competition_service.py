"""Competitions, participants, coaches and HelloAsso links (Firestore collections).

Business rules of the competition pages, over CompetitionFirestoreRepository (shared with
the desktop app and the HelloAsso webhook, so all three write with the same rules).
Knows nothing about HTTP: failures are raised as services.errors, Firestore errors
included, and the router maps them to responses.
"""

import datetime
import functools
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from domain.competition_models import Competition
from infrastructure.competition_firestore_repository import (
    CompetitionFirestoreRepository as Repo,
    ItemAlreadyLinked,
    ParticipantAlreadyPaid,
)
from infrastructure.firestore_client import FirestoreConflictError, FirestoreError
from services.errors import Conflict, InvalidRequest, NotFound, StorageUnavailable

# Fields stored as given, outside the domain model (plan appendix B)
PASS_THROUGH_FIELDS = ("lieu", "type")
COMPETITION_FIELDS = ("nom", "id_ffme", "date_competition", "date_fin", "prix", "statut",
                      "helloasso_ref")

# Cache to mutualize polling: every poll of every open page lists the whole collection.
# Writes through this service drop it at once; writes made elsewhere (desktop app,
# webhook, other instance) show up after CACHE_SECONDS.
CACHE_SECONDS = 5.0
_cache_lock = threading.Lock()
_competitions_cache: dict = {"at": 0.0, "docs": None}


def invalidate_cache():
    with _cache_lock:
        _competitions_cache["docs"] = None


def _storage(fn):
    """Turns Firestore failures into service errors."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FirestoreConflictError as e:
            raise Conflict("Données modifiées simultanément par un autre poste : réessayez.") from e
        except FirestoreError as e:
            print(f"❌ [CompetitionService] {type(e).__name__}: {e}")
            raise StorageUnavailable("Base Firestore indisponible, réessayez dans un instant.") from e
    return wrapper


def _write(fn):
    """A write: Firestore failures translated, and the list cache dropped even on failure
    (a write can fail after part of it was applied)."""
    wrapped = _storage(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return wrapped(*args, **kwargs)
        finally:
            invalidate_cache()
    return wrapper


def _competition_not_found() -> NotFound:
    return NotFound("Compétition introuvable.")


def _require_competition(competition_id: int) -> dict:
    doc = Repo.get_competition_doc(competition_id)
    if doc is None:
        raise _competition_not_found()
    return doc


def _apply_coaches(comp: Competition, coach_ids):
    ids = list(coach_ids) + [None] * 3
    comp.coach1_id, comp.coach2_id, comp.coach3_id = ids[0], ids[1], ids[2]


def _extra(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {k: fields[k] for k in PASS_THROUGH_FIELDS if k in fields}


class CompetitionService:

    # ------------------------------------------------------------------
    # Competitions
    # ------------------------------------------------------------------
    @staticmethod
    @_storage
    def list_competitions() -> List[dict]:
        with _cache_lock:
            if _competitions_cache["docs"] is None or time.time() - _competitions_cache["at"] > CACHE_SECONDS:
                _competitions_cache["docs"] = Repo.list_competition_docs()
                _competitions_cache["at"] = time.time()
            return _competitions_cache["docs"]

    @staticmethod
    @_write
    def create_competition(fields: Dict[str, Any]) -> dict:
        """`fields`: validated body (api.schemas.CompetitionCreate)."""
        comp = Competition(**{k: fields[k] for k in COMPETITION_FIELDS if k in fields})
        _apply_coaches(comp, fields.get("coach_ids") or [])
        new_id = Repo.save_competition(comp, _extra(fields))
        return Repo.get_competition_doc(new_id)

    @staticmethod
    @_write
    def update_competition(competition_id: int, fields: Dict[str, Any]) -> dict:
        """Partial update: only the fields given are changed (participants untouched)."""
        comp = Repo.get_competition(competition_id)
        if comp is None:
            raise _competition_not_found()
        for field in COMPETITION_FIELDS:
            if fields.get(field) is not None:
                setattr(comp, field, fields[field])
        if "coach_ids" in fields:
            _apply_coaches(comp, fields["coach_ids"] or [])
        Repo.save_competition(comp, _extra(fields))
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @_write
    def delete_competition(competition_id: int) -> None:
        if not Repo.delete_competition(competition_id):
            raise _competition_not_found()

    @staticmethod
    @_write
    def archive_past_competitions() -> List[int]:
        """Closes the competitions that are over; returns their ids."""
        return Repo.archive_past_competitions(datetime.date.today().isoformat())

    # ------------------------------------------------------------------
    # Participants (array embedded in the competition document)
    # ------------------------------------------------------------------
    @staticmethod
    @_write
    def add_participant(competition_id: int, adherent_id: int, selectionne: bool) -> dict:
        _require_competition(competition_id)
        Repo.add_participant(competition_id, adherent_id, selectionne)
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @_write
    def update_participant(competition_id: int, adherent_id: int,
                           selectionne: Optional[bool] = None,
                           present: Optional[bool] = None) -> dict:
        """Unselecting a participant who paid is refused (Conflict `already_paid`): the
        coach must then choose whether the money is lost or carried over (cancel_participant)."""
        _require_competition(competition_id)
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
    @_write
    def cancel_participant(competition_id: int, adherent_id: int, payment_status: str,
                           note: str) -> dict:
        """`payment_status`: PAIEMENT_ANNULE_PERDU or PAIEMENT_ANNULE_REPORTE."""
        if not Repo.mark_cancelled(competition_id, adherent_id, payment_status, note):
            raise NotFound("Compétition ou compétiteur introuvable.")
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @_write
    def remove_participant(competition_id: int, adherent_id: int) -> dict:
        if not Repo.remove_participant(competition_id, adherent_id):
            raise NotFound("Compétition ou compétiteur introuvable.")
        return Repo.get_competition_doc(competition_id)

    @staticmethod
    @_write
    def load_competition_group(competition_id: int) -> Tuple[int, dict]:
        """Adds every member of the « Compétition » tariff not already listed (not invited).
        Returns (number added, competition)."""
        _require_competition(competition_id)
        added = Repo.load_competition_group_into(competition_id)
        return added, Repo.get_competition_doc(competition_id)

    # ------------------------------------------------------------------
    # Coaches
    # ------------------------------------------------------------------
    @staticmethod
    @_storage
    def list_coaches() -> List[dict]:
        return Repo.list_coaches()

    @staticmethod
    @_write
    def create_coach(nom: str) -> int:
        return Repo.save_coach(nom)

    @staticmethod
    @_write
    def rename_coach(coach_id: int, nom: str) -> None:
        """Renames the coach and the name copied into their competitions."""
        if Repo.get_coach(coach_id) is None:
            raise NotFound("Coach introuvable.")
        Repo.save_coach(nom, coach_id)

    @staticmethod
    @_write
    def delete_coach(coach_id: int) -> None:
        """Deletes the coach and removes them from every competition."""
        if Repo.get_coach(coach_id) is None:
            raise NotFound("Coach introuvable.")
        Repo.delete_coach(coach_id)

    # ------------------------------------------------------------------
    # Members as seen by the competition pages (Firestore `adherents` projection)
    # ------------------------------------------------------------------
    @staticmethod
    @_storage
    def list_members() -> List[dict]:
        return Repo.list_adherents()

    # ------------------------------------------------------------------
    # HelloAsso mirror: manual links and ignored items
    # ------------------------------------------------------------------
    @staticmethod
    @_storage
    def list_helloasso_items() -> List[dict]:
        return Repo.list_item_docs()

    @staticmethod
    @_write
    def link_helloasso_item(id_item: int, competition_id: Optional[int],
                            adherent_id: Optional[int], commentaire: str) -> bool:
        """Saves the coach's link. When both a competition and a member are chosen, the member
        is (re)selected for the competition and the item's amount recorded as paid.
        Returns whether the item is now linked to a participant."""
        item = Repo.get_item(id_item)
        if item is None:
            raise NotFound("Article HelloAsso introuvable.")
        if competition_id is not None and Repo.get_competition_doc(competition_id) is None:
            raise _competition_not_found()
        Repo.save_manual_link(id_item, competition_id, adherent_id, commentaire)
        linked = competition_id is not None and adherent_id is not None
        if linked:
            Repo.add_participant(competition_id, adherent_id, selectionne=True)
            Repo.apply_helloasso_payment(competition_id, adherent_id,
                                         float(item.get("montant") or 0.0),
                                         order_ref=str(item.get("order_id") or ""))
        return linked

    @staticmethod
    @_write
    def ignore_helloasso_item(id_item: int, ignore: bool, motif: str, commentaire: str,
                              by: str) -> None:
        """Ignores (reason required) or restores an item. Refused (Conflict `already_linked`)
        when the item got linked meanwhile. `by`: e-mail of the coach, kept for audit."""
        if ignore and not motif:
            raise InvalidRequest("Indiquez un motif pour ignorer cette ligne.", "motif_required")
        try:
            found = Repo.set_item_ignored(id_item, ignore, motif, commentaire, by=by)
        except ItemAlreadyLinked as e:
            raise Conflict("Cette ligne vient d'être rattachée à un compétiteur : "
                           "elle ne peut pas être ignorée.", "already_linked") from e
        if not found:
            raise NotFound("Article HelloAsso introuvable.")
