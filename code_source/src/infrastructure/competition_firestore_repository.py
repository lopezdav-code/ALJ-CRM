"""
Référentiel des compétitions sur Google Cloud Firestore (source de vérité unique).

Remplace l'ancienne base SQLite locale (database_Competition.db) : la page web
PWA (web/competitions.html) et l'application de bureau partagent désormais le
même modèle de documents Firestore :

- `competitions/{id}`        : épreuve + tableau `participants` embarqué ;
- `coaches/{id}`             : référentiel des coachs ;
- `adherents/{id}`           : instantané des adhérents (miroir de database.db) ;
- `app_settings/{key}`       : paramètres applicatifs (campagne annuelle…) ;
- `helloasso_items/{id_item}` : miroir des paiements HelloAsso + rattachements.

L'API publique reproduit à l'identique celle de l'ancien
`CompetitionRepository` (SQLite) afin que les pages et services existants
fonctionnent sans changement. Toutes les méthodes sont des classmethods.

Normalisation des identifiants : les documents hérités créés par la page web
avaient un identifiant Firestore aléatoire. À la première lecture d'une épreuve,
le document est recopié vers l'identifiant canonique `str(id)` et le document
hérité est supprimé ; les écritures ciblent toujours l'identifiant canonique.
"""
import time
import datetime
import json
import re
from typing import Dict, Any, List, Optional

from domain.competition_models import (
    Competition,
    Participant,
    PAIEMENT_EN_ATTENTE,
    PAIEMENT_NON_INVITE,
)
from domain.constants import get_active_season
from domain.age_rules import parse_birth_date, age_at, get_season_start_date
from domain.utils import normalize_string
from infrastructure.firestore_client import (
    FirestoreClient,
    FirestoreError,
)
from infrastructure.sqlite_repository import SqliteRepository

# Collé pour l'ancien appelant (web) : état de paiement par défaut d'un nouveau
# participant ajouté explicitement (même sémantique que l'ancienne base SQLite).
DEFAULT_STATUT_NOUVEAU_PARTICIPANT = PAIEMENT_EN_ATTENTE

_ADHERENTS_CACHE_TTL = 30.0


