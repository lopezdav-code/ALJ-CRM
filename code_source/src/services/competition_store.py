"""Plumbing shared by the services of the competition pages (Firestore-backed).

- `storage` / `write`: decorators turning Firestore failures into services.errors; a write
  also drops the competition list cache, since most writes change a competition document
  (participants, coach names, HelloAsso payments).
- The competition list cache, shared by every poll of every open page.
- `require_competition`: existence check used by several services.
"""

import functools
import threading
import time
from typing import Callable, List

from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
from infrastructure.firestore_client import FirestoreConflictError, FirestoreError
from services.errors import Conflict, NotFound, StorageUnavailable

# Writes through the services drop the cache at once; writes made elsewhere (desktop app,
# webhook, other instance) show up after CACHE_SECONDS.
CACHE_SECONDS = 5.0
_cache_lock = threading.Lock()
_competitions_cache: dict = {"at": 0.0, "docs": None}


def cached_competitions(load: Callable[[], List[dict]]) -> List[dict]:
    with _cache_lock:
        if _competitions_cache["docs"] is None or time.time() - _competitions_cache["at"] > CACHE_SECONDS:
            _competitions_cache["docs"] = load()
            _competitions_cache["at"] = time.time()
        return _competitions_cache["docs"]


def invalidate_cache():
    with _cache_lock:
        _competitions_cache["docs"] = None


def storage(fn):
    """Turns Firestore failures into service errors."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FirestoreConflictError as e:
            raise Conflict("Données modifiées simultanément par un autre poste : réessayez.") from e
        except FirestoreError as e:
            print(f"❌ [{fn.__qualname__}] {type(e).__name__}: {e}")
            raise StorageUnavailable("Base Firestore indisponible, réessayez dans un instant.") from e
    return wrapper


def write(fn):
    """A write: Firestore failures translated, and the list cache dropped even on failure
    (a write can fail after part of it was applied)."""
    wrapped = storage(fn)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return wrapped(*args, **kwargs)
        finally:
            invalidate_cache()
    return wrapper


def competition_not_found() -> NotFound:
    return NotFound("Compétition introuvable.")


def require_competition(competition_id: int) -> dict:
    doc = Repo.get_competition_doc(competition_id)
    if doc is None:
        raise competition_not_found()
    return doc
