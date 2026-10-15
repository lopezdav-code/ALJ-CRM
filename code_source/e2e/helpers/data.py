"""
Test data set up through the application's own repository (CompetitionFirestoreRepository, the
code path of the desktop app and the HelloAsso webhook), run in a dev-mode subprocess like the
seed: the pytest process never talks to Firestore itself.

The subprocess is started once and serves every request (JSON lines on stdin / stdout): a fresh
interpreter per call cost ~0.5 s of startup and imports, against ~20 ms for the call itself.

Each test creates the competitions it changes, under a unique name, so tests stay independent
of each other and of the seeded data.
"""
import json
import queue
import subprocess
import sys
import threading
import time
import uuid

from helpers.stack import CODE_SOURCE

_RESULT, _ERROR = "__RESULT__", "__ERROR__"
_TIMEOUT = 60   # seconds per request
EVENTUALLY_TIMEOUT = 5.0   # seconds, as Playwright's expect (shortened by conftest.known_bug_timeouts)

# Each request line is {"body", "args"}: `body` runs with `args`, `Repo` and `Competition` in scope and sets
# `result`. The adherents cache is dropped first, so that every request reads Firestore as a fresh process would.
_WORKER = f"""
import json, sys, traceback
sys.path.insert(0, "src")
from domain.competition_models import Competition
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
for line in sys.stdin:
    request = json.loads(line)
    try:
        Repo._invalidate_adherents_cache()
        scope = {{"json": json, "sys": sys, "Repo": Repo, "Competition": Competition, "args": request["args"]}}
        exec(request["body"], scope)
        print({_RESULT!r} + json.dumps(scope["result"], default=str), flush=True)
    except Exception:
        print({_ERROR!r} + json.dumps(traceback.format_exc()), flush=True)
"""


def eventually(check, timeout: float = None):
    """Retries `check` (plain asserts on test_data reads) until it passes, then returns its result; after
    `timeout` (EVENTUALLY_TIMEOUT by default), its last error is raised. The pages update optimistically: a read right after the UI change
    can run before the write reaches Firestore. A missing document or participant (None, KeyError,
    StopIteration) counts as "not yet"."""
    deadline = time.monotonic() + (EVENTUALLY_TIMEOUT if timeout is None else timeout)
    while True:
        try:
            return check()
        except (AssertionError, LookupError, TypeError, StopIteration):
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


def unique_name(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:6]}"


class TestData:
    def __init__(self, env: dict):
        self.env = env
        self._process = None
        self._lines = None

    def _start(self) -> None:
        self._process = subprocess.Popen([sys.executable, "-c", _WORKER], cwd=CODE_SOURCE, env=self.env,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding="utf-8", bufsize=1)
        # Read from a thread: a blocking readline could not time out (and pipes are not selectable on Windows)
        self._lines = queue.Queue()
        threading.Thread(target=self._pump, args=(self._process.stdout, self._lines), daemon=True).start()

    @staticmethod
    def _pump(stream, lines: queue.Queue) -> None:
        for line in stream:
            lines.put(line.rstrip("\n"))
        lines.put(None)   # end of output: the worker exited

    def close(self) -> None:
        if self._process is None:
            return
        self._process.stdin.close()
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        self._process = None

    def _run(self, body: str, **args):
        """Runs `body` (which sets `result`) with the repository in dev mode; returns `result`."""
        if self._process is None or self._process.poll() is not None:
            self._start()
        self._process.stdin.write(json.dumps({"body": body, "args": args}) + "\n")
        self._process.stdin.flush()
        output = []   # the application's own prints and logs, shown on failure
        while True:
            try:
                line = self._lines.get(timeout=_TIMEOUT)
            except queue.Empty:
                self._process.kill()
                raise RuntimeError(f"test data setup timed out after {_TIMEOUT} s:\n" + "\n".join(output))
            if line is None:
                raise RuntimeError(f"test data worker exited (code {self._process.wait()}):\n" + "\n".join(output))
            if line.startswith(_RESULT):
                return json.loads(line[len(_RESULT):])
            if line.startswith(_ERROR):
                raise RuntimeError("test data setup failed:\n" + "\n".join(output) + "\n" + json.loads(line[len(_ERROR):]))
            output.append(line)

    def members(self, competition_only: bool = False) -> list:
        """Members of the `adherents` projection (id, nom, prenom, tarif, email…)."""
        return self._run("result = Repo.list_adherents(competition_only=args['only'])", only=competition_only)

    def coaches(self) -> list:
        return self._run("result = Repo.list_coaches()")

    def save_setting(self, key: str, value: str) -> None:
        """Firestore app setting (e.g. HELLOASSO_ANNUAL_CAMPAIGN), as the desktop app saves it."""
        self._run("Repo.save_app_setting(args['key'], args['value'])\nresult = True", key=key, value=value)

    def helloasso_item(self, id_item: int):
        """Mirror document of a HelloAsso item (link, ignore flag, comment), or None."""
        return self._run("result = Repo.get_item(args['id'])", id=id_item)

    def fill_geocache(self) -> int:
        """Fake coordinates (around Jonage) for every address the map would geocode, so that it
        never calls Nominatim. The addresses come from the server's own map code; the cache is
        pushed to Firestore (crm_geocache). Run before the server starts: it uses its SQLite file."""
        return self._run("""
import server
from infrastructure.cloud_database import CloudDatabase
from infrastructure.sqlite_repository import SqliteRepository

class Collect:
    addresses = []
    def add_task(self, func, addresses):
        self.addresses.extend(addresses)

CloudDatabase.sync(full=True)
collect = Collect()
server.get_sqlite_map_data(collect)
for i, address in enumerate(sorted(set(collect.addresses))):
    SqliteRepository.save_geocode(address, 45.79 + (i % 10) * 0.004, 5.04 + (i // 10) * 0.004)
CloudDatabase.flush_only()
result = len(set(collect.addresses))
""")

    def create_coach(self, nom: str) -> int:
        return self._run("result = Repo.save_coach(args['nom'])", nom=nom)

    def create_competition(self, nom: str, date: str = "", prix: float = 10.0, participants=(),
                           selected=(), coach_ids=(), id_ffme: str = "") -> int:
        """Creates a competition; `participants` are member ids, those in `selected` participate."""
        return self._run("""
ids = list(args['coach_ids']) + [None] * 3
comp = Competition(nom=args['nom'], date_competition=args['date'], prix=args['prix'], id_ffme=args['id_ffme'],
                   coach1_id=ids[0], coach2_id=ids[1], coach3_id=ids[2])
cid = Repo.save_competition(comp)
for aid in args['participants']:
    Repo.add_participant(cid, aid, selectionne=aid in args['selected'])
result = cid
""", nom=nom, date=date, prix=prix, participants=list(participants), selected=list(selected),
            coach_ids=list(coach_ids), id_ffme=id_ffme)

    def mark_paid(self, competition_id: int, adherent_id: int, amount: float, order_ref: str = "E2E-ORDER") -> None:
        """Records a HelloAsso payment (same call as the webhook)."""
        self._run("Repo.apply_helloasso_payment(args['cid'], args['aid'], args['amount'], order_ref=args['ref'])\n"
                  "result = True", cid=competition_id, aid=adherent_id, amount=amount, ref=order_ref)

    def competition(self, competition_id: int):
        """The competition document as stored (participants embedded), or None."""
        return self._run("result = Repo._load_comp_doc(args['cid'])", cid=competition_id)

    def competition_by_name(self, nom: str):
        return self._run("result = next((d for d in Repo._list_comp_docs() if d.get('nom') == args['nom']), None)",
                         nom=nom)
