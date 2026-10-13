"""
Test data set up through the application's own repository (CompetitionFirestoreRepository, the
code path of the desktop app and the HelloAsso webhook), run in a dev-mode subprocess like the
seed: the pytest process never talks to Firestore itself.

Each test creates the competitions it changes, under a unique name, so tests stay independent
of each other and of the seeded data.
"""
import json
import subprocess
import sys
import uuid

from helpers.stack import CODE_SOURCE

_PRELUDE = """
import json, sys
sys.path.insert(0, "src")
from domain.competition_models import Competition
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
args = json.loads(sys.argv[1])
"""


def unique_name(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:6]}"


class TestData:
    def __init__(self, env: dict):
        self.env = env

    def _run(self, body: str, **args):
        """Runs `body` (which sets `result`) with the repository in dev mode; returns `result`."""
        code = _PRELUDE + body + "\nprint('__RESULT__' + json.dumps(result, default=str))"
        proc = subprocess.run([sys.executable, "-c", code, json.dumps(args)], cwd=CODE_SOURCE, env=self.env,
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"test data setup failed:\n{proc.stdout}\n{proc.stderr}")
        line = next(ln for ln in reversed(proc.stdout.splitlines()) if ln.startswith("__RESULT__"))
        return json.loads(line[len("__RESULT__"):])

    def members(self, competition_only: bool = False) -> list:
        """Members of the `adherents` projection (id, nom, prenom, tarif, email…)."""
        return self._run("result = Repo.list_adherents(competition_only=args['only'])", only=competition_only)

    def coaches(self) -> list:
        return self._run("result = Repo.list_coaches()")

    def create_coach(self, nom: str) -> int:
        return self._run("result = Repo.save_coach(args['nom'])", nom=nom)

    def create_competition(self, nom: str, date: str = "", prix: float = 10.0, participants=(),
                           selected=(), coach_ids=()) -> int:
        """Creates a competition; `participants` are member ids, those in `selected` participate."""
        return self._run("""
ids = list(args['coach_ids']) + [None] * 3
comp = Competition(nom=args['nom'], date_competition=args['date'], prix=args['prix'],
                   coach1_id=ids[0], coach2_id=ids[1], coach3_id=ids[2])
cid = Repo.save_competition(comp)
for aid in args['participants']:
    Repo.add_participant(cid, aid, selectionne=aid in args['selected'])
result = cid
""", nom=nom, date=date, prix=prix, participants=list(participants), selected=list(selected),
            coach_ids=list(coach_ids))

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
