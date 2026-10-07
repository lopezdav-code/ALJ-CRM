"""
Module de synchronisation bidirectionnelle Google Cloud Firestore (ALJ Escalade).

Permet de :
1. Convertir les données SQLite en documents NoSQL Firestore (REST API v1 / Firebase).
2. Pousser (Push) vers Firestore :
   - Les compétitions et leurs listes de participants (avec statut et contacts).
   - Le référentiel des coachs (coaches).
   - L'annuaire des adhérents actifs.
   - La grille du planning des créneaux.
   - Les modèles d'e-mails disponibles.
3. Récupérer (Pull) depuis Firestore :
   - Les sélections et modifications de pointage réalisées par les coachs sur mobile.
   - Rapprocher et mettre à jour la base de données SQLite locale.
"""

import json
import datetime
from typing import Dict, Any, List, Optional

from domain.constants import get_active_season
from domain.age_rules import parse_birth_date, age_at, get_season_start_date
from domain.utils import normalize_string
from infrastructure.sqlite_repository import SqliteRepository
from infrastructure.competition_repository import CompetitionRepository
from infrastructure.secret_store import SecretStore
from infrastructure.google_drive_client import GoogleDriveClient
# Convertisseurs de types partagés avec le client Firestore (réexportés pour
# compatibilité avec les tests existants).
from infrastructure.firestore_client import (  # noqa: F401
    python_to_firestore_value,
    firestore_to_python_value,
    dict_to_firestore_fields,
    firestore_fields_to_dict,
)

DEFAULT_PROJECT_ID = "smart-amplifier-510811-n6"
FIRESTORE_BASE_URL = "https://firestore.googleapis.com/v1"


