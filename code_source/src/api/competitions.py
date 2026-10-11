"""Competitions, participants, coaches and HelloAsso links (Firestore collections).

Thin layer over CompetitionFirestoreRepository, shared with the desktop app and the
HelloAsso webhook so all three write with the same rules (participant writes use an
optimistic lock and are retried on conflict). Roles are checked by the auth middleware
(infrastructure.api_auth.required_role): reads are open to readonly, writes need coach.
"""

import datetime
import threading
import time
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.responses import json_with_etag
from api.schemas import (
    CANCEL_MODES,
    CoachIn,
    CompetitionCreate,
    CompetitionUpdate,
    ItemIgnore,
    ItemLink,
    ParticipantAdd,
    ParticipantCancel,
    ParticipantUpdate,
)
from domain.competition_models import Competition
from infrastructure.competition_firestore_repository import (
    CompetitionFirestoreRepository as Repo,
    ItemAlreadyLinked,
    ParticipantAlreadyPaid,
)
from infrastructure.firestore_client import FirestoreConflictError, FirestoreError

router = APIRouter()

# Fields stored as given, outside the domain model (plan appendix B)
PASS_THROUGH_FIELDS = ("lieu", "type")

# Every poll of every open page lists the whole collection: a short per-instance cache
# absorbs the polls of several users. Writes on this instance drop it at once; writes
# made elsewhere (desktop app, webhook, other instance) show up after CACHE_SECONDS.
CACHE_SECONDS = 5.0
_cache_lock = threading.Lock()
_competitions_cache: dict = {"at": 0.0, "docs": None}


def _cached_competitions() -> list:
    with _cache_lock:
        if _competitions_cache["docs"] is None or time.time() - _competitions_cache["at"] > CACHE_SECONDS:
            _competitions_cache["docs"] = Repo.list_competition_docs()
            _competitions_cache["at"] = time.time()
        return _competitions_cache["docs"]


def invalidate_cache():
    with _cache_lock:
        _competitions_cache["docs"] = None


def error(status: int, message: str, code: Optional[str] = None) -> JSONResponse:
    """Same error shape as the other API routes ({status, message}), plus a machine code."""
    body = {"status": "error", "message": message}
    if code:
        body["code"] = code
    return JSONResponse(body, status_code=status)


def _run(action: Callable[[], Any]):
    """Runs a repository call, mapping Firestore failures to HTTP errors."""
    try:
        return action()
    except FirestoreConflictError:
        return error(409, "Données modifiées simultanément par un autre poste : réessayez.", "conflict")
    except FirestoreError as e:
        print(f"❌ [API competitions] {type(e).__name__}: {e}")
        return error(503, "Base Firestore indisponible, réessayez dans un instant.", "unavailable")


def _write(action: Callable[[], Any]):
    try:
        return _run(action)
    finally:
        invalidate_cache()


def _competition_or_404(competition_id: int):
    doc = Repo.get_competition_doc(competition_id)
    return doc if doc is not None else error(404, "Compétition introuvable.", "not_found")


def _apply_coaches(comp: Competition, coach_ids):
    ids = list(coach_ids) + [None] * 3
    comp.coach1_id, comp.coach2_id, comp.coach3_id = ids[0], ids[1], ids[2]


def _extra(body) -> dict:
    sent = body.model_dump(exclude_unset=True)
    return {k: sent[k] for k in PASS_THROUGH_FIELDS if k in sent}


# ---------------------------------------------------------------------------
# Competitions
# ---------------------------------------------------------------------------
@router.get("/api/competitions")
def list_competitions(request: Request):
    docs = _run(_cached_competitions)
    return docs if isinstance(docs, JSONResponse) else json_with_etag(request, docs)


@router.post("/api/competitions", status_code=201)
def create_competition(body: CompetitionCreate):
    comp = Competition(nom=body.nom, id_ffme=body.id_ffme, date_competition=body.date_competition,
                       date_fin=body.date_fin, prix=body.prix, statut=body.statut,
                       helloasso_ref=body.helloasso_ref)
    _apply_coaches(comp, body.coach_ids)

    def action():
        new_id = Repo.save_competition(comp, _extra(body))
        return Repo.get_competition_doc(new_id)
    return _write(action)


