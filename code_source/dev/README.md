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
- **HelloAsso** : `/api/dashboard` et la synchro HelloAsso appellent toujours l'API HelloAsso
  réelle (lecture) si des identifiants sont configurés ; sans eux, ces écrans sont en erreur.
- **Service worker** : en cas de page figée après un changement, « Mettre à jour » sur le badge
  de version ou désenregistrer le SW (DevTools → Application).

## Tests e2e (Playwright)

Tests navigateur de bout en bout dans `code_source/e2e/`, sur cette même pile (émulateur + Mailpit).
Ils sont lancés par la CI (job `e2e` de `.github/workflows/tests.yml`, Ubuntu) à chaque PR et push sur `main`.

```bash
cd code_source
docker compose -f dev/docker-compose.yml up -d
pip install -r requirements-docker.txt -r requirements-e2e.txt
python -m playwright install --with-deps chromium    # WSL/Linux : bibliothèques système (sudo)
python -m pytest -c e2e/pytest.ini e2e -m smoke      # rapide ; sans -m : toute la suite
```

- ⚠️ **La suite réinitialise les données de l'émulateur** (elle relance le seed). Le serveur de test tourne
  sur le port `8090` (`E2E_PORT`), avec son propre cache SQLite temporaire : `run_server.sh` (8080) peut rester lancé.
- Connexion sans passer par le sélecteur de comptes : `login_as(page, "admin" | "coach" | "readonly")`
  (`e2e/helpers/auth.py`). E-mails : fixture `mailpit` (`e2e/helpers/mailpit.py`).
- Déboguer : `--headed --slowmo 300`, ou `--tracing retain-on-failure` puis
  `python -m playwright show-trace e2e-results/<test>/trace.zip`. Journaux du serveur et du seed :
  `test-results/server.log` (`e2e-results/` avec `--output e2e-results`, comme la CI).
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