# --------------------------------------------------------------------------
# 2. Préparation des collections depuis SQLite
# --------------------------------------------------------------------------
def prepare_firestore_data(season_filter: Optional[str] = None) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    Extrait et structure l'ensemble des données SQLite prêtes à être envoyées
    dans les collections NoSQL Firestore.
    Retourne : { nom_collection : { doc_id : donnees_doc } }
    """
    season = season_filter or get_active_season()
    ref_date = get_season_start_date(season)

    SqliteRepository.setup_database()
    CompetitionRepository.setup_database()

    conn_main = SqliteRepository.get_connection()
    conn_comp = CompetitionRepository.get_connection()

    try:
        # A. Compétitions et Participants
        comps = conn_comp.execute("SELECT * FROM competitions ORDER BY date_competition DESC, id DESC").fetchall()
        coaches_dict = {r["id"]: r["nom"] for r in conn_comp.execute("SELECT id, nom FROM coaches").fetchall()}

        # Référentiel des coachs (collection dédiée pour l'édition PWA)
        coaches_docs: Dict[str, Dict[str, Any]] = {}
        for r in conn_comp.execute("SELECT id, nom FROM coaches ORDER BY nom").fetchall():
            coaches_docs[str(r["id"])] = {
                "id": r["id"],
                "nom": r["nom"] or "",
                "updated_at": datetime.datetime.now().isoformat()
            }

        # Coordonnées des utilisateurs depuis la base principale
        users_info = {
            u["id"]: dict(u) for u in conn_main.execute(
                "SELECT id, birth_date, gender, email_primary, phone, emergency1_name, emergency1_phone FROM users"
            ).fetchall()
        }

        # Tous les participants
        participants_rows = conn_comp.execute("""
            SELECT p.*, a.nom, a.prenom, a.num_licence, a.email, a.phone, a.tarif
            FROM participants p
            LEFT JOIN adherents a ON a.id = p.adherent_id
        """).fetchall()

        parts_by_comp: Dict[int, List[Dict[str, Any]]] = {}
        for p in participants_rows:
            cid = p["competition_id"]
            if cid not in parts_by_comp:
                parts_by_comp[cid] = []

            aid = p["adherent_id"]
            u = users_info.get(aid, {})

            parts_by_comp[cid].append({
                "participant_id": p["id"],
                "adherent_id": aid,
                "nom": (p["nom"] or "").strip().upper(),
                "prenom": (p["prenom"] or "").strip().title(),
                "num_licence": p["num_licence"] or "",
                "email": p["email"] or u.get("email_primary") or "",
                "phone": p["phone"] or u.get("phone") or "",
                "selectionne": bool(p["selectionne"]),
                "statut_paiement": p["statut_paiement"] or "non_invite",
                "montant_paye": float(p["montant_paye"] or 0.0),
                "commande_helloasso": p["commande_helloasso"] or "",
                "urgence_nom": u.get("emergency1_name") or "",
                "urgence_tel": u.get("emergency1_phone") or "",
                "updated_at": p["date_synchro_helloasso"] or ""
            })

        competitions_docs: Dict[str, Dict[str, Any]] = {}
        for c in comps:
            cid = c["id"]
            c_keys = c.keys()
            coach_ids = [c[f"coach{i}_id"] for i in (1, 2, 3) if f"coach{i}_id" in c_keys and c[f"coach{i}_id"]]
            coach_names = [coaches_dict.get(cid_) for cid_ in coach_ids]

            parts = parts_by_comp.get(cid, [])
            nb_sel = sum(1 for p in parts if p["selectionne"])
            nb_payes = sum(1 for p in parts if p["statut_paiement"] == "paye")
            total_collecte = sum(p["montant_paye"] for p in parts)

            competitions_docs[str(cid)] = {
                "id": cid,
                "id_ffme": str(c["id_ffme"] or ""),
                "nom": c["nom"] or "",
                "date_competition": str(c["date_competition"] or ""),
                "prix": float(c["prix"] or 0.0),
                "statut": c["statut"] or "en_preparation",
                "coaches": coach_names,
                "coach_ids": coach_ids,
                "helloasso_ref": c["helloasso_ref"] or "",
                "nb_participants": len(parts),
                "nb_selectionnes": nb_sel,
                "nb_payes": nb_payes,
                "total_collecte": round(total_collecte, 2),
                "participants": parts,
                "updated_at": datetime.datetime.now().isoformat()
            }

        # B. Annuaire des Adhérents
        adherents_docs: Dict[str, Dict[str, Any]] = {}
        planning_groups = CompetitionRepository.list_planning_groups()

        for r in conn_main.execute("""
            SELECT * FROM v_adherents_legacy 
            WHERE season_name = ? OR ? = 'all'
            ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE
        """, (season, season)).fetchall():
            uid = str(r["user_id"])
            if uid not in adherents_docs:
                bdate = r["birth_date"] or ""
                b_parsed = parse_birth_date(bdate)
                age_val = age_at(b_parsed, ref_date) if b_parsed else None

                t_name = str(r["tarif_name"] or "").strip()
                groupe = planning_groups.get(normalize_string(t_name), "")

                adherents_docs[uid] = {
                    "id": r["user_id"],
                    "nom": str(r["last_name"] or "").strip().upper(),
                    "prenom": str(r["first_name"] or "").strip().title(),
                    "licence_ffme": str(r["licence_ffme"] or "").strip(),
                    "birth_date": bdate,
                    "age": age_val,
                    "gender": r["gender"] or "",
                    "email": r["email_primary"] or "",
                    "phone": r["phone"] or "",
                    "creneau_groupe": groupe,
                    "tarif": t_name,
                    "emergency_name": r["emergency1_name"] or "",
                    "emergency_phone": r["emergency1_phone"] or "",
                    "badge_rouge": r["badge_rouge"] or "Non",
                    "autonomie_bloc": r["autonomie_bloc"] or "Non"
                }

        # C. Planning
        planning_docs: Dict[str, Dict[str, Any]] = {}
        for r in conn_main.execute("SELECT * FROM planning ORDER BY jour, horaires").fetchall():
            pid = str(r["id"])
            enc = r["encadrants"] or ""
            if enc.startswith("["):
                try:
                    enc = ", ".join(json.loads(enc))
                except Exception:
                    pass

            planning_docs[pid] = {
                "id": r["id"],
                "groupe": r["groupe"] or "",
                "type": r["type"] or "",
                "categorie_age": r["categorie_age"] or "",
                "jour": r["jour"] or "",
                "horaires": r["horaires"] or "",
                "encadrants": enc
            }

        # D. Modèles d'emails
        template_docs: Dict[str, Dict[str, Any]] = {}
        for t in SqliteRepository.get_email_templates():
            tid = str(t.get("id") or t.get("name") or "")
            template_docs[tid] = {
                "id": t.get("id", 0),
                "name": t.get("name", ""),
                "subject": t.get("subject") or "",
                "body": t.get("body") or "",
                "sender_email": t.get("sender_email") or "",
                "sender_name": t.get("sender_name") or ""
            }

    finally:
        conn_main.close()
        conn_comp.close()

    return {
        "competitions": competitions_docs,
        "adherents": adherents_docs,
        "coaches": coaches_docs,
        "planning": planning_docs,
        "email_templates": template_docs
    }


# --------------------------------------------------------------------------
# 3. Synchronisation REST vers Google Cloud Firestore
# --------------------------------------------------------------------------
class FirestoreSyncService:
    """Service gérant les échanges REST avec Firestore."""

    @classmethod
    def get_project_id(cls) -> str:
        """Récupère l'identifiant du projet Google Cloud / Firebase."""
        return (
            SecretStore.get_secret("FIREBASE_PROJECT_ID") or
            SecretStore.get_secret("GOOGLE_PROJECT_ID") or
            DEFAULT_PROJECT_ID
        )

    @classmethod
    def push_collection(
        cls,
        collection_name: str,
        documents: Dict[str, Dict[str, Any]],
        project_id: Optional[str] = None,
        access_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Envoie un dictionnaire de documents vers une collection Firestore via l'API REST v1.
        Utilise PATCH pour effectuer un Upsert (création ou mise à jour).
        """
        import requests

        pid = project_id or cls.get_project_id()
        token = access_token or GoogleDriveClient.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        success_count = 0
        errors = []

        for doc_id, doc_data in documents.items():
            url = f"{FIRESTORE_BASE_URL}/projects/{pid}/databases/(default)/documents/{collection_name}/{doc_id}"
            payload = {
                "fields": dict_to_firestore_fields(doc_data)
            }

            try:
                resp = requests.patch(url, headers=headers, json=payload, timeout=15)
                if resp.status_code in (200, 201):
                    success_count += 1
                else:
                    errors.append({
                        "doc_id": doc_id,
                        "status_code": resp.status_code,
                        "error": resp.text[:200]
                    })
            except Exception as e:
                errors.append({
                    "doc_id": doc_id,
                    "status_code": 0,
                    "error": str(e)
                })

        return {
            "collection": collection_name,
            "total": len(documents),
            "synced": success_count,
            "errors_count": len(errors),
            "errors": errors
        }

    @classmethod
    def push_all(cls, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Exécute un Push complet de toutes les collections vers Firestore."""
        data = prepare_firestore_data()
        token = GoogleDriveClient.get_access_token()
        pid = project_id or cls.get_project_id()

        results = {}
        for col_name, docs in data.items():
            report = cls.push_collection(
                collection_name=col_name,
                documents=docs,
                project_id=pid,
                access_token=token
            )
            results[col_name] = report

        return {
            "status": "success" if all(r["errors_count"] == 0 for r in results.values()) else "partial",
            "project_id": pid,
            "collections": results
        }

    @classmethod
    def pull_competition_updates(
        cls,
        competition_id: int,
        project_id: Optional[str] = None,
        access_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Récupère depuis Firestore les sélections et pointages mis à jour
        par les coachs pour les réconcilier dans la BDD SQLite locale.
        """
        import requests

        pid = project_id or cls.get_project_id()
        token = access_token or GoogleDriveClient.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        url = f"{FIRESTORE_BASE_URL}/projects/{pid}/databases/(default)/documents/competitions/{competition_id}"
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code != 200:
            return {
                "status": "error",
                "message": f"Impossible de lire la compétition #{competition_id} sur Firestore (HTTP {resp.status_code})"
            }

        doc = resp.json()
        doc_fields = firestore_fields_to_dict(doc.get("fields", {}))
        participants = doc_fields.get("participants", [])

        applied = 0
        for p in participants:
            aid = p.get("adherent_id")
            if not aid:
                continue

            sel = bool(p.get("selectionne"))
            st_paiement = p.get("statut_paiement") or "non_invite"
            montant = float(p.get("montant_paye") or 0.0)

            # Mise à jour dans SQLite locale
            CompetitionRepository.set_selection(competition_id, aid, sel)
            if st_paiement == "paye":
                CompetitionRepository.apply_helloasso_payment(
                    competition_id=competition_id,
                    adherent_id=aid,
                    montant_paye=montant,
                    order_ref=p.get("commande_helloasso") or ""
                )
            applied += 1

        return {
            "status": "success",
            "competition_id": competition_id,
            "participants_reconciled": applied
        }

    @classmethod
    def import_sqlite_into_firestore(cls, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Import de l'ancienne base SQLite (database_Competition.db) vers Firestore.

        Mode « fusion » : seuls les documents ABSENTS de Firestore sont créés —
        les données déjà présentes (source de vérité) ne sont jamais écrasées.
        L'instantané des adhérents fait exception : c'est un miroir de la base
        principale, il est intégralement recalculé.
        """
        from infrastructure.firestore_client import FirestoreClient

        pid = project_id or cls.get_project_id()
        data = prepare_firestore_data()
        report: Dict[str, Any] = {"project_id": pid, "competitions": 0,
                                  "competitions_ignorees": 0, "coaches": 0,
                                  "adherents": 0, "app_settings": 0,
                                  "helloasso_items": 0, "errors": []}

        # 1. Compétitions absentes uniquement (jamais d'écrasement)
        for doc_id, doc in data["competitions"].items():
            try:
                existing = FirestoreClient.get_document("competitions", doc_id, project_id=pid)
                if existing:
                    report["competitions_ignorees"] += 1
                    continue
                FirestoreClient.upsert_document("competitions", doc_id, doc, project_id=pid)
                report["competitions"] += 1
            except Exception as e:
                report["errors"].append(f"Compétition #{doc_id} : {e}")

        # 2. Coachs absents uniquement
        for doc_id, doc in data["coaches"].items():
            try:
                existing = FirestoreClient.get_document("coaches", doc_id, project_id=pid)
                if existing:
                    continue
                FirestoreClient.upsert_document("coaches", doc_id, doc, project_id=pid)
                report["coaches"] += 1
            except Exception as e:
                report["errors"].append(f"Coach #{doc_id} : {e}")

        # 3. Instantané des adhérents (miroir recalculé intégralement)
        try:
            if data["adherents"]:
                writes = [{"path": f"adherents/{doc_id}", "data": doc}
                          for doc_id, doc in data["adherents"].items()]
                batch_report = FirestoreClient.batch_upsert(writes, project_id=pid)
                report["adherents"] = batch_report["written"]
                report["errors"].extend(batch_report["errors"][:3])
        except Exception as e:
            report["errors"].append(f"Adhérents : {e}")

        # 4. Paramètres applicatifs absents (campagne annuelle HelloAsso)
        try:
            conn_comp = CompetitionRepository.get_connection()
            try:
                settings_rows = conn_comp.execute(
                    "SELECT key, value FROM app_settings WHERE value IS NOT NULL AND value != ''"
                ).fetchall()
            finally:
                conn_comp.close()
            for r in settings_rows:
                key = r["key"]
                try:
                    existing = FirestoreClient.get_document("app_settings", str(key), project_id=pid)
                    if existing:
                        continue
                    FirestoreClient.upsert_document(
                        "app_settings", str(key),
                        {"key": key, "value": r["value"],
                         "updated_at": datetime.datetime.now().isoformat()},
                        project_id=pid,
                    )
                    report["app_settings"] += 1
                except Exception as e:
                    report["errors"].append(f"Paramètre {key} : {e}")
        except Exception as e:
            report["errors"].append(f"Paramètres applicatifs : {e}")

        # 5. Miroir HelloAsso + liens (documents absents uniquement, lien embarqué)
        try:
            conn_comp = CompetitionRepository.get_connection()
            try:
                items = conn_comp.execute("SELECT * FROM helloasso_items").fetchall()
                links = conn_comp.execute(
                    "SELECT id_item, competition_id, adherent_id, source FROM item_links"
                ).fetchall()
            finally:
                conn_comp.close()
            links_map = {r["id_item"]: dict(r) for r in links}
            now = datetime.datetime.now().isoformat()
            for it in items:
                doc_id = str(it["id_item"])
                try:
                    existing = FirestoreClient.get_document("helloasso_items", doc_id, project_id=pid)
                    if existing:
                        continue
                    link = links_map.get(it["id_item"], {})
                    doc = {
                        "id_item": it["id_item"],
                        "order_id": it["order_id"],
                        "payer_nom": it["payer_nom"] or "",
                        "payer_prenom": it["payer_prenom"] or "",
                        "montant": float(it["montant"] or 0.0),
                        "etat": it["etat"] or "",
                        "date_item": it["date_item"] or "",
                        "licence_saisie": it["licence_saisie"] or "",
                        "competition_saisie": it["competition_saisie"] or "",
                        "campagne_slug": it["campagne_slug"] or "",
                        "raw_json": it["raw_json"] or "",
                        "synced_at": it["synced_at"] or now,
                        "commentaire": it["commentaire"] or "",
                        "competition_id": link.get("competition_id"),
                        "adherent_id": link.get("adherent_id"),
                        "source": link.get("source"),
                        "link_updated_at": link.get("updated_at"),
                        "updated_at": now,
                    }
                    FirestoreClient.upsert_document("helloasso_items", doc_id, doc, project_id=pid)
                    report["helloasso_items"] += 1
                except Exception as e:
                    report["errors"].append(f"Article #{doc_id} : {e}")
        except Exception as e:
            report["errors"].append(f"Miroir HelloAsso : {e}")

        report["status"] = "success" if not report["errors"] else "partial"
        return report
