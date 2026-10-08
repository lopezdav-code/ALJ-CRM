"""
Client REST Google Cloud Firestore (API v1) pour l'application de bureau.

Fournit les opérations document (get / list / upsert / update partiel / delete)
et les écritures par lot (commit) utilisées par le référentiel des compétitions.

Authentification :
- Sur Cloud Run / GCP : jeton du compte de service (metadata server).
- Sur le poste de bureau : jeton OAuth2 du club (GoogleDriveClient), dont le
  consentement inclut déjà le scope Firestore `https://www.googleapis.com/auth/datastore`.
"""
import os
import datetime
from typing import Dict, Any, List, Optional

import requests

from infrastructure.secret_store import SecretStore
from infrastructure.google_drive_client import GoogleDriveClient

DEFAULT_PROJECT_ID = "smart-amplifier-510811-n6"
FIRESTORE_BASE_URL = "https://firestore.googleapis.com/v1"
DATABASE_PATH = "projects/{pid}/databases/(default)/documents"

# Le nombre maximal d'écritures par requête :commit est limité à 500.
BATCH_WRITE_LIMIT = 450


class FirestoreError(RuntimeError):
    """Erreur d'échange avec l'API Firestore (statut HTTP non attendu)."""


class FirestoreConflictError(FirestoreError):
    """Écriture refusée : le document a été modifié depuis sa lecture
    (précondition `currentDocument.updateTime` non satisfaite)."""


# Clés techniques ajoutées aux documents lus (jamais réécrites dans Firestore).
META_KEYS = ("_doc_id", "_update_time")


def python_to_firestore_value(val: Any) -> Dict[str, Any]:
    """Convertit une valeur Python native en format de champ Firestore REST."""
    if val is None:
        return {"nullValue": None}
    if isinstance(val, bool):
        return {"booleanValue": val}
    if isinstance(val, int):
        return {"integerValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": val}
    if isinstance(val, (datetime.date, datetime.datetime)):
        iso = val.isoformat()
        if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
            iso = f"{iso}T00:00:00Z"
        elif not iso.endswith("Z"):
            iso = f"{iso}Z"
        return {"timestampValue": iso}
    if isinstance(val, list):
        return {"arrayValue": {"values": [python_to_firestore_value(x) for x in val]}}
    if isinstance(val, dict):
        return {"mapValue": {"fields": {k: python_to_firestore_value(v) for k, v in val.items()}}}
    return {"stringValue": str(val)}


def firestore_to_python_value(f_val: Dict[str, Any]) -> Any:
    """Convertit un champ Firestore REST en valeur Python native."""
    if not isinstance(f_val, dict):
        return None
    if "nullValue" in f_val:
        return None
    if "booleanValue" in f_val:
        return bool(f_val["booleanValue"])
    if "integerValue" in f_val:
        try:
            return int(f_val["integerValue"])
        except (ValueError, TypeError):
            return 0
    if "doubleValue" in f_val:
        try:
            return float(f_val["doubleValue"])
        except (ValueError, TypeError):
            return 0.0
    if "stringValue" in f_val:
        return f_val["stringValue"]
    if "timestampValue" in f_val:
        return f_val["timestampValue"]
    if "arrayValue" in f_val:
        arr = f_val["arrayValue"].get("values", [])
        return [firestore_to_python_value(x) for x in arr]
    if "mapValue" in f_val:
        fields = f_val["mapValue"].get("fields", {})
        return {k: firestore_to_python_value(v) for k, v in fields.items()}
    return None


