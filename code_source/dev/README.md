# Environnement de développement local

Front + API + Firestore en local, sur l'**émulateur Firebase** (Auth + Firestore) du projet
fictif `demo-alj`, avec des **données fictives** (univers Harry Potter). Aucun accès possible
aux données de production : un projet `demo-*` n'existe pas chez Google et le serveur refuse
le mode dev sur Cloud Run. Détails et architecture : `ARCHITECTURE.md` §7.

## Démarrage

Prérequis : Docker, et le venv du projet (`requirements-docker.txt` + `requirements-dev.txt`).

```bash
cd code_source
docker compose -f dev/docker-compose.yml up -d     # émulateur (UI :4000) + Mailpit (UI :8025)
source venv/bin/activate
set -a && source dev/dev.env && set +a
python dev/seed/seed_emulator.py                    # réinitialise + données fictives
dev/run_server.sh                                   # http://localhost:8080/bureau/
```

Connexion : le bouton « Se connecter » ouvre le sélecteur de comptes de l'émulateur.

| Compte | Rôle |
|---|---|
| `albus.dumbledore@alj-escalade.fr` | admin (domaine du club) |
| `severus.snape@hogwarts.example` | coach (custom claim) |
| `argus.filch@hogwarts.example` | lecture seule (custom claim) |

« Add new account » permet d'en créer d'autres (e-mail libre, claims JSON).

## Bon à savoir

- **Bandeau orange « DEV »** en bas de page : la page est branchée sur l'émulateur.
- **E-mails** : l'application envoie par son SMTP habituel, dirigé par `dev.env` vers **Mailpit**, qui les garde
  sans jamais les relayer. Lecture (HTML, pièces jointes PDF) : http://localhost:8025, ou
  `docker compose -f dev/docker-compose.yml logs -f mailpit`. Messages perdus au redémarrage du conteneur.
- **Garde-fou** : `run_server.sh` lance `check_env.py`, qui lit la configuration effective (y compris les `.env`
  du dépôt, prioritaires sur `dev.env`) et refuse de démarrer si l'API Gmail est active ou si le SMTP n'est pas local.
- **Persistance** : l'émulateur exporte ses données dans `dev/.emulator-data/` à l'arrêt
  (`docker compose -f dev/docker-compose.yml down`) et les recharge au démarrage.
  Relancer le seed repart de zéro (et vide le cache `data-dev/` du serveur).
- **Règles** : l'émulateur applique le vrai `firestore.rules` (monté en lecture seule).
- **HelloAsso** : `/api/dashboard` et la synchro HelloAsso appellent l'API HelloAsso réelle (lecture)
  si des identifiants sont configurés ; sans eux, ces écrans sont en erreur. En mode dev uniquement,
  `HELLOASSO_API_BASE_URL` / `HELLOASSO_OAUTH_URL` les redirigent vers un faux HelloAsso local
  (`e2e/fakes/helloasso_fake.py`, utilisé par les tests e2e) ; `check_env.py` refuse toute autre adresse.
- **Service worker** : en cas de page figée après un changement, « Mettre à jour » sur le badge
  de version ou désenregistrer le SW (DevTools → Application).

## Tests e2e (Playwright)

Tests navigateur de bout en bout dans `code_source/e2e/`, sur leur **propre pile jetable** (émulateur + Mailpit,
`e2e/docker-compose.yml`), que la suite démarre puis supprime elle-même : la pile de dev ci-dessus et ses données
ne sont jamais touchées, et chaque exécution part d'un émulateur neuf. Ils sont lancés par la CI (job `e2e` de
`.github/workflows/tests.yml`, Ubuntu) à chaque PR et push sur `main`.

```bash
cd code_source
pip install -r requirements-docker.txt -r requirements-e2e.txt
python -m playwright install --with-deps chromium    # WSL/Linux : bibliothèques système (sudo)
python -m pytest -c e2e/pytest.ini e2e -m smoke      # rapide ; sans -m : toute la suite
```

- **En parallèle** : 4 processus (pytest-xdist, `-n 4` dans `e2e/pytest.ini`), environ 1 min pour toute la suite.
  La pile, le seed, le faux HelloAsso et le serveur sont démarrés une seule fois, par le processus principal
  (`e2e/helpers/session.py`), puis partagés par les 4 processus. Au-delà de 4 sous WSL (~3 Go libres), la mémoire
  sature et la suite ralentit. `-n 0` : un seul processus (pour déboguer avec `--headed`).