@router.patch("/api/competitions/{competition_id}")
def update_competition(competition_id: int, body: CompetitionUpdate):
    def action():
        comp = Repo.get_competition(competition_id)
        if comp is None:
            return error(404, "Compétition introuvable.", "not_found")
        sent = body.model_dump(exclude_unset=True)
        for field in ("nom", "id_ffme", "date_competition", "date_fin", "prix", "statut",
                      "helloasso_ref"):
            if sent.get(field) is not None:
                setattr(comp, field, sent[field])
        if "coach_ids" in sent:
            _apply_coaches(comp, sent["coach_ids"] or [])
        Repo.save_competition(comp, _extra(body))
        return Repo.get_competition_doc(competition_id)
    return _write(action)


@router.delete("/api/competitions/{competition_id}")
def delete_competition(competition_id: int):
    def action():
        if not Repo.delete_competition(competition_id):
            return error(404, "Compétition introuvable.", "not_found")
        return {"status": "success"}
    return _write(action)


@router.post("/api/competitions/archive-past")
def archive_past_competitions():
    today = datetime.date.today().isoformat()
    return _write(lambda: {"status": "success", "archived": Repo.archive_past_competitions(today)})


# ---------------------------------------------------------------------------
# Participants (array embedded in the competition document)
# ---------------------------------------------------------------------------
@router.post("/api/competitions/{competition_id}/participants")
def add_participant(competition_id: int, body: ParticipantAdd):
    def action():
        found = _competition_or_404(competition_id)
        if isinstance(found, JSONResponse):
            return found
        Repo.add_participant(competition_id, body.adherent_id, body.selectionne)
        return Repo.get_competition_doc(competition_id)
    return _write(action)


@router.patch("/api/competitions/{competition_id}/participants/{adherent_id}")
def update_participant(competition_id: int, adherent_id: int, body: ParticipantUpdate):
    """Unselecting a participant who paid answers 409 `already_paid`: the page then asks the
    coach whether the money is lost or carried over (cancel route)."""
    def action():
        found = _competition_or_404(competition_id)
        if isinstance(found, JSONResponse):
            return found
        try:
            if body.selectionne is not None:
                Repo.set_selection(competition_id, adherent_id, body.selectionne,
                                   refuse_unselect_paid=True)
        except ParticipantAlreadyPaid:
            return error(409, "Ce compétiteur a déjà payé : choisissez le sort de son paiement.",
                         "already_paid")
        if body.present is not None and not Repo.set_present(competition_id, adherent_id, body.present):
            return error(404, "Compétiteur absent de cette compétition.", "not_found")
        return Repo.get_competition_doc(competition_id)
    return _write(action)


@router.post("/api/competitions/{competition_id}/participants/{adherent_id}/cancel")
def cancel_participant(competition_id: int, adherent_id: int, body: ParticipantCancel):
    def action():
        if not Repo.mark_cancelled(competition_id, adherent_id, CANCEL_MODES[body.mode], body.note):
            return error(404, "Compétition ou compétiteur introuvable.", "not_found")
        return Repo.get_competition_doc(competition_id)
    return _write(action)


@router.delete("/api/competitions/{competition_id}/participants/{adherent_id}")
def remove_participant(competition_id: int, adherent_id: int):
    def action():
        if not Repo.remove_participant(competition_id, adherent_id):
            return error(404, "Compétition ou compétiteur introuvable.", "not_found")
        return Repo.get_competition_doc(competition_id)
    return _write(action)


@router.post("/api/competitions/{competition_id}/load-group")
def load_competition_group(competition_id: int):
    """Adds every member of the « Compétition » tariff not already listed (not invited)."""
    def action():
        found = _competition_or_404(competition_id)
        if isinstance(found, JSONResponse):
            return found
        added = Repo.load_competition_group_into(competition_id)
        return {"added": added, "competition": Repo.get_competition_doc(competition_id)}
    return _write(action)


