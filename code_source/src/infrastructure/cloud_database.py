"""
Base principale des adhérents adossée à Firestore.

Depuis la migration (v2.4.0), la **source de vérité** des tables de `database.db`
(adhérents, commandes, inscriptions, options, saisons, planning, modèles d'e-mails,
réglages, cache de géocodage) est Firestore : une collection `crm_<table>` par
table, un document par ligne (ID = clé primaire SQLite).

Le fichier `database.db` local devient un **cache** reconstruit depuis Firestore :
tout le code existant (SqliteRepository, vue `v_adherents_legacy`, SQL brut des
pages) continue de lire et d'écrire en SQL, sans modification.

Mécanisme :
- des déclencheurs SQLite (`_fs_*`) notent chaque ligne insérée / modifiée /
  supprimée dans `_fs_changes` ;
- `flush()` envoie ces lignes à Firestore, **champ par champ** (seules les
  colonnes modifiées depuis la dernière synchronisation sont écrites, avec la
  précondition `updateTime`) : deux postes qui modifient des champs différents
  d'un même adhérent ne s'écrasent plus ;
- `pull()` récupère les documents modifiés ailleurs (champ `_modified_at`) et
  les fusionne dans le cache (fusion à 3 voies si la ligne a aussi été modifiée
  localement) ;
- une suppression devient un document « tombe » (`_deleted: true`) pour être
  propagée aux autres postes.

Le réglage `MEMBER_BACKEND` (`firestore` par défaut, `drive` pour revenir à
l'ancien partage du fichier par Google Drive) permet un retour arrière.
"""
import base64
import datetime
import hashlib
import json
import os
import re
import socket
import sqlite3
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests

from infrastructure import runtime_env

# Tables synchronisées (les tables legacy `adherents` / `adherents_seasons`,
# remplacées par le schéma v2, ne sont pas migrées).
TRACKED_TABLES = (
    "seasons", "users", "orders", "purchases", "purchase_options",
    "planning", "email_templates", "app_settings", "geocache",
)
COLLECTION_PREFIX = "crm_"
MOD_FIELD = "_modified_at"
DEL_FIELD = "_deleted"
BY_FIELD = "_modified_by"
META_FIELDS = (MOD_FIELD, DEL_FIELD, BY_FIELD)
CACHE_FORMAT = "1"
PULL_MARGIN_SECONDS = 300
COMMIT_CHUNK = 400
# Références entre tables (pour renuméroter une ligne dont l'ID est déjà pris
# par un autre poste).
REFERENCES = {
    "seasons": [("orders", "season_id")],
    "users": [("purchases", "user_id")],
    "orders": [("purchases", "order_id")],
    "purchases": [("purchase_options", "purchase_id")],
}
DEFAULT_PROJECT_ID = "smart-amplifier-510811-n6"


class CloudSyncError(RuntimeError):
    """Échange impossible avec Firestore."""


class CloudConflictError(CloudSyncError):
    """Précondition refusée : le document a changé côté Firestore."""


def collection_for(table: str) -> str:
    return f"{COLLECTION_PREFIX}{table}"


# ----------------------------------------------------------------------
# Valeurs Firestore <-> SQLite (aller-retour exact : int, float, str, None, bytes)
# ----------------------------------------------------------------------
def encode_value(val: Any) -> Dict[str, Any]:
    if val is None:
        return {"nullValue": None}
    if isinstance(val, bool):
        return {"booleanValue": val}
    if isinstance(val, int):
        return {"integerValue": str(val)}
    if isinstance(val, float):
        if val != val:
            return {"doubleValue": "NaN"}
        if val in (float("inf"), float("-inf")):
            return {"doubleValue": "Infinity" if val > 0 else "-Infinity"}
        return {"doubleValue": val}
    if isinstance(val, (bytes, bytearray, memoryview)):
        return {"bytesValue": base64.b64encode(bytes(val)).decode("ascii")}
    return {"stringValue": str(val)}


def decode_value(f: Dict[str, Any]) -> Any:
    if not isinstance(f, dict) or "nullValue" in f:
        return None
    if "integerValue" in f:
        return int(f["integerValue"])
    if "doubleValue" in f:
        return float(f["doubleValue"])
    if "stringValue" in f:
        return f["stringValue"]
    if "booleanValue" in f:
        return bool(f["booleanValue"])
    if "bytesValue" in f:
        return base64.b64decode(f["bytesValue"])
    if "timestampValue" in f:
        return f["timestampValue"]
    return None