- Tests qui modifient un état lu par d'autres tests (faux HelloAsso, créneaux du planning) : même
  `xdist_group` (`pytestmark`), exécutés l'un après l'autre sur un même processus. Mailpit n'est vidé qu'une fois par
  exécution : chercher ses e-mails par destinataire **et** sujet (`unique_name`).
- Ports de la pile e2e : Firestore `18081`, Auth `19099`, Mailpit `18025` (SMTP `11025`) ; serveur de test
  `8090` (`E2E_PORT`), faux HelloAsso `8095`. La pile de dev (`8081`, `9099`, `8025`) et `run_server.sh` (`8080`)
  peuvent rester lancés. Docker est requis.
- `E2E_KEEP_STACK=1` garde la pile e2e après l'exécution (itérations rapides, ou lecture des journaux :
  `docker compose -f e2e/docker-compose.yml logs`) ; la suite la réensemence à chaque exécution. La supprimer ensuite
  (`docker compose -f e2e/docker-compose.yml down`) : la mémoire de l'émulateur grossit à chaque exécution.
- **Sans installer les bibliothèques système de Chromium** (WSL sans sudo) : navigateur servi par l'image
  officielle Playwright (même version que `requirements-e2e.txt`), réseau de l'hôte pour joindre `localhost` :
  ```bash
  docker run -d --name alj-e2e-browser --network host --init --ipc=host --user pwuser \
    mcr.microsoft.com/playwright:v1.63.0-noble \
    /bin/sh -c "cd /home/pwuser && npx -y playwright@1.63.0 run-server --port 3000 --host 127.0.0.1"
  E2E_PLAYWRIGHT_WS=ws://127.0.0.1:3000/ python -m pytest -c e2e/pytest.ini e2e
  ```
- Connexion sans passer par le sélecteur de comptes : `login_as(page, "admin" | "coach" | "readonly")`
  (`e2e/helpers/auth.py`). E-mails : fixture `mailpit` (`e2e/helpers/mailpit.py`). Données de test : fixture
  `test_data` (`e2e/helpers/data.py`), qui passe par le dépôt de l'application ; chaque test crée ses propres
  compétitions sous un nom unique.
  Les pages mettent à jour l'affichage avant l'écriture Firestore : une lecture après une action dans la page passe
  par `eventually(check)` (même fichier), qui réessaie ses `assert` jusqu'à 5 s.
- Bugs connus (`xfail`) : délais de 2 s au lieu de 5 s / 30 s (fixture `known_bug_timeouts`) ; pas de `timeout=`
  explicite sur l'étape qui échoue.
- HelloAsso : fixture `fake_helloasso` (faux serveur sur le port `8095`, `e2e/helpers/helloasso.py`) ; chaque test
  y charge ses propres paiements (`fake_helloasso.set([item(...)])`), le webhook est appelé avec
  `HELLOASSO_WEBHOOK_TOKEN`.
- Bugs connus : tests marqués `xfail(strict=True)` avec la référence du bug (ex. A6 de
  `docs/plan_api_only_front.md`). Ils échouent (XPASS) dès que le bug est corrigé : retirer alors le marqueur.
- Déboguer : `-n 0 --headed --slowmo 300`, ou `--tracing retain-on-failure` puis
  `python -m playwright show-trace e2e-results/<test>/trace.zip`. Journaux de la pile, du serveur et du seed :
  `test-results/stack.log`, `test-results/server.log` (`e2e-results/` avec `--output e2e-results`, comme la CI).
- En CI, en cas d'échec : artefact `e2e-results` (traces, captures, vidéos, journaux serveur et Docker).

## Fichiers

| Fichier | Rôle |
|---|---|
| `docker-compose.yml`, `emulator/Dockerfile` | émulateur Firebase (`firebase-tools` épinglé, Node 22 + Java 21) et Mailpit |
| `dev.env` | variables du mode dev (`ALJ_ENV=dev`, hôtes de l'émulateur…) — aucun secret |
| `run_server.sh` | charge `dev.env`, vérifie l'émulateur et Mailpit, lance `check_env.py` puis uvicorn `--reload` |
| `check_env.py` | refuse le démarrage si un e-mail pouvait partir réellement ou si l'émulateur manque |
| `seed/seed_emulator.py`, `seed/hp_names.py` | données fictives (Faker, graine fixe) |
| `../src/infrastructure/runtime_env.py` | source unique prod/dev côté serveur |
| `../web/shared/alj-firebase.js` | initialisation Firebase unique côté navigateur |