def dict_to_firestore_fields(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convertit un dictionnaire Python en structure de champs Firestore."""
    return {k: python_to_firestore_value(v) for k, v in (d or {}).items()
            if k not in META_KEYS}


def _is_precondition_failure(resp) -> bool:
    """Vrai si Firestore a refusé l'écriture pour cause de précondition
    (document modifié entre-temps)."""
    if resp.status_code not in (400, 409, 412):
        return False
    text = resp.text or ""
    return "FAILED_PRECONDITION" in text or "ABORTED" in text or resp.status_code == 412


def firestore_fields_to_dict(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Convertit une structure de champs Firestore en dictionnaire Python."""
    return {k: firestore_to_python_value(v) for k, v in (fields or {}).items()}


class FirestoreClient:
    """Passerelle REST vers la base Firestore du projet."""

    @classmethod
    def get_project_id(cls) -> str:
        # Priorité au projet FIREBASE explicite (la base Firestore peut vivre dans
        # un projet différent de celui du service Cloud Run), puis historique
        # GOOGLE_PROJECT_ID, puis le projet Firebase du club.
        return (
            SecretStore.get_secret("FIREBASE_PROJECT_ID") or
            SecretStore.get_secret("GOOGLE_PROJECT_ID") or
            DEFAULT_PROJECT_ID
        )

    @classmethod
    def get_access_token(cls) -> str:
        """Jeton d'accès : metadata server sur GCP/Cloud Run, OAuth2 du club sinon."""
        if os.environ.get("K_SERVICE") or os.environ.get("K_CONFIGURATION"):
            try:
                url = ("http://metadata.google.internal/computeMetadata/v1/instance/"
                       "service-accounts/default/token")
                resp = requests.get(url, headers={"Metadata-Flavor": "Google"}, timeout=5)
                if resp.status_code == 200:
                    return resp.json().get("access_token", "")
            except requests.RequestException:
                pass
        return GoogleDriveClient.get_access_token()

    @classmethod
    def database_url(cls, project_id: Optional[str] = None) -> str:
        pid = project_id or cls.get_project_id()
        return f"{FIRESTORE_BASE_URL}/{DATABASE_PATH.format(pid=pid)}"

    @classmethod
    def _headers(cls, access_token: Optional[str] = None) -> Dict[str, str]:
        token = access_token or cls.get_access_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    @classmethod
    def get_document(cls, collection_name: str, doc_id: str,
                     project_id: Optional[str] = None,
                     access_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Lit un document ; renvoie un dict Python aplati (+ `_doc_id`) ou None."""
        url = f"{cls.database_url(project_id)}/{collection_name}/{doc_id}"
        try:
            resp = requests.get(url, headers=cls._headers(access_token), timeout=15)
        except requests.RequestException as e:
            raise FirestoreError(f"Firestore injoignable ({collection_name}/{doc_id}) : {e}")
        if resp.status_code == 200:
            doc = resp.json()
            data = firestore_fields_to_dict(doc.get("fields", {}))
            data["_doc_id"] = doc.get("name", "").rsplit("/", 1)[-1]
            data["_update_time"] = doc.get("updateTime")
            return data
        if resp.status_code == 404:
            return None
        raise FirestoreError(
            f"Lecture Firestore {collection_name}/{doc_id} : HTTP {resp.status_code} - {resp.text[:200]}"
        )

    @classmethod
    def list_documents(cls, collection_name: str,
                       project_id: Optional[str] = None,
                       access_token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Liste tous les documents d'une collection (pagination incluse)."""
        url = f"{cls.database_url(project_id)}/{collection_name}"
        headers = cls._headers(access_token)
        results: List[Dict[str, Any]] = []
        page_token = None
        while True:
            params = {"pageSize": 300}
            if page_token:
                params["pageToken"] = page_token
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=30)
            except requests.RequestException as e:
                raise FirestoreError(f"Firestore injoignable ({collection_name}) : {e}")
            if resp.status_code != 200:
                raise FirestoreError(
                    f"Liste Firestore {collection_name} : HTTP {resp.status_code} - {resp.text[:200]}"
                )
            payload = resp.json()
            for doc in payload.get("documents", []):
                data = firestore_fields_to_dict(doc.get("fields", {}))
                data["_doc_id"] = doc.get("name", "").rsplit("/", 1)[-1]
                data["_update_time"] = doc.get("updateTime")
                results.append(data)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return results

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------
    @classmethod
    def upsert_document(cls, collection_name: str, doc_id: str, data: Dict[str, Any],
                        project_id: Optional[str] = None,
                        access_token: Optional[str] = None) -> bool:
        """Crée ou remplace intégralement un document (PATCH sans masque = upsert)."""
        url = f"{cls.database_url(project_id)}/{collection_name}/{doc_id}"
        payload = {"fields": dict_to_firestore_fields(data)}
        try:
            resp = requests.patch(url, headers=cls._headers(access_token), json=payload, timeout=30)
        except requests.RequestException as e:
            raise FirestoreError(f"Firestore injoignable ({collection_name}/{doc_id}) : {e}")
        if resp.status_code in (200, 201):
            return True
        raise FirestoreError(
            f"Écriture Firestore {collection_name}/{doc_id} : HTTP {resp.status_code} - {resp.text[:200]}"
        )

    @classmethod
    def update_fields(cls, collection_name: str, doc_id: str, patch: Dict[str, Any],
                      project_id: Optional[str] = None,
                      access_token: Optional[str] = None,
                      expected_update_time: Optional[str] = None) -> bool:
        """Mise à jour partielle (updateMask) : seuls les champs fournis sont modifiés.

        Si le document n'existe pas, il est créé avec les champs fournis.

        `expected_update_time` (valeur `_update_time` du document lu) active le
        verrouillage optimiste : si le document a été modifié depuis la lecture,
        Firestore refuse l'écriture et `FirestoreConflictError` est levée."""
        patch = {k: v for k, v in (patch or {}).items() if k not in META_KEYS}
        if not patch:
            return False
        url = f"{cls.database_url(project_id)}/{collection_name}/{doc_id}"
        field_paths = list(patch.keys())
        params = []
        for p in field_paths:
            params.append(("updateMask.fieldPaths", p))
        if expected_update_time:
            params.append(("currentDocument.updateTime", expected_update_time))
        payload = {"fields": dict_to_firestore_fields(patch)}
        try:
            resp = requests.patch(url, headers=cls._headers(access_token),
                                  params=params, json=payload, timeout=30)
        except requests.RequestException as e:
            raise FirestoreError(f"Firestore injoignable ({collection_name}/{doc_id}) : {e}")
        if resp.status_code in (200, 201):
            return True
        if expected_update_time and _is_precondition_failure(resp):
            raise FirestoreConflictError(
                f"Document {collection_name}/{doc_id} modifié entre-temps (conflit d'écriture)"
            )
        raise FirestoreError(
            f"Mise à jour Firestore {collection_name}/{doc_id} : HTTP {resp.status_code} - {resp.text[:200]}"
        )

    @classmethod
    def delete_document(cls, collection_name: str, doc_id: str,
                        project_id: Optional[str] = None,
                        access_token: Optional[str] = None) -> bool:
        url = f"{cls.database_url(project_id)}/{collection_name}/{doc_id}"
        try:
            resp = requests.delete(url, headers=cls._headers(access_token), timeout=15)
        except requests.RequestException as e:
            raise FirestoreError(f"Firestore injoignable ({collection_name}/{doc_id}) : {e}")
        if resp.status_code in (200, 204):
            return True
        if resp.status_code == 404:
            return False
        raise FirestoreError(
            f"Suppression Firestore {collection_name}/{doc_id} : HTTP {resp.status_code} - {resp.text[:200]}"
        )

    @classmethod
    def batch_upsert(cls, writes: List[Dict[str, Any]],
                     project_id: Optional[str] = None,
                     access_token: Optional[str] = None) -> Dict[str, Any]:
        """Exécute des écritures par lot via :commit.

        `writes` : liste de {"path": "col/docid", "data": {...}, "update_fields": [..]?}.
        Retourne un rapport {written, errors_count, errors}.
        """
        pid = project_id or cls.get_project_id()
        url = f"{FIRESTORE_BASE_URL}/{DATABASE_PATH.format(pid=pid)}:commit"
        headers = cls._headers(access_token)
        report = {"written": 0, "errors_count": 0, "errors": []}
        for chunk_start in range(0, len(writes), BATCH_WRITE_LIMIT):
            chunk = writes[chunk_start:chunk_start + BATCH_WRITE_LIMIT]
            body = []
            for w in chunk:
                op: Dict[str, Any] = {"update": {
                    "name": f"{DATABASE_PATH.format(pid=pid)}/{w['path']}",
                    "fields": dict_to_firestore_fields(w.get("data") or {}),
                }}
                if w.get("update_fields"):
                    op["updateMask"] = {"fieldPaths": list(w["update_fields"])}
                body.append(op)
            try:
                resp = requests.post(url, headers=headers, json={"writes": body}, timeout=60)
            except requests.RequestException as e:
                report["errors_count"] += len(chunk)
                report["errors"].append(f"Firestore injoignable (commit) : {e}")
                continue
            if resp.status_code in (200, 201):
                report["written"] += len(chunk)
            else:
                report["errors_count"] += len(chunk)
                report["errors"].append(f"commit HTTP {resp.status_code} - {resp.text[:200]}")
        return report