class CompetitionFirestoreRepository:
    """CRUD des épreuves / participants / coachs / miroir HelloAsso sur Firestore."""

    _adherents_cache: Optional[List[Dict[str, Any]]] = None
    _adherents_cache_at: float = 0.0

    COLLECTION_COMPETITIONS = "competitions"
    COLLECTION_COACHES = "coaches"
    COLLECTION_ADHERENTS = "adherents"
    COLLECTION_PLANNING = "planning"
    COLLECTION_SETTINGS = "app_settings"
    COLLECTION_ITEMS = "helloasso_items"

    # ------------------------------------------------------------------
    # Outils internes : documents de compétition
    # ------------------------------------------------------------------
    @classmethod
    def _now_iso(cls) -> str:
        return datetime.datetime.now().isoformat(timespec="seconds")

    @classmethod
    def _new_id(cls) -> int:
        """Identifiant métier d'un nouveau document (même convention que la PWA)."""
        return int(time.time() * 1000)

    @classmethod
    def _list_comp_docs(cls) -> List[Dict[str, Any]]:
        """Tous les documents `competitions`, dédoublonnés par identifiant métier.

        Un même identifiant métier peut exister sous deux documents (création PWA
        historique avec identifiant Firestore aléatoire) : le document le plus
        récent gagne, il est recopié vers l'identifiant canonique `str(id)` et
        les doublons sont supprimés."""
        docs = FirestoreClient.list_documents(cls.COLLECTION_COMPETITIONS)
        kept: Dict[str, Dict[str, Any]] = {}
        for d in docs:
            if d.get("id") is None:
                key = d.get("_doc_id")
                kept.setdefault(key, d)
                continue
            key = str(d.get("id"))
            current = kept.get(key)
            if current is None or str(d.get("updated_at") or "") > str(current.get("updated_at") or ""):
                kept[key] = d
        for key, doc in list(kept.items()):
            if doc.get("id") is None:
                continue
            doc_id = doc.get("_doc_id") or key
            if doc_id == key:
                continue
            try:
                clean = {k: v for k, v in doc.items() if k != "_doc_id"}
                FirestoreClient.upsert_document(cls.COLLECTION_COMPETITIONS, key, clean)
                FirestoreClient.delete_document(cls.COLLECTION_COMPETITIONS, doc_id)
                doc["_doc_id"] = key
            except FirestoreError as e:
                print(f"⚠️ [FIRESTORE] Normalisation de l'épreuve #{key} impossible : {e}")
        return list(kept.values())

    @classmethod
    def _load_comp_doc(cls, competition_id) -> Optional[Dict[str, Any]]:
        """Charge le document d'une épreuve (chemin rapide : identifiant canonique)."""
        wanted = str(competition_id)
        doc = FirestoreClient.get_document(cls.COLLECTION_COMPETITIONS, wanted)
        if doc is not None and str(doc.get("id")) == wanted:
            return doc
        matches = [d for d in cls._list_comp_docs() if str(d.get("id")) == wanted]
        return matches[0] if matches else None

    @classmethod
    def _comp_from_doc(cls, doc: Dict[str, Any]) -> Competition:
        coach_ids = [int(cid) for cid in (doc.get("coach_ids") or []) if cid is not None]
        row = {
            "id": doc.get("id"),
            "id_ffme": doc.get("id_ffme"),
            "nom": doc.get("nom"),
            "date_competition": doc.get("date_competition"),
            "prix": doc.get("prix"),
            "statut": doc.get("statut"),
            "helloasso_ref": doc.get("helloasso_ref"),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "coach1_id": doc.get("coach1_id") or (coach_ids[0] if len(coach_ids) > 0 else None),
            "coach2_id": doc.get("coach2_id") or (coach_ids[1] if len(coach_ids) > 1 else None),
            "coach3_id": doc.get("coach3_id") or (coach_ids[2] if len(coach_ids) > 2 else None),
            "_doc_id": doc.get("_doc_id"),
        }
        return Competition.from_row(row)

    @classmethod
    def _build_comp_doc(cls, doc: Optional[Dict[str, Any]], comp: Competition,
                        coach_names: List[str]) -> Dict[str, Any]:
        """Document complet prêt à être écrit (participants préservés)."""
        parts = (doc or {}).get("participants") or []
        coach_ids = [cid for cid in (comp.coach1_id, comp.coach2_id, comp.coach3_id)
                     if cid is not None]
        now = cls._now_iso()
        new_doc = {
            "id": comp.id,
            "id_ffme": comp.id_ffme or "",
            "nom": comp.nom or "",
            "date_competition": comp.date_competition or "",
            "prix": float(comp.prix or 0.0),
            "statut": comp.statut or "en_preparation",
            "helloasso_ref": comp.helloasso_ref or "",
            "coaches": coach_names,
            "coach_ids": coach_ids,
            "coach1_id": comp.coach1_id,
            "coach2_id": comp.coach2_id,
            "coach3_id": comp.coach3_id,
            "participants": parts,
            "created_at": (doc or {}).get("created_at") or now,
            "updated_at": now,
        }
        new_doc.update(cls._recompute_counters(parts))
        return new_doc

    @classmethod
    def _recompute_counters(cls, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "nb_participants": len(parts),
            "nb_selectionnes": sum(1 for p in parts if p.get("selectionne")),
            "nb_payes": sum(1 for p in parts if (p.get("statut_paiement") or "") == "paye"),
            "total_collecte": round(sum(float(p.get("montant_paye") or 0.0) for p in parts), 2),
        }

    @classmethod
    def _save_parts(cls, doc: Dict[str, Any], parts: List[Dict[str, Any]]):
        """Réécrit le tableau des participants + compteurs (mise à jour partielle)."""
        patch = {"participants": parts, "updated_at": cls._now_iso()}
        patch.update(cls._recompute_counters(parts))
        FirestoreClient.update_fields(
            cls.COLLECTION_COMPETITIONS, doc.get("_doc_id") or str(doc.get("id")), patch
        )

    # ------------------------------------------------------------------
    # Compatibilité avec l'ancien référentiel SQLite
    # ------------------------------------------------------------------
    @classmethod
    def setup_database(cls, force: bool = False):
        """Aucune action : les collections Firestore existent par nature."""
        return None

    @classmethod
    def get_db_path(cls) -> str:
        """Ancienne API (SQLite) : conservée pour compatibilité, inutilisée."""
        return ""

    # ------------------------------------------------------------------
    # Instantané des adhérents (source : database.db principale -> Firestore)
    # ------------------------------------------------------------------
    @classmethod
    def sync_adherents_from_main(cls, season_filter: str = "") -> dict:
        """Recalcule l'annuaire Firestore `adherents` depuis la base principale.

        Le miroir est intégralement réécrit (l'annuaire Firestore reflète
        database.db) et la collection `planning` est mise à jour dans la foulée
        pour que la PWA dispose des groupes de créneaux.
        Retourne un rapport {imported, updated, errors}.
        """
        report = {"imported": 0, "updated": 0, "errors": []}
        season = (season_filter or get_active_season() or "").strip()

        try:
            SqliteRepository.setup_database()
            main_conn = SqliteRepository.get_connection()
        except Exception as e:
            report["errors"].append(f"Base principale inaccessible : {e}")
            return report

        try:
            rows = []
            if season:
                rows = main_conn.execute(
                    'SELECT * FROM v_adherents_legacy WHERE season_name = ? '
                    'ORDER BY "user_id" ASC', (season,)
                ).fetchall()
            if not rows:
                rows = main_conn.execute(
                    'SELECT * FROM v_adherents_legacy ORDER BY "user_id" ASC'
                ).fetchall()

            # Groupes de créneaux (planning -> tarifs) pour le champ creneau_groupe
            planning_groups = cls._read_planning_groups(main_conn)

            # Collection planning (référence pour la PWA)
            planning_writes = []
            for pr in main_conn.execute(
                "SELECT * FROM planning ORDER BY jour, horaires"
            ).fetchall():
                enc = pr["encadrants"] or ""
                if enc.startswith("["):
                    try:
                        enc = ", ".join(json.loads(enc))
                    except Exception:
                        pass
                planning_writes.append({
                    "path": f"{cls.COLLECTION_PLANNING}/{pr['id']}",
                    "data": {
                        "id": pr["id"],
                        "groupe": pr["groupe"] or "",
                        "type": pr["type"] or "",
                        "categorie_age": pr["categorie_age"] or "",
                        "jour": pr["jour"] or "",
                        "horaires": pr["horaires"] or "",
                        "encadrants": enc,
                    },
                })
        except Exception as e:
            report["errors"].append(f"Lecture de la base principale impossible : {e}")
            return report
        finally:
            main_conn.close()

        ref_date = get_season_start_date(season or get_active_season())
        now = cls._now_iso()
        adherent_writes = []
        for row in rows:
            d = dict(row)
            adherent_id = d.get("user_id") or d.get("id")
            if adherent_id is None:
                continue
            bdate = d.get("birth_date") or ""
            b_parsed = parse_birth_date(bdate)
            age_val = age_at(b_parsed, ref_date) if b_parsed else None
            t_name = str(d.get("tarif_name") or "").strip()
            groupe = planning_groups.get(normalize_string(t_name), "")
            licence = str(d.get("licence_ffme") or "").strip()
            adherent_writes.append({
                "path": f"{cls.COLLECTION_ADHERENTS}/{adherent_id}",
                "data": {
                    "id": adherent_id,
                    "nom": str(d.get("last_name") or "").strip().upper(),
                    "prenom": str(d.get("first_name") or "").strip().title(),
                    "licence_ffme": licence,
                    "num_licence": licence,
                    "birth_date": bdate,
                    "age": age_val,
                    "gender": d.get("gender") or "",
                    "email": str(d.get("email_primary") or "").strip(),
                    "email_secondaire": str(d.get("email_secondary") or "").strip(),
                    "phone": str(d.get("phone") or "").strip(),
                    "creneau_groupe": groupe,
                    "tarif": t_name,
                    "saison": str(d.get("season_name") or "").strip(),
                    "emergency_name": d.get("emergency1_name") or "",
                    "emergency_phone": d.get("emergency1_phone") or "",
                    "badge_rouge": d.get("badge_rouge") or "Non",
                    "autonomie_bloc": d.get("autonomie_bloc") or "Non",
                    "updated_at": now,
                },
            })
            report["imported"] += 1

        writes = planning_writes + adherent_writes
        if writes:
            try:
                batch_report = FirestoreClient.batch_upsert(writes)
            except Exception as e:
                report["errors"].append(str(e))
                return report
            if batch_report["errors_count"]:
                report["errors"].append(
                    f"{batch_report['errors_count']} écriture(s) Firestore en échec : "
                    + " ; ".join(batch_report["errors"][:3])
                )
                report["updated"] = max(0, batch_report["written"] - len(planning_writes))
                return report

        cls._invalidate_adherents_cache()
        report["updated"] = len(adherent_writes)
        return report

    @staticmethod
    def _read_planning_groups(main_conn) -> Dict[str, str]:
        """{tarif normalisé -> groupe de créneau} depuis la table planning."""
        pairs: Dict[str, str] = {}
        try:
            for pr in main_conn.execute("SELECT groupe, helloasso_tarifs FROM planning").fetchall():
                groupe = str(pr["groupe"] or "").strip()
                if not groupe:
                    continue
                try:
                    tarifs = json.loads(str(pr["helloasso_tarifs"] or "[]"))
                except (ValueError, TypeError):
                    tarifs = []
                for t in tarifs or []:
                    t = str(t or "").strip()
                    if t:
                        pairs[normalize_string(t)] = groupe
        except Exception:
            pass
        return pairs

    COLLECTION_PLANNING = "planning"

    @classmethod
    def list_planning_groups(cls) -> Dict[str, str]:
        """{tarif normalisé -> groupe de créneau} (lu directement dans database.db)."""
        SqliteRepository.setup_database()
        conn = SqliteRepository.get_connection()
        try:
            return cls._read_planning_groups(conn)
        finally:
            conn.close()

    @classmethod
    def _invalidate_adherents_cache(cls):
        cls._adherents_cache = None
        cls._adherents_cache_at = 0.0

    @classmethod
    def _adherents_raw(cls) -> List[Dict[str, Any]]:
        now = time.time()
        if cls._adherents_cache is None or (now - cls._adherents_cache_at) > _ADHERENTS_CACHE_TTL:
            try:
                cls._adherents_cache = FirestoreClient.list_documents(cls.COLLECTION_ADHERENTS)
            except Exception as e:
                print(f"⚠️ [FIRESTORE] Lecture de l'annuaire adhérents impossible : {e}")
                cls._adherents_cache = cls._adherents_cache or []
            cls._adherents_cache_at = now
        return cls._adherents_cache

    @classmethod
    def _adherent_map(cls) -> Dict[int, Dict[str, Any]]:
        return {a.get("id"): a for a in cls._adherents_raw() if a.get("id") is not None}

    @classmethod
    def _adherent_as_legacy_dict(cls, doc: Dict[str, Any]) -> Dict[str, Any]:
        licence = str(doc.get("licence_ffme") or doc.get("num_licence") or "")
        return {
            "id": doc.get("id"),
            "nom": str(doc.get("nom") or ""),
            "prenom": str(doc.get("prenom") or ""),
            "num_licence": licence,
            "email": str(doc.get("email") or ""),
            "email_secondaire": str(doc.get("email_secondaire") or ""),
            "phone": str(doc.get("phone") or ""),
            "tarif": str(doc.get("tarif") or ""),
            "saison": str(doc.get("saison") or ""),
            "licence_ffme": licence,
            "creneau_groupe": str(doc.get("creneau_groupe") or ""),
            "emergency_name": str(doc.get("emergency_name") or ""),
            "emergency_phone": str(doc.get("emergency_phone") or ""),
            "birth_date": str(doc.get("birth_date") or ""),
            "age": doc.get("age"),
            "gender": str(doc.get("gender") or ""),
            "badge_rouge": str(doc.get("badge_rouge") or ""),
            "autonomie_bloc": str(doc.get("autonomie_bloc") or ""),
        }

    @classmethod
    def list_adherents(cls, search: str = "", competition_only: bool = False) -> list:
        """Liste les adhérents de l'annuaire Firestore (recherche insensible aux accents)."""
        from domain.utils import normalize_string
        q = normalize_string(search) if search else ""
        result = []
        for doc in cls._adherents_raw():
            d = cls._adherent_as_legacy_dict(doc)
            if competition_only and "competition" not in normalize_string(d.get("tarif") or ""):
                continue
            if q:
                haystack = normalize_string(
                    f"{d.get('nom')} {d.get('prenom')} {d.get('num_licence')} {d.get('tarif')}"
                )
                if q not in haystack:
                    continue
            result.append(d)
        return result

    @classmethod
    def count_adherents(cls) -> int:
        return len(cls._adherents_raw())

    # ------------------------------------------------------------------
    # CRUD Compétitions
    # ------------------------------------------------------------------
    @classmethod
    def list_competitions(cls) -> List[Competition]:
        docs = cls._list_comp_docs()
        comps = [cls._comp_from_doc(d) for d in docs]
        comps.sort(key=lambda c: (c.date_competition or "", int(c.id or 0)), reverse=True)
        return comps

    @classmethod
    def get_competition(cls, competition_id: int) -> Optional[Competition]:
        doc = cls._load_comp_doc(competition_id)
        return cls._comp_from_doc(doc) if doc else None

    @classmethod
    def save_competition(cls, comp: Competition) -> int:
        """Insère ou met à jour une épreuve ; retourne son identifiant."""
        existing = cls._load_comp_doc(comp.id) if comp.id else None
        if comp.id is None:
            comp.id = cls._new_id()
        coaches = cls._coaches_map()
        coach_names = [coaches[cid] for cid in (comp.coach1_id, comp.coach2_id, comp.coach3_id)
                       if cid is not None and cid in coaches]
        doc = cls._build_comp_doc(existing, comp, coach_names)
        FirestoreClient.upsert_document(cls.COLLECTION_COMPETITIONS, str(comp.id), doc)
        return comp.id

    @classmethod
    def set_competition_status(cls, competition_id: int, statut: str) -> bool:
        doc = cls._load_comp_doc(competition_id)
        if not doc:
            return False
        FirestoreClient.update_fields(cls.COLLECTION_COMPETITIONS, str(doc.get("id")),
                                      {"statut": statut, "updated_at": cls._now_iso()})
        return True

    @classmethod
    def delete_competition(cls, competition_id: int) -> bool:
        doc = cls._load_comp_doc(competition_id)
        if not doc:
            return False
        FirestoreClient.delete_document(cls.COLLECTION_COMPETITIONS, str(doc.get("id")))
        return True

    # ------------------------------------------------------------------
    # Participants (tableau embarqué dans le document de l'épreuve)
    # ------------------------------------------------------------------
    @classmethod
    def list_participants(cls, competition_id: int, selected_only: bool = False) -> List[Participant]:
        doc = cls._load_comp_doc(competition_id)
        if not doc:
            return []
        parts = doc.get("participants") or []
        if selected_only:
            parts = [p for p in parts if p.get("selectionne")]
        adh = cls._adherent_map()
        result = []
        for p in parts:
            row = dict(p)
            a = adh.get(p.get("adherent_id")) or {}
            row.setdefault("tarif", a.get("tarif") or "")
            row.setdefault("email", a.get("email") or "")
            row.setdefault("nom", a.get("nom") or "")
            row.setdefault("prenom", a.get("prenom") or "")
            row.setdefault("num_licence", a.get("num_licence") or "")
            row.setdefault("date_synchro_helloasso", row.get("updated_at") or "")
            row["competition_id"] = competition_id
            result.append(Participant.from_row(row))
        result.sort(key=lambda p: ((p.nom or "").lower(), (p.prenom or "").lower()))
        return result

    @classmethod
    def _new_participant_map(cls, adherent_doc: Dict[str, Any],
                             selectionne: bool, statut: str = DEFAULT_STATUT_NOUVEAU_PARTICIPANT) -> Dict[str, Any]:
        return {
            "participant_id": adherent_doc.get("id"),
            "adherent_id": adherent_doc.get("id"),
            "nom": str(adherent_doc.get("nom") or "").upper(),
            "prenom": str(adherent_doc.get("prenom") or ""),
            "num_licence": str(adherent_doc.get("licence_ffme") or adherent_doc.get("num_licence") or ""),
            "email": str(adherent_doc.get("email") or ""),
            "phone": str(adherent_doc.get("phone") or ""),
            "tarif": str(adherent_doc.get("tarif") or ""),
            "selectionne": bool(selectionne),
            "statut_paiement": statut,
            "montant_paye": 0.0,
            "commande_helloasso": "",
            "urgence_nom": str(adherent_doc.get("emergency_name") or ""),
            "urgence_tel": str(adherent_doc.get("emergency_phone") or ""),
            "updated_at": cls._now_iso(),
        }

    @classmethod
    def _mutate_participants(cls, competition_id: int, mutate) -> Optional[Dict[str, Any]]:
        """Charge le document, applique `mutate(parts)`, réécrit le tableau.

        `mutate` peut renvoyer None pour signaler « rien à faire » : aucune
        écriture n'a alors lieu."""
        doc = cls._load_comp_doc(competition_id)
        if not doc:
            return None
        parts = [dict(p) for p in (doc.get("participants") or [])]
        new_parts = mutate(parts)
        if new_parts is None:
            return None
        cls._save_parts(doc, new_parts)
        return doc

    @classmethod
    def add_participant(cls, competition_id: int, adherent_id: int,
                        selectionne: bool = True) -> int:
        """Ajoute un adhérent à une compétition (idempotent) ; retourne l'identifiant
        de la ligne participant (existante ou nouvelle)."""
        def mutate(parts):
            for p in parts:
                if p.get("adherent_id") == adherent_id:
                    if selectionne:
                        p["selectionne"] = True
                        p["updated_at"] = cls._now_iso()
                    return parts
            adh = cls._adherent_map().get(adherent_id) or {"id": adherent_id}
            parts.append(cls._new_participant_map(adh, selectionne))
            return parts
        doc = cls._mutate_participants(competition_id, mutate)
        if doc is None:
            return 0
        for p in doc.get("participants") or []:
            if p.get("adherent_id") == adherent_id:
                return p.get("participant_id") or adherent_id
        return adherent_id

    @classmethod
    def remove_participant(cls, competition_id: int, adherent_id: int) -> bool:
        doc = cls._load_comp_doc(competition_id)
        if not doc:
            return False
        parts = [p for p in (doc.get("participants") or []) if p.get("adherent_id") != adherent_id]
        if len(parts) == len(doc.get("participants") or []):
            return False
        cls._save_parts(doc, parts)
        return True

    @classmethod
    def set_selection(cls, competition_id: int, adherent_id: int, selectionne: bool) -> bool:
        def mutate(parts):
            for p in parts:
                if p.get("adherent_id") == adherent_id:
                    p["selectionne"] = bool(selectionne)
                    p["updated_at"] = cls._now_iso()
                    return parts
            adh = cls._adherent_map().get(adherent_id) or {"id": adherent_id}
            parts.append(cls._new_participant_map(adh, selectionne))
            return parts
        cls._mutate_participants(competition_id, mutate)
        return True

    @classmethod
    def set_payment_status(cls, competition_id: int, adherent_id: int, statut_paiement: str) -> bool:
        def mutate(parts):
            changed = False
            for p in parts:
                if p.get("adherent_id") == adherent_id:
                    p["statut_paiement"] = statut_paiement
                    p["updated_at"] = cls._now_iso()
                    changed = True
            return parts if changed else None
        return cls._mutate_participants(competition_id, mutate) is not None

    @classmethod
    def apply_helloasso_payment(cls, competition_id: int, adherent_id: int,
                                montant_paye: float, date_synchro: str = "",
                                order_ref: str = "") -> bool:
        date_val = date_synchro or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        def mutate(parts):
            changed = False
            for p in parts:
                if p.get("adherent_id") == adherent_id:
                    p["statut_paiement"] = "paye"
                    p["montant_paye"] = float(montant_paye or 0.0)
                    p["commande_helloasso"] = str(order_ref or "")
                    p["updated_at"] = date_val
                    changed = True
            return parts if changed else None
        return cls._mutate_participants(competition_id, mutate) is not None

    @classmethod
    def load_competition_group_into(cls, competition_id: int) -> int:
        """Pré-remplit la liste des participants avec le groupe « Compétition »."""
        doc = cls._load_comp_doc(competition_id)
        if not doc:
            return 0
        parts = [dict(p) for p in (doc.get("participants") or [])]
        existing = {p.get("adherent_id") for p in parts}
        now = cls._now_iso()
        count = 0
        for a in cls.list_adherents(competition_only=True):
            if a["id"] in existing:
                continue
            p = cls._new_participant_map(a, True)
            p["updated_at"] = now
            parts.append(p)
            count += 1
        if count:
            cls._save_parts(doc, parts)
        return count

    # ------------------------------------------------------------------
    # Bilan de fin d'année
    # ------------------------------------------------------------------
    @staticmethod
    def season_of_date(date_iso: str) -> str:
        raw = str(date_iso or "").strip()[:10]
        try:
            y, m = int(raw[:4]), int(raw[5:7])
        except (ValueError, IndexError):
            return ""
        start = y if m >= 8 else y - 1
        return f"{start}-{start + 1}"

    @classmethod
    def get_bilan(cls, season: str = "") -> dict:
        docs = cls._list_comp_docs()
        comps = [cls._comp_from_doc(d) for d in docs]
        comps.sort(key=lambda c: (c.date_competition or "", int(c.id or 0)))
        adh = cls._adherent_map()
        if season:
            comps = [c for c in comps if cls.season_of_date(c.date_competition) == season]

        doc_by_id = {d.get("id"): d for d in docs}
        participants_map = {}
        payments_map = {}
        students = {}
        for c in comps:
            doc = doc_by_id.get(c.id) or {}
            for p in (doc.get("participants") or []):
                if not p.get("selectionne"):
                    continue
                key = p.get("adherent_id")
                if key is None:
                    continue
                a = adh.get(key) or {}
                students.setdefault(key, {
                    "nom": p.get("nom") or a.get("nom") or "",
                    "prenom": p.get("prenom") or a.get("prenom") or "",
                    "num_licence": p.get("num_licence") or a.get("num_licence") or "",
                    "tarif": p.get("tarif") or a.get("tarif") or "",
                })
                participants_map[(key, c.id)] = p.get("statut_paiement") or PAIEMENT_NON_INVITE
                payments_map[(key, c.id)] = {
                    "montant_paye": float(p.get("montant_paye") or 0.0),
                    "prix": float(c.prix or 0.0),
                }

        seasons = sorted(
            {cls.season_of_date(c.date_competition) for c in comps if c.date_competition},
            reverse=True,
        )
        return {"competitions": comps, "students": students,
                "participations": participants_map, "payments": payments_map, "seasons": seasons}

    # ------------------------------------------------------------------
    # Paramètres applicatifs
    # ------------------------------------------------------------------
    @classmethod
    def get_app_setting(cls, key: str, default: str = "") -> str:
        doc = FirestoreClient.get_document(cls.COLLECTION_SETTINGS, str(key))
        if not doc:
            return default
        value = doc.get("value")
        return str(value) if value is not None else default

    @classmethod
    def save_app_setting(cls, key: str, value: str) -> bool:
        FirestoreClient.upsert_document(cls.COLLECTION_SETTINGS, str(key),
                                        {"key": key, "value": str(value or ""),
                                         "updated_at": cls._now_iso()})
        return True

    # ------------------------------------------------------------------
    # Miroir HelloAsso (documents avec rattachement embarqué)
    # ------------------------------------------------------------------
    @classmethod
    def _items_map(cls) -> Dict[int, Dict[str, Any]]:
        """{id_item: document miroir} — une seule lecture de la collection."""
        items = {}
        for d in FirestoreClient.list_documents(cls.COLLECTION_ITEMS):
            try:
                iid = int(d.get("id_item"))
            except (TypeError, ValueError):
                continue
            items[iid] = d
        return items

    @classmethod
    def sync_helloasso_mirror(cls, summarized: list, raw_items: list,
                              campagne_slug: str) -> int:
        """Upsert du miroir : ce que dit HelloAsso remplace la copie, en préservant
        le commentaire et le rattachement (liens) de chaque article."""
        existing = cls._items_map()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        writes = []
        written = 0
        for s, raw in zip(summarized or [], raw_items or [], strict=False):
            id_item = s.get("id_item")
            if id_item is None:
                continue
            payeur = str(s.get("payeur") or "")
            nom, _, prenom = payeur.partition(" ")
            doc = dict(existing.get(int(id_item)) or {})
            doc.update({
                "id_item": int(id_item),
                "order_id": s.get("commande") or None,
                "payer_nom": nom.strip(),
                "payer_prenom": prenom.strip(),
                "montant": float(s.get("montant") or 0.0),
                "etat": str(s.get("etat") or ""),
                "date_item": str(s.get("date_item") or ""),
                "licence_saisie": str(s.get("licence") or ""),
                "competition_saisie": str(s.get("competition") or ""),
                "campagne_slug": str(campagne_slug or ""),
                "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
                "synced_at": now,
            })
            doc.setdefault("competition_id", None)
            doc.setdefault("adherent_id", None)
            doc.setdefault("source", None)
            doc.setdefault("link_updated_at", None)
            doc.setdefault("commentaire", "")
            writes.append({"path": f"{cls.COLLECTION_ITEMS}/{int(id_item)}", "data": doc})
            written += 1
        if writes:
            FirestoreClient.batch_upsert(writes)
        return written

    @classmethod
    def list_helloasso_links(cls) -> dict:
        result = {}
        for iid, doc in cls._items_map().items():
            source = doc.get("source")
            comp_id = doc.get("competition_id")
            adh_id = doc.get("adherent_id")
            if source or comp_id is not None or adh_id is not None:
                result[iid] = {
                    "competition_id": comp_id,
                    "adherent_id": adh_id,
                    "source": source or "",
                }
        return result

    @classmethod
    def set_item_link(cls, id_item: int, competition_id, adherent_id,
                      source: str = "manuel") -> bool:
        FirestoreClient.update_fields(cls.COLLECTION_ITEMS, str(id_item), {
            "competition_id": competition_id,
            "adherent_id": adherent_id,
            "source": source,
            "link_updated_at": cls._now_iso(),
        })
        return True

    @classmethod
    def clear_item_link(cls, id_item: int) -> bool:
        """Efface le rattachement d'un article (choix « Ignorer »)."""
        try:
            FirestoreClient.update_fields(cls.COLLECTION_ITEMS, str(id_item), {
                "competition_id": None,
                "adherent_id": None,
                "source": None,
                "link_updated_at": cls._now_iso(),
            })
            return True
        except FirestoreError:
            return False

    @classmethod
    def replace_auto_links(cls, links: dict) -> int:
        """Remplace tous les liens 'auto' par le calcul courant ; les liens
        'manuel' sont intacts. `links` : retour de auto_link_items()."""
        items = cls._items_map()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        writes = []
        for iid, doc in items.items():
            source = doc.get("source")
            if str(source or "") == "manuel":
                continue
            new = dict(doc)
            link = (links or {}).get(iid)
            if link is not None:
                new["competition_id"] = link.get("competition_id")
                new["adherent_id"] = link.get("adherent_id")
                new["source"] = "auto"
            else:
                new["competition_id"] = None
                new["adherent_id"] = None
                new["source"] = None
            new["link_updated_at"] = now
            if new != doc:
                writes.append({"path": f"{cls.COLLECTION_ITEMS}/{iid}", "data": new})
        if writes:
            FirestoreClient.batch_upsert(writes)
        return len(writes)

    @classmethod
    def get_item(cls, id_item: int) -> Optional[Dict[str, Any]]:
        doc = FirestoreClient.get_document(cls.COLLECTION_ITEMS, str(id_item))
        return doc

    @classmethod
    def save_item_comment(cls, id_item: int, comment: str) -> bool:
        FirestoreClient.update_fields(cls.COLLECTION_ITEMS, str(id_item),
                                      {"commentaire": str(comment or "")})
        return True

    @classmethod
    def _participant_montant(cls, comp_doc: Optional[Dict[str, Any]], adherent_id) -> Optional[float]:
        for p in (comp_doc or {}).get("participants") or []:
            if p.get("adherent_id") == adherent_id:
                return float(p.get("montant_paye") or 0.0)
        return None

    @classmethod
    def list_mirror_items(cls) -> list:
        items = cls._items_map()
        comps = {}
        for d in cls._list_comp_docs():
            comps[d.get("id")] = d
        adh = cls._adherent_map()
        rows = []
        for iid, doc in items.items():
            comp_id = doc.get("competition_id")
            adh_id = doc.get("adherent_id")
            comp_doc = comps.get(comp_id) if comp_id is not None else None
            a_doc = adh.get(adh_id) or {}
            rows.append({
                "id_item": iid,
                "order_id": doc.get("order_id"),
                "payer_nom": doc.get("payer_nom") or "",
                "payer_prenom": doc.get("payer_prenom") or "",
                "montant": float(doc.get("montant") or 0.0),
                "etat": str(doc.get("etat") or ""),
                "date_item": str(doc.get("date_item") or ""),
                "licence_saisie": str(doc.get("licence_saisie") or ""),
                "competition_saisie": str(doc.get("competition_saisie") or ""),
                "campagne_slug": str(doc.get("campagne_slug") or ""),
                "raw_json": str(doc.get("raw_json") or ""),
                "synced_at": str(doc.get("synced_at") or ""),
                "commentaire": str(doc.get("commentaire") or ""),
                "competition_id": comp_id,
                "adherent_id": adh_id,
                "source": doc.get("source"),
                "competition_nom": (comp_doc or {}).get("nom") or "",
                "adherent_nom": (a_doc.get("nom") or ""),
                "adherent_prenom": (a_doc.get("prenom") or ""),
                "participant_montant_paye": cls._participant_montant(comp_doc, adh_id)
                if comp_id is not None and adh_id is not None else None,
            })
        rows.sort(key=lambda r: (r["date_item"], r["id_item"]), reverse=True)
        return rows

    @classmethod
    def list_unlinked_items(cls) -> list:
        from domain.competition_matching import STATUTS_PAYES
        paid = {str(s).lower() for s in STATUTS_PAYES}
        adh = {a["id"]: a for a in cls.list_adherents()}
        result = []
        for it in cls.list_mirror_items():
            if str(it.get("etat") or "").lower() not in paid:
                continue
            if it.get("competition_id") is not None and it.get("adherent_id") is not None:
                continue
            lic = re.sub(r"\D", "", str(it.get("licence_saisie") or ""))
            preselect = it.get("adherent_id")
            if preselect is None and lic:
                preselect = next((aid for aid, a in adh.items()
                                  if re.sub(r"\D", "", str(a.get("num_licence") or "")) == lic), None)
            comp_name_val, comp_num_val = "", ""
            raw_json_str = it.get("raw_json")
            if raw_json_str:
                try:
                    raw_data = json.loads(raw_json_str)
                    from domain import competition_matching
                    comp_name_val = competition_matching.extract_competition_name(raw_data)
                    comp_num_val = competition_matching.extract_competition_number(raw_data, fallback=False)
                except Exception:
                    pass
            result.append({
                "id_item": it["id_item"],
                "payer": f"{it.get('payer_nom') or ''} {it.get('payer_prenom') or ''}".strip() or "Inconnu",
                "montant": float(it.get("montant") or 0.0),
                "etat": str(it.get("etat") or ""),
                "date_item": str(it.get("date_item") or ""),
                "order_ref": str(it.get("order_id") or ""),
                "licence": str(it.get("licence_saisie") or ""),
                "valeur_champ": str(it.get("competition_saisie") or ""),
                "competition_concernee": comp_name_val,
                "numero_competition": comp_num_val,
                "adherent_id": preselect,
                "participant": "",
                "commentaire": str(it.get("commentaire") or ""),
            })
        result.sort(key=lambda r: (str(r.get("payer") or "").lower(), r.get("id_item") or 0))
        return result

    @classmethod
    def apply_links_to_participants(cls) -> int:
        """Reporte les liens valides sur les participants (groupé par épreuve :
        une lecture + une écriture Firestore par compétition concernée)."""
        from domain.competition_matching import STATUTS_PAYES
        paid = {str(s).lower() for s in STATUTS_PAYES}
        groupes: Dict[tuple, Dict[str, Any]] = {}
        for it in cls._items_map().values():
            if str(it.get("etat") or "").lower() not in paid:
                continue
            comp_id = it.get("competition_id")
            adherent_id = it.get("adherent_id")
            if comp_id is None or adherent_id is None:
                continue
            g = groupes.setdefault((comp_id, adherent_id),
                                   {"montant": 0.0, "orders": []})
            g["montant"] += float(it.get("montant") or 0.0)
            order = str(it.get("order_id") or "")
            if order:
                g["orders"].append(order)

        by_comp: Dict[int, List[tuple]] = {}
        for (comp_id, adherent_id) in groupes:
            by_comp.setdefault(comp_id, []).append(adherent_id)

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        applied = 0
        for comp_id, adherent_ids in by_comp.items():
            doc = cls._load_comp_doc(comp_id)
            if not doc:
                continue
            parts = [dict(p) for p in (doc.get("participants") or [])]
            index = {p.get("adherent_id"): p for p in parts}
            for adherent_id in adherent_ids:
                g = groupes[(comp_id, adherent_id)]
                p = index.get(adherent_id)
                if p is None:
                    adh = cls._adherent_map().get(adherent_id) or {"id": adherent_id}
                    p = cls._new_participant_map(adh, True)
                    p["updated_at"] = now
                    parts.append(p)
                    index[adherent_id] = p
                else:
                    p["selectionne"] = True
                p["statut_paiement"] = "paye"
                p["montant_paye"] = round(g["montant"], 2)
                p["commande_helloasso"] = ", ".join(g["orders"])
                p["updated_at"] = now
                applied += 1
            cls._save_parts(doc, parts)
        return applied

    # ------------------------------------------------------------------
    # CRUD Coachs
    # ------------------------------------------------------------------
    @classmethod
    def _coaches_map(cls) -> Dict[int, str]:
        try:
            docs = FirestoreClient.list_documents(cls.COLLECTION_COACHES)
        except Exception:
            return {}
        return {d.get("id"): str(d.get("nom") or "") for d in docs if d.get("id") is not None}

    @classmethod
    def list_coaches(cls) -> list:
        docs = FirestoreClient.list_documents(cls.COLLECTION_COACHES)
        result = [{"id": d.get("id"), "nom": str(d.get("nom") or "")} for d in docs
                  if d.get("id") is not None]
        result.sort(key=lambda c: (c["nom"] or "").lower())
        return result

    @classmethod
    def get_coach(cls, coach_id: int) -> Optional[dict]:
        doc = FirestoreClient.get_document(cls.COLLECTION_COACHES, str(coach_id))
        if not doc:
            return None
        return {"id": doc.get("id"), "nom": str(doc.get("nom") or "")}

    @classmethod
    def save_coach(cls, nom: str, coach_id: int = None) -> int:
        if coach_id:
            ret_id = coach_id
        else:
            ret_id = cls._new_id()
        FirestoreClient.upsert_document(cls.COLLECTION_COACHES, str(ret_id),
                                        {"id": ret_id, "nom": nom, "updated_at": cls._now_iso()})
        if coach_id:
            cls._refresh_coach_names(ret_id, nom)
        return ret_id

    @classmethod
    def delete_coach(cls, coach_id: int) -> bool:
        existed = FirestoreClient.delete_document(cls.COLLECTION_COACHES, str(coach_id))
        for doc in cls._list_comp_docs():
            if coach_id not in (doc.get("coach_ids") or []):
                continue
            new_ids = [cid for cid in doc.get("coach_ids") or [] if cid != coach_id]
            coaches = cls._coaches_map()
            patch = {
                "coach_ids": new_ids,
                "coach1_id": new_ids[0] if len(new_ids) > 0 else None,
                "coach2_id": new_ids[1] if len(new_ids) > 1 else None,
                "coach3_id": new_ids[2] if len(new_ids) > 2 else None,
                "coaches": [coaches[cid] for cid in new_ids if cid in coaches],
                "updated_at": cls._now_iso(),
            }
            try:
                FirestoreClient.update_fields(cls.COLLECTION_COMPETITIONS,
                                              str(doc.get("id")), patch)
            except FirestoreError as e:
                print(f"⚠️ [FIRESTORE] Retrait du coach #{coach_id} sur l'épreuve "
                      f"#{doc.get('id')} impossible : {e}")
        return existed

    @classmethod
    def _refresh_coach_names(cls, coach_id: int, nom: str):
        for doc in cls._list_comp_docs():
            ids = doc.get("coach_ids") or []
            if coach_id not in ids:
                continue
            coaches = cls._coaches_map()
            coaches[coach_id] = nom
            patch = {"coaches": [coaches[cid] for cid in ids if cid in coaches],
                     "updated_at": cls._now_iso()}
            try:
                FirestoreClient.update_fields(cls.COLLECTION_COMPETITIONS,
                                              str(doc.get("id")), patch)
            except FirestoreError as e:
                print(f"⚠️ [FIRESTORE] Mise à jour du nom du coach sur l'épreuve "
                      f"#{doc.get('id')} impossible : {e}")

    @classmethod
    def list_competitions_for_coach(cls, coach_id: int) -> List[Competition]:
        return [c for c in cls.list_competitions()
                if coach_id in (c.coach1_id, c.coach2_id, c.coach3_id)]