def quote_field_path(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    return "`" + name.replace("\\", "\\\\").replace("`", "\\`") + "`"


def doc_id_for(pk_values: List[Any]) -> str:
    """ID de document stable : la clé entière telle quelle, sinon une empreinte."""
    if len(pk_values) == 1 and isinstance(pk_values[0], int) and not isinstance(pk_values[0], bool):
        return str(pk_values[0])
    raw = json.dumps(pk_values, ensure_ascii=False, separators=(",", ":"))
    return "h" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def ts_key(ts: Optional[str]) -> Tuple:
    """Clé de comparaison d'un horodatage RFC 3339 Firestore (précision ns)."""
    if not ts:
        return (0,)
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z", ts)
    if not m:
        return (ts,)
    frac = (m.group(2) or "").ljust(9, "0")[:9]
    return (m.group(1), frac)


def ts_minus(ts: str, seconds: int) -> str:
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", ts or "")
    if not m:
        return "1970-01-01T00:00:00Z"
    dt = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S") - datetime.timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _same(a: Any, b: Any) -> bool:
    return a == b and type(a) is type(b) or (a is None and b is None)


# ----------------------------------------------------------------------
# Accès REST à Firestore
# ----------------------------------------------------------------------
class RestStore:
    """Opérations Firestore nécessaires au cache (liste, requête, lecture, commit)."""

    def __init__(self, project_id: Optional[str] = None,
                 token_provider: Optional[Callable[[], str]] = None):
        self._project_id = project_id
        self._token_provider = token_provider

    @property
    def project_id(self) -> str:
        if not self._project_id:
            self._project_id = runtime_env.project_id_override()
        if not self._project_id:
            try:
                from infrastructure.firestore_client import FirestoreClient
                self._project_id = FirestoreClient.get_project_id()
            except Exception:
                self._project_id = DEFAULT_PROJECT_ID
        return self._project_id

    def _token(self) -> str:
        if self._token_provider:
            return self._token_provider()
        emulator_tok = runtime_env.emulator_token()
        if emulator_tok:
            return emulator_tok
        env_tok = os.environ.get("ALJ_FIRESTORE_ACCESS_TOKEN", "").strip()
        if env_tok:
            return env_tok
        from infrastructure.firestore_client import FirestoreClient
        return FirestoreClient.get_access_token()

    @property
    def _root(self) -> str:
        return f"projects/{self.project_id}/databases/(default)/documents"

    @property
    def _base(self) -> str:
        return f"{runtime_env.firestore_base_url()}/{self._root}"

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        try:
            return requests.request(method, url, headers=self._headers(), timeout=60, **kw)
        except requests.RequestException as e:
            raise CloudSyncError(f"Firestore injoignable : {e}")

    @staticmethod
    def _parse_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
        raw = doc.get("fields", {}) or {}
        fields = {k: decode_value(v) for k, v in raw.items() if k not in META_FIELDS}
        return {
            "id": doc.get("name", "").rsplit("/", 1)[-1],
            "fields": fields,
            "deleted": bool(decode_value(raw.get(DEL_FIELD, {"nullValue": None}))),
            "update_time": doc.get("updateTime"),
            "modified_at": decode_value(raw.get(MOD_FIELD, {"nullValue": None})) or doc.get("updateTime"),
        }

    def list_all(self, collection: str) -> List[Dict[str, Any]]:
        url = f"{self._base}/{collection}"
        out, token = [], None
        while True:
            params = {"pageSize": 300}
            if token:
                params["pageToken"] = token
            resp = self._request("GET", url, params=params)
            if resp.status_code != 200:
                raise CloudSyncError(f"Liste {collection} : HTTP {resp.status_code} - {resp.text[:200]}")
            payload = resp.json()
            out.extend(self._parse_doc(d) for d in payload.get("documents", []))
            token = payload.get("nextPageToken")
            if not token:
                return out

    def list_modified_since(self, collection: str, since: str) -> List[Dict[str, Any]]:
        url = f"{self._base}:runQuery"
        body = {"structuredQuery": {
            "from": [{"collectionId": collection}],
            "where": {"fieldFilter": {
                "field": {"fieldPath": MOD_FIELD},
                "op": "GREATER_THAN_OR_EQUAL",
                "value": {"timestampValue": since},
            }},
        }}
        resp = self._request("POST", url, json=body)
        if resp.status_code != 200:
            raise CloudSyncError(f"Requête {collection} : HTTP {resp.status_code} - {resp.text[:200]}")
        return [self._parse_doc(r["document"]) for r in resp.json() if r.get("document")]

    def get_many(self, collection: str, doc_ids: Iterable[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        ids = list(dict.fromkeys(doc_ids))
        result: Dict[str, Optional[Dict[str, Any]]] = {}
        url = f"{self._base}:batchGet"
        for i in range(0, len(ids), 300):
            names = [f"{self._root}/{collection}/{d}" for d in ids[i:i + 300]]
            resp = self._request("POST", url, json={"documents": names})
            if resp.status_code != 200:
                raise CloudSyncError(f"Lecture {collection} : HTTP {resp.status_code} - {resp.text[:200]}")
            for r in resp.json():
                if r.get("found"):
                    d = self._parse_doc(r["found"])
                    result[d["id"]] = d
                elif r.get("missing"):
                    result[r["missing"].rsplit("/", 1)[-1]] = None
        return result

    def max_int_id(self, collection: str, field: str) -> int:
        url = f"{self._base}:runQuery"
        body = {"structuredQuery": {
            "from": [{"collectionId": collection}],
            "orderBy": [{"field": {"fieldPath": quote_field_path(field)}, "direction": "DESCENDING"}],
            "limit": 1,
        }}
        resp = self._request("POST", url, json=body)
        if resp.status_code != 200:
            raise CloudSyncError(f"Requête {collection} : HTTP {resp.status_code} - {resp.text[:200]}")
        for r in resp.json():
            if r.get("document"):
                v = self._parse_doc(r["document"])["fields"].get(field)
                return int(v) if isinstance(v, int) else 0
        return 0

    def commit(self, writes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Écritures atomiques. Chaque écriture :
        {collection, doc_id, fields, mask (liste|None), deleted, by, precondition}
        Retourne [{update_time, modified_at}] dans l'ordre."""
        if not writes:
            return []
        url = f"{self._base}:commit"
        body = []
        for w in writes:
            fields = {k: encode_value(v) for k, v in (w.get("fields") or {}).items()}
            fields[DEL_FIELD] = {"booleanValue": bool(w.get("deleted"))}
            fields[BY_FIELD] = {"stringValue": w.get("by") or ""}
            op: Dict[str, Any] = {
                "update": {"name": f"{self._root}/{w['collection']}/{w['doc_id']}", "fields": fields},
                "updateTransforms": [{"fieldPath": MOD_FIELD, "setToServerValue": "REQUEST_TIME"}],
            }
            if w.get("mask") is not None:
                paths = [quote_field_path(k) for k in w["mask"]] + [DEL_FIELD, BY_FIELD]
                op["updateMask"] = {"fieldPaths": paths}
            pre = w.get("precondition")
            if pre:
                op["currentDocument"] = pre
            body.append(op)
        resp = self._request("POST", url, json={"writes": body})
        if resp.status_code == 200:
            out = []
            for r in resp.json().get("writeResults", []):
                tr = (r.get("transformResults") or [{}])[0]
                out.append({"update_time": r.get("updateTime"),
                            "modified_at": tr.get("timestampValue") or r.get("updateTime")})
            return out
        text = resp.text or ""
        if resp.status_code in (404, 409) or "FAILED_PRECONDITION" in text or "ALREADY_EXISTS" in text:
            raise CloudConflictError(f"commit HTTP {resp.status_code} - {text[:200]}")
        raise CloudSyncError(f"commit HTTP {resp.status_code} - {text[:300]}")


# ----------------------------------------------------------------------
# Cache SQLite local
# ----------------------------------------------------------------------
def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA recursive_triggers=ON")
    return conn


def table_exists(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone() is not None


def table_columns(conn, table: str) -> List[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def table_pk(conn, table: str) -> List[str]:
    cols = [(r[5], r[1]) for r in conn.execute(f'PRAGMA table_info("{table}")') if r[5]]
    return [c for _, c in sorted(cols)]


def tracked_tables(conn) -> List[str]:
    return [t for t in TRACKED_TABLES if table_exists(conn, t)]


def install_tracking(conn):
    """Crée les tables techniques et les déclencheurs de suivi (idempotent)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS _fs_changes (tbl TEXT NOT NULL, pk TEXT NOT NULL,
            seq INTEGER NOT NULL, PRIMARY KEY (tbl, pk));
        CREATE TABLE IF NOT EXISTS _fs_counter (id INTEGER PRIMARY KEY CHECK (id = 1), n INTEGER NOT NULL);
        INSERT OR IGNORE INTO _fs_counter (id, n) VALUES (1, 0);
        CREATE TABLE IF NOT EXISTS _fs_base (tbl TEXT NOT NULL, pk TEXT NOT NULL,
            data TEXT NOT NULL, ut TEXT, PRIMARY KEY (tbl, pk));
        CREATE TABLE IF NOT EXISTS _fs_state (k TEXT PRIMARY KEY, v TEXT);
    """)
    for t in tracked_tables(conn):
        pk = table_pk(conn, t)
        if not pk:
            continue

        def pk_expr(prefix):
            return "json_array(" + ", ".join(f'{prefix}."{c}"' for c in pk) + ")"

        def log(prefix):
            return (f"DELETE FROM _fs_changes WHERE tbl = '{t}' AND pk = {pk_expr(prefix)}; "
                    f"INSERT INTO _fs_changes (tbl, pk, seq) VALUES ('{t}', {pk_expr(prefix)}, "
                    f"(SELECT n FROM _fs_counter WHERE id = 1)); ")
        guard = "WHEN NOT EXISTS (SELECT 1 FROM _fs_state WHERE k = 'applying' AND v = '1')"
        bump = "UPDATE _fs_counter SET n = n + 1 WHERE id = 1; "
        conn.executescript(f"""
            CREATE TRIGGER IF NOT EXISTS "_fs_{t}_ai" AFTER INSERT ON "{t}" {guard}
            BEGIN {bump}{log('NEW')}END;
            CREATE TRIGGER IF NOT EXISTS "_fs_{t}_au" AFTER UPDATE ON "{t}" {guard}
            BEGIN {bump}{log('OLD')}{log('NEW')}END;
            CREATE TRIGGER IF NOT EXISTS "_fs_{t}_ad" AFTER DELETE ON "{t}" {guard}
            BEGIN {bump}{log('OLD')}END;
        """)


def get_state(conn, key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        r = conn.execute("SELECT v FROM _fs_state WHERE k = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return default
    return r[0] if r else default


def set_state(conn, key: str, value: str):
    conn.execute("INSERT INTO _fs_state (k, v) VALUES (?, ?) "
                 "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (key, value))


def pending_count(conn) -> int:
    try:
        return conn.execute("SELECT COUNT(*) FROM _fs_changes").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _pk_string(conn, values: List[Any]) -> str:
    return conn.execute("SELECT json_array(" + ",".join("?" * len(values)) + ")", values).fetchone()[0]


def _where(pk: List[str]) -> str:
    return " AND ".join(f'"{c}" IS ?' for c in pk)


def _read_row(conn, table: str, pk: List[str], values: List[Any]) -> Optional[Dict[str, Any]]:
    r = conn.execute(f'SELECT * FROM "{table}" WHERE {_where(pk)}', values).fetchone()
    return dict(r) if r else None


def _upsert_row(conn, table: str, cols: List[str], pk: List[str], data: Dict[str, Any]):
    use = [c for c in cols if c in data]
    if not all(c in use for c in pk):
        raise CloudSyncError(f"Document {table} sans clé primaire complète")
    placeholders = ", ".join("?" for _ in use)
    col_sql = ", ".join(f'"{c}"' for c in use)
    upd = [c for c in use if c not in pk]
    sql = f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders}) ON CONFLICT({", ".join(chr(34) + c + chr(34) for c in pk)}) '
    sql += ("DO UPDATE SET " + ", ".join(f'"{c}" = excluded."{c}"' for c in upd)) if upd else "DO NOTHING"
    conn.execute(sql, [data[c] for c in use])


def _set_base(conn, table: str, pk_str: str, data: Dict[str, Any], ut: Optional[str]):
    conn.execute("INSERT INTO _fs_base (tbl, pk, data, ut) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT(tbl, pk) DO UPDATE SET data = excluded.data, ut = excluded.ut",
                 (table, pk_str, json.dumps(data, ensure_ascii=False), ut))


def _get_base(conn, table: str, pk_str: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    r = conn.execute("SELECT data, ut FROM _fs_base WHERE tbl = ? AND pk = ?", (table, pk_str)).fetchone()
    if not r:
        return None, None
    return json.loads(r[0]), r[1]


class _Applying:
    """Désactive les déclencheurs de suivi dans la transaction courante."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        set_state(self.conn, "applying", "1")

    def __exit__(self, *exc):
        set_state(self.conn, "applying", "0")


def renumber_row(conn, store, table: str, old_id: int, report: Dict[str, Any]) -> int:
    """Donne un nouvel identifiant à une ligne locale dont l'ID est déjà utilisé
    dans Firestore par une autre ligne (deux postes ont créé en même temps).
    Les références (REFERENCES) sont mises à jour ; les déclencheurs notent tout."""
    pk = table_pk(conn, table)[0]
    local_max = conn.execute(f'SELECT COALESCE(MAX("{pk}"), 0) FROM "{table}"').fetchone()[0]
    remote_max = store.max_int_id(collection_for(table), pk)
    new_id = max(local_max, remote_max) + 1
    conn.execute(f'UPDATE "{table}" SET "{pk}" = ? WHERE "{pk}" = ?', (new_id, old_id))
    for ref_table, ref_col in REFERENCES.get(table, []):
        if table_exists(conn, ref_table):
            conn.execute(f'UPDATE "{ref_table}" SET "{ref_col}" = ? WHERE "{ref_col}" = ?', (new_id, old_id))
    report.setdefault("renumbered", []).append(f"{table} {old_id} -> {new_id}")
    return new_id


def apply_remote_docs(conn, store, table: str, docs: List[Dict[str, Any]], report: Dict[str, Any]):
    """Intègre des documents Firestore dans le cache (fusion à 3 voies si besoin)."""
    if not docs:
        return
    cols = table_columns(conn, table)
    pk = table_pk(conn, table)
    conn.execute("BEGIN IMMEDIATE")
    try:
        with _Applying(conn):
            for d in docs:
                vals = [d["fields"].get(c) for c in pk]
                if any(v is None for v in vals):
                    continue
                pk_str = _pk_string(conn, vals)
                base, base_ut = _get_base(conn, table, pk_str)
                if base_ut and ts_key(base_ut) >= ts_key(d["update_time"]):
                    continue
                dirty = conn.execute("SELECT 1 FROM _fs_changes WHERE tbl = ? AND pk = ?",
                                     (table, pk_str)).fetchone() is not None
                local = _read_row(conn, table, pk, vals)
                if d["deleted"]:
                    if base is None and dirty and local is not None:
                        # Ligne créée ici avec un ID supprimé ailleurs : on la garde.
                        continue
                    conn.execute(f'DELETE FROM "{table}" WHERE {_where(pk)}', vals)
                    conn.execute("DELETE FROM _fs_base WHERE tbl = ? AND pk = ?", (table, pk_str))
                    conn.execute("DELETE FROM _fs_changes WHERE tbl = ? AND pk = ?", (table, pk_str))
                    report["pulled"] = report.get("pulled", 0) + 1
                    continue
                remote = {c: d["fields"][c] for c in cols if c in d["fields"]}
                if dirty and base is None and local is not None:
                    # Même ID créé sur deux postes : renuméroter la ligne locale.
                    if len(pk) == 1 and isinstance(vals[0], int):
                        with _Resume(conn):
                            renumber_row(conn, store, table, vals[0], report)
                        local = None
                    else:
                        merged = dict(remote)
                        merged.update(local)
                        _upsert_row(conn, table, cols, pk, merged)
                        _set_base(conn, table, pk_str, remote, d["update_time"])
                        continue
                if dirty and local is not None and base is not None:
                    merged = dict(remote)
                    for c, v in local.items():
                        if not _same(v, base.get(c)) and (c in base or v is not None):
                            merged[c] = v
                    _upsert_row(conn, table, cols, pk, merged)
                elif dirty and local is None and base is not None:
                    pass  # supprimée ici : la suppression sera envoyée
                else:
                    try:
                        _upsert_row(conn, table, cols, pk, remote)
                    except sqlite3.IntegrityError as e:
                        report.setdefault("errors", []).append(f"{table}/{d['id']} : {e}")
                        continue
                _set_base(conn, table, pk_str, remote, d["update_time"])
                report["pulled"] = report.get("pulled", 0) + 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


class _Resume:
    """Réactive temporairement le suivi (pour qu'une renumérotation soit envoyée)."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        set_state(self.conn, "applying", "0")

    def __exit__(self, *exc):
        set_state(self.conn, "applying", "1")


def pull(conn, store, report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Récupère les documents modifiés depuis la dernière synchronisation."""
    report = report if report is not None else {}
    for t in tracked_tables(conn):
        coll = collection_for(t)
        wm = get_state(conn, f"wm:{t}") or "1970-01-01T00:00:00Z"
        docs = store.list_modified_since(coll, ts_minus(wm, PULL_MARGIN_SECONDS))
        apply_remote_docs(conn, store, t, docs, report)
        if docs:
            newest = max((d["modified_at"] for d in docs if d.get("modified_at")), key=ts_key, default=wm)
            if ts_key(newest) > ts_key(wm):
                set_state(conn, f"wm:{t}", newest)
    set_state(conn, "last_pull", datetime.datetime.now().isoformat(timespec="seconds"))
    return report


def _build_write(conn, table: str, cols: List[str], pk: List[str], pk_str: str, by: str):
    """Prépare l'écriture d'une ligne modifiée. Retourne (write, row, base) ou None."""
    vals = json.loads(pk_str)
    row = _read_row(conn, table, pk, vals)
    base, base_ut = _get_base(conn, table, pk_str)
    w = {"collection": collection_for(table), "doc_id": doc_id_for(vals), "by": by}
    if row is None:
        if base is None:
            return None
        w.update(fields={c: v for c, v in zip(pk, vals, strict=False)}, mask=None, deleted=True,
                 precondition={"updateTime": base_ut} if base_ut else None)
        return w, None
    if base is None:
        w.update(fields=row, mask=None, deleted=False, precondition=None, create=True)
        return w, row
    diff = {c: v for c, v in row.items() if c not in base or not _same(v, base.get(c))}
    if not diff:
        return {"noop": True}, row
    w.update(fields=diff, mask=list(diff.keys()), deleted=False,
             precondition={"updateTime": base_ut} if base_ut else {"exists": True})
    return w, row


def flush(conn, store, by: str = "", report: Optional[Dict[str, Any]] = None,
          _depth: int = 0) -> Dict[str, Any]:
    """Envoie les lignes modifiées localement vers Firestore."""
    report = report if report is not None else {}
    changes = conn.execute("SELECT tbl, pk, seq FROM _fs_changes ORDER BY seq").fetchall()
    if not changes:
        return report
    meta = {}
    items = []  # (table, pk_str, seq, write, row)
    for ch in changes:
        t, pk_str, seq = ch["tbl"], ch["pk"], ch["seq"]
        if t not in meta:
            if not table_exists(conn, t):
                conn.execute("DELETE FROM _fs_changes WHERE tbl = ?", (t,))
                continue
            meta[t] = (table_columns(conn, t), table_pk(conn, t))
        cols, pk = meta[t]
        built = _build_write(conn, t, cols, pk, pk_str, by)
        if built is None or built[0].get("noop"):
            row = None if built is None else built[1]
            conn.execute("DELETE FROM _fs_changes WHERE tbl = ? AND pk = ? AND seq <= ?", (t, pk_str, seq))
            continue
        items.append((t, pk_str, seq, built[0], built[1]))

    # Créations : vérifier que l'ID n'est pas déjà pris (tombe => on écrase la tombe)
    collisions = []
    by_table: Dict[str, List[int]] = {}
    for i, it in enumerate(items):
        if it[3].get("create"):
            by_table.setdefault(it[0], []).append(i)
    for t, idxs in by_table.items():
        found = store.get_many(collection_for(t), [items[i][3]["doc_id"] for i in idxs])
        for i in idxs:
            w = items[i][3]
            remote = found.get(w["doc_id"])
            if remote is None:
                w["precondition"] = {"exists": False}
            elif remote["deleted"]:
                w["precondition"] = {"updateTime": remote["update_time"]}
            else:
                same = all(_same(remote["fields"].get(c), v) for c, v in items[i][4].items())
                if same or len(meta[t][1]) != 1 or not isinstance(json.loads(items[i][1])[0], int):
                    # Contenu identique, ou clé « métier » (texte) : on adopte / écrase.
                    w["precondition"] = {"updateTime": remote["update_time"]}
                else:
                    collisions.append(i)
    if collisions:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for i in collisions:
                renumber_row(conn, store, items[i][0], json.loads(items[i][1])[0], report)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        if _depth < 3:
            return flush(conn, store, by, report, _depth + 1)
        report.setdefault("errors", []).append("Conflits d'identifiants non résolus")
        return report

    def done(it, res):
        t, pk_str, seq, w, row = it
        if row is None:
            conn.execute("DELETE FROM _fs_base WHERE tbl = ? AND pk = ?", (t, pk_str))
            report["deleted"] = report.get("deleted", 0) + 1
        else:
            base, _ = _get_base(conn, t, pk_str)
            new_base = dict(base or {})
            new_base.update(row if w.get("mask") is None else w["fields"])
            _set_base(conn, t, pk_str, new_base, res.get("update_time"))
            report["pushed"] = report.get("pushed", 0) + 1
        conn.execute("DELETE FROM _fs_changes WHERE tbl = ? AND pk = ? AND seq <= ?", (t, pk_str, seq))
        touched = report.setdefault("tables", [])
        if t not in touched:
            touched.append(t)

    conflicts = []
    for start in range(0, len(items), COMMIT_CHUNK):
        chunk = items[start:start + COMMIT_CHUNK]
        try:
            results = store.commit([it[3] for it in chunk])
            for it, res in zip(chunk, results, strict=False):
                done(it, res)
        except CloudConflictError:
            for it in chunk:
                try:
                    res = store.commit([it[3]])[0]
                    done(it, res)
                except CloudConflictError:
                    conflicts.append(it)
    if conflicts:
        report["conflicts"] = report.get("conflicts", 0) + len(conflicts)
        # Relire les documents en conflit, fusionner, puis renvoyer.
        for t in {it[0] for it in conflicts}:
            ids = [it[3]["doc_id"] for it in conflicts if it[0] == t]
            found = store.get_many(collection_for(t), ids)
            apply_remote_docs(conn, store, t, [d for d in found.values() if d], report)
        if _depth < 3:
            return flush(conn, store, by, report, _depth + 1)
        report.setdefault("errors", []).append(f"{len(conflicts)} écriture(s) en conflit non résolue(s)")
    return report


# ----------------------------------------------------------------------
# Construction complète du cache et export initial
# ----------------------------------------------------------------------
def create_schema(path: str):
    """Crée une base vide au schéma de l'application (SqliteRepository)."""
    from infrastructure.sqlite_repository import SqliteRepository as R
    saved = (R._db_path, R._db_path_overridden, R._database_setup_done, R._startup_db_hash)
    try:
        R._db_path = path
        R._db_path_overridden = True
        R._database_setup_done = False
        R.setup_database(force=True)
    finally:
        R._db_path, R._db_path_overridden, R._database_setup_done, R._startup_db_hash = saved


def _remove_db_files(path: str):
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(path + suffix)
        except FileNotFoundError:
            pass


def build_cache(path: str, store, schema_factory: Callable[[str], None] = create_schema,
                backup_dir: Optional[str] = None) -> Dict[str, Any]:
    """Reconstruit intégralement le cache `path` depuis Firestore (remplacement atomique)."""
    report: Dict[str, Any] = {"loaded": {}}
    tmp = path + ".building"
    _remove_db_files(tmp)
    schema_factory(tmp)
    conn = connect(tmp)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("BEGIN")
        for t in TRACKED_TABLES:
            if table_exists(conn, t):
                conn.execute(f'DELETE FROM "{t}"')
        conn.execute("COMMIT")
        install_tracking(conn)
        conn.execute("BEGIN")
        with _Applying(conn):
            for t in tracked_tables(conn):
                cols, pk = table_columns(conn, t), table_pk(conn, t)
                docs = store.list_all(collection_for(t))
                n, wm = 0, "1970-01-01T00:00:00Z"
                for d in docs:
                    if d.get("modified_at") and ts_key(d["modified_at"]) > ts_key(wm):
                        wm = d["modified_at"]
                    if d["deleted"]:
                        continue
                    remote = {c: d["fields"][c] for c in cols if c in d["fields"]}
                    _upsert_row(conn, t, cols, pk, remote)
                    _set_base(conn, t, _pk_string(conn, [remote[c] for c in pk]), remote, d["update_time"])
                    n += 1
                set_state(conn, f"wm:{t}", wm)
                report["loaded"][t] = n
        conn.execute("DELETE FROM _fs_changes")
        set_state(conn, "format", CACHE_FORMAT)
        set_state(conn, "project", store.project_id)
        set_state(conn, "built_at", datetime.datetime.now().isoformat(timespec="seconds"))
        conn.execute("COMMIT")
    finally:
        conn.close()
    if os.path.exists(path):
        if backup_dir:
            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                bk = sqlite3.connect(path)
                dst = sqlite3.connect(os.path.join(backup_dir, f"database_avant_firestore_{stamp}.db"))
                bk.backup(dst)
                dst.close()
                bk.close()
            except Exception as e:
                print(f"⚠️ [CLOUD_DB] Sauvegarde de l'ancien cache impossible : {e}")
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass
    os.replace(tmp, path)
    return report


def cache_is_valid(path: str, project_id: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        conn = connect(path)
        try:
            return (get_state(conn, "format") == CACHE_FORMAT
                    and get_state(conn, "project") == project_id)
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def export_rows(conn, table: str) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(f'SELECT * FROM "{table}"')]


def import_database(src_path: str, store, by: str = "migration") -> Dict[str, int]:
    """Écrit toutes les lignes des tables suivies de `src_path` dans Firestore
    (documents complets, ré-exécutable sans doublon)."""
    conn = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    counts = {}
    try:
        for t in tracked_tables(conn):
            pk = table_pk(conn, t)
            writes = []
            for row in export_rows(conn, t):
                writes.append({"collection": collection_for(t), "doc_id": doc_id_for([row[c] for c in pk]),
                               "fields": row, "mask": None, "deleted": False, "by": by})
            for i in range(0, len(writes), COMMIT_CHUNK):
                store.commit(writes[i:i + COMMIT_CHUNK])
            counts[t] = len(writes)
    finally:
        conn.close()
    return counts


# ----------------------------------------------------------------------
# Façade utilisée par l'application
# ----------------------------------------------------------------------
class CloudDatabase:
    """Point d'entrée : synchronisation du cache `database.db` avec Firestore."""

    _lock = threading.RLock()
    _store = None
    _last_report: Dict[str, Any] = {}
    _last_error = ""
    _last_sync = 0.0
    _last_pull = 0.0
    _projection_dirty = False
    _last_projection = 0.0
    _bg_thread = None
    _bg_stop = threading.Event()

    @staticmethod
    def backend() -> str:
        val = os.environ.get("MEMBER_BACKEND", "").strip().lower()
        if not val:
            try:
                from infrastructure.secret_store import SecretStore
                val = (SecretStore.get_secret("MEMBER_BACKEND") or "").strip().lower()
            except Exception:
                val = ""
        if not val:
            val = "drive" if os.environ.get("PYTEST_CURRENT_TEST") else "firestore"
        return val

    @classmethod
    def is_enabled(cls) -> bool:
        return cls.backend() == "firestore"

    @classmethod
    def store(cls):
        if cls._store is None:
            cls._store = RestStore()
        return cls._store

    @staticmethod
    def db_path() -> str:
        from infrastructure.sqlite_repository import SqliteRepository
        return SqliteRepository.get_db_path()

    @staticmethod
    def who() -> str:
        try:
            return f"{os.environ.get('USERNAME') or os.environ.get('USER') or '?'}@{socket.gethostname()}"
        except Exception:
            return "?"

    @classmethod
    def is_db_path(cls, path: str) -> bool:
        try:
            return os.path.abspath(path) == os.path.abspath(cls.db_path())
        except Exception:
            return False

    @classmethod
    def sync(cls, full: bool = False, progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """Met le cache à jour : reconstruction si besoin, puis réception et envoi."""
        with cls._lock:
            path = cls.db_path()
            store = cls.store()
            report: Dict[str, Any] = {}
            try:
                if full or not cache_is_valid(path, store.project_id):
                    if progress:
                        progress("Chargement complet de la base depuis Firestore…")
                    backup_dir = os.path.join(os.path.dirname(path), "backups")
                    report = build_cache(path, store, backup_dir=backup_dir)
                    from infrastructure.sqlite_repository import SqliteRepository
                    SqliteRepository._database_setup_done = False
                    SqliteRepository.setup_database()
                    conn = connect(path)
                    try:
                        install_tracking(conn)
                    finally:
                        conn.close()
                    report["full"] = True
                conn = connect(path)
                try:
                    install_tracking(conn)
                    if progress:
                        progress("Réception des modifications Firestore…")
                    pull(conn, store, report)
                    if progress:
                        progress("Envoi des modifications locales…")
                    flush(conn, store, cls.who(), report)
                    try:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    except sqlite3.DatabaseError:
                        pass
                finally:
                    conn.close()
                cls._after_sync(report)
                cls._last_pull = time.time()
                cls._last_error = ""
            except Exception as e:
                cls._last_error = str(e)
                report.setdefault("errors", []).append(str(e))
                print(f"❌ [CLOUD_DB] Synchronisation Firestore impossible : {e}")
            cls._last_report = report
            cls._last_sync = time.time()
            return report

    @classmethod
    def flush_only(cls) -> Dict[str, Any]:
        with cls._lock:
            path = cls.db_path()
            report: Dict[str, Any] = {}
            if not cache_is_valid(path, cls.store().project_id):
                return report
            conn = connect(path)
            try:
                if pending_count(conn):
                    flush(conn, cls.store(), cls.who(), report)
            except Exception as e:
                cls._last_error = str(e)
                report.setdefault("errors", []).append(str(e))
                print(f"❌ [CLOUD_DB] Envoi vers Firestore impossible : {e}")
            finally:
                conn.close()
            cls._after_sync(report)
            return report

    @classmethod
    def _after_sync(cls, report: Dict[str, Any]):
        if set(report.get("tables") or []) & {"users", "orders", "purchases", "planning", "seasons"}:
            cls._projection_dirty = True
        if report.get("pushed") or report.get("deleted") or report.get("pulled"):
            print(f"☁️ [CLOUD_DB] envoyés={report.get('pushed', 0)} supprimés={report.get('deleted', 0)} "
                  f"reçus={report.get('pulled', 0)} conflits={report.get('conflicts', 0)}")

    @classmethod
    def refresh_projection(cls, force: bool = False):
        """Met à jour l'annuaire `adherents` / `planning` lu par la PWA et le webhook."""
        if not (cls._projection_dirty or force):
            return
        try:
            from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository
            rep = CompetitionFirestoreRepository.sync_adherents_from_main()
            if not rep.get("errors"):
                cls._projection_dirty = False
            cls._last_projection = time.time()
        except Exception as e:
            print(f"⚠️ [CLOUD_DB] Mise à jour de l'annuaire Firestore impossible : {e}")

    @classmethod
    def status(cls) -> Dict[str, Any]:
        path = cls.db_path()
        pending = 0
        if os.path.exists(path):
            try:
                conn = connect(path)
                pending = pending_count(conn)
                conn.close()
            except Exception:
                pass
        return {"pending": pending, "last_error": cls._last_error, "last_sync": cls._last_sync}

    @classmethod
    def background_tick(cls, pull_every: int = 120, projection_every: int = 180):
        if not cls.is_enabled() or not cache_is_valid(cls.db_path(), cls.store().project_id):
            return
        try:
            if time.time() - cls._last_pull >= pull_every:
                cls.sync()
            else:
                cls.flush_only()
            if cls._projection_dirty and time.time() - cls._last_projection >= projection_every:
                cls.refresh_projection()
        except Exception as e:
            print(f"⚠️ [CLOUD_DB] Synchronisation d'arrière-plan : {e}")

    @classmethod
    def start_background(cls, interval: int = 15):
        if cls._bg_thread and cls._bg_thread.is_alive():
            return
        cls._bg_stop.clear()

        def loop():
            while not cls._bg_stop.wait(interval):
                cls.background_tick()
        cls._bg_thread = threading.Thread(target=loop, name="cloud-db-sync", daemon=True)
        cls._bg_thread.start()

    @classmethod
    def stop_background(cls):
        cls._bg_stop.set()

    @classmethod
    def cache_ready(cls) -> bool:
        """Vrai si un cache local issu de Firestore est disponible (même hors ligne)."""
        path = cls.db_path()
        if not os.path.exists(path):
            return False
        try:
            conn = connect(path)
            try:
                return get_state(conn, "format") == CACHE_FORMAT
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            return False

    @classmethod
    def ensure_fresh(cls, max_age: int = 30) -> None:
        """Serveur (Cloud Run) : construit le cache au premier appel, puis récupère
        les modifications si la dernière réception date de plus de `max_age` s."""
        if not cls.is_enabled():
            return
        if (not cache_is_valid(cls.db_path(), cls.store().project_id)
                or time.time() - cls._last_pull >= max_age):
            cls.sync()

    @classmethod
    def after_write(cls) -> None:
        """Envoie aussitôt les modifications locales (serveur) et met à jour
        l'annuaire `adherents` de la PWA si des adhérents / le planning ont changé."""
        if not cls.is_enabled():
            return
        cls.flush_only()
        cls.refresh_projection()