# ---------------------------------------------------------------------------
# Coaches
# ---------------------------------------------------------------------------
@router.get("/api/coaches")
def list_coaches(request: Request):
    coaches = _run(Repo.list_coaches)
    return coaches if isinstance(coaches, JSONResponse) else json_with_etag(request, coaches)


@router.post("/api/coaches", status_code=201)
def create_coach(body: CoachIn):
    return _write(lambda: {"id": Repo.save_coach(body.nom), "nom": body.nom})


@router.put("/api/coaches/{coach_id}")
def update_coach(coach_id: int, body: CoachIn):
    """Renames the coach and the name copied into their competitions."""
    def action():
        if Repo.get_coach(coach_id) is None:
            return error(404, "Coach introuvable.", "not_found")
        Repo.save_coach(body.nom, coach_id)
        return {"id": coach_id, "nom": body.nom}
    return _write(action)


@router.delete("/api/coaches/{coach_id}")
def delete_coach(coach_id: int):
    """Deletes the coach and removes them from every competition."""
    def action():
        if Repo.get_coach(coach_id) is None:
            return error(404, "Coach introuvable.", "not_found")
        Repo.delete_coach(coach_id)
        return {"status": "success"}
    return _write(action)


# ---------------------------------------------------------------------------
# Members as seen by the competition pages (Firestore `adherents` projection)
# ---------------------------------------------------------------------------
@router.get("/api/competition-members")
def list_competition_members(request: Request):
    members = _run(Repo.list_adherents)
    return members if isinstance(members, JSONResponse) else json_with_etag(request, members)


# ---------------------------------------------------------------------------
# HelloAsso mirror: manual links and ignored items (coach only)
# ---------------------------------------------------------------------------
@router.get("/api/helloasso/items")
def list_helloasso_items(request: Request):
    items = _run(Repo.list_item_docs)
    return items if isinstance(items, JSONResponse) else json_with_etag(request, items)


@router.put("/api/helloasso/items/{id_item}/link")
def link_helloasso_item(id_item: int, body: ItemLink):
    """Saves the coach's link. When both a competition and a member are chosen, the member
    is (re)selected for the competition and the item's amount recorded as paid."""
    def action():
        item = Repo.get_item(id_item)
        if item is None:
            return error(404, "Article HelloAsso introuvable.", "not_found")
        linked = body.competition_id is not None and body.adherent_id is not None
        if body.competition_id is not None and Repo.get_competition_doc(body.competition_id) is None:
            return error(404, "Compétition introuvable.", "not_found")
        Repo.save_manual_link(id_item, body.competition_id, body.adherent_id, body.commentaire)
        if linked:
            Repo.add_participant(body.competition_id, body.adherent_id, selectionne=True)
            Repo.apply_helloasso_payment(body.competition_id, body.adherent_id,
                                         float(item.get("montant") or 0.0),
                                         order_ref=str(item.get("order_id") or ""))
        return {"status": "success", "linked": linked}
    return _write(action)


@router.put("/api/helloasso/items/{id_item}/ignore")
def ignore_helloasso_item(id_item: int, body: ItemIgnore, request: Request):
    """Ignores (reason required) or restores an item. Refused with 409 `already_linked` when
    the item got linked meanwhile."""
    if body.ignore and not body.motif:
        return error(400, "Indiquez un motif pour ignorer cette ligne.", "motif_required")
    claims = getattr(request.state, "user", None) or {}

    def action():
        try:
            found = Repo.set_item_ignored(id_item, body.ignore, body.motif, body.commentaire,
                                          by=str(claims.get("email") or ""))
        except ItemAlreadyLinked:
            return error(409, "Cette ligne vient d'être rattachée à un compétiteur : "
                              "elle ne peut pas être ignorée.", "already_linked")
        if not found:
            return error(404, "Article HelloAsso introuvable.", "not_found")
        return {"status": "success"}
    return _write(action)
