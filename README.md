# ALJ-CRM

Gestion des adhésions de la section Escalade de l'Amicale Laïque de Jonage : client lourd Windows (PySide6)
et application web (FastAPI + PWA) sur Google Cloud Run, données dans Firestore.
Architecture détaillée : [ARCHITECTURE.md](ARCHITECTURE.md).

## Lancer l'application en mode dev local

Tout tourne sur la machine : émulateur Firebase (projet fictif `demo-alj`), données fictives,
e-mails capturés par Mailpit. **Aucun accès aux données ni aux services de production.**

### Prérequis (une fois)

```bash
sudo apt install python3-venv libpango-1.0-0 libpangoft2-1.0-0   # + Docker
cd code_source
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-docker.txt -r requirements-dev.txt
```

### Démarrage

```bash
cd code_source
docker compose -f dev/docker-compose.yml up -d    # émulateur Firebase + Mailpit
source venv/bin/activate
set -a && source dev/dev.env && set +a
python dev/seed/seed_emulator.py                   # (ré)initialise les données fictives
dev/run_server.sh                                  # serveur FastAPI avec rechargement auto
```

Arrêt : `Ctrl+C` pour le serveur, `docker compose -f dev/docker-compose.yml down` pour les conteneurs
(les données de l'émulateur sont conservées dans `dev/.emulator-data/`).

### URL utiles

| URL | Contenu |
|---|---|
| http://localhost:8080/bureau/ | Portail bureau (ordinateur) |
| http://localhost:8080/competitions?vue=pwa | PWA compétitions (smartphone) |
| http://localhost:8080/index?vue=pwa | PWA annuaire (smartphone) |
| http://localhost:8080/health | État du serveur |
| http://localhost:8080/docs | Documentation de l'API (Swagger) |
| http://localhost:4000 | Interface de l'émulateur Firebase (Firestore, Auth) |
| http://localhost:8025 | Mailpit : e-mails envoyés par l'application |

### Comptes de connexion

« Se connecter » ouvre le sélecteur de comptes de l'émulateur :

| Compte | Rôle |
|---|---|
| `albus.dumbledore@alj-escalade.fr` | admin |
| `severus.snape@poudlard.example` | coach |
| `argus.filch@poudlard.example` | lecture seule |

### À savoir

- Un bandeau orange « DEV » en bas de page confirme le branchement sur l'émulateur.
- `dev/run_server.sh` refuse de démarrer si un `.env` du dépôt réactive Gmail ou un SMTP externe.
- HelloAsso (`/api/dashboard`, synchro) appelle l'API réelle : en erreur sans identifiants.
- Plus de détails : [code_source/dev/README.md](code_source/dev/README.md).

## Tests

```bash
cd code_source && source venv/bin/activate
python -m pytest tests --ignore=tests/test_app_smoke.py   # voir .github/workflows pour la liste de la CI
ruff check src
```
