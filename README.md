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
| `severus.snape@hogwarts.example` | coach |
| `argus.filch@hogwarts.example` | lecture seule |

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

## Déployer sur Cloud Run

Depuis `code_source/` (Google Cloud Shell ou poste avec le Google Cloud SDK) :

```bash
./deploy_cloud_run.sh                     # production : la nouvelle version reçoit 100 % du trafic
./deploy_cloud_run.sh --test              # version de test : 0 % du trafic, URL dédiée
./deploy_cloud_run.sh --rollback          # retour à la révision précédant celle en ligne
./deploy_cloud_run.sh --rollback <REV>    # retour à une révision précise
./deploy_cloud_run.sh --cleanup           # supprime l'URL de test (la révision est conservée)
```

Chaque déploiement crée une **révision** Cloud Run immuable ; le script affiche la révision en ligne,
demande confirmation, puis donne l'URL de l'application à la fin.

### Tester avant la mise en production

1. `./deploy_cloud_run.sh --test` : la révision est publiée sur une URL du type
   `https://test---alj-escalade-api-….run.app`, sans recevoir de trafic.
2. Vérifier sur cette URL : `/health`, connexion, pages modifiées.
3. Promouvoir sans reconstruire avec la commande `gcloud run services update-traffic … --to-tags test=100`
   affichée par le script (ou relancer un déploiement de production).
4. `./deploy_cloud_run.sh --cleanup` une fois les tests terminés : l'URL de test, branchée sur les
   données de production, cesse de répondre. Une révision sans trafic ne coûte rien (0 instance au
   repos) ; seules les images Docker s'accumulent dans Artifact Registry (`cloud-run-source-deploy`).

### Revenir en arrière

`./deploy_cloud_run.sh --rollback` bascule tout le trafic sur une ancienne révision, sans reconstruction,
en quelques secondes. Le script liste les dernières révisions : vérifier que la cible n'est pas une
version de test jamais promue. Après un déploiement en production, la commande de retour exacte est
affichée. Le prochain déploiement en production renvoie le trafic sur la nouvelle révision.

### À savoir

- La version de test utilise **les données Firestore et les secrets de production** : toute action
  (envoi d'e-mails, modification d'adhérents) y est réelle.
- Un rollback ne restaure que le code, jamais les données.
- Connexion sur l'URL de test (`Erreur 400 : redirect_uri_mismatch`) : la connexion Google passe par
  le client OAuth `796572126711-npcue84…` (voir `web/competitions.html`). Une seule fois, dans la console
  Google Cloud > API et services > Identifiants > ce client OAuth, ajouter :
  - **Origines JavaScript autorisées** : `https://test---alj-escalade-api-….run.app`
  - **URI de redirection autorisés** : `https://test---alj-escalade-api-….run.app/competitions`

  L'URL de test ne change pas d'un déploiement `--test` à l'autre. La prise en compte peut prendre
  quelques minutes.
- Les webhooks HelloAsso arrivent toujours sur l'URL principale, donc sur la révision de production.
- `firestore.rules` n'est **pas** déployé par ce script (`firebase deploy --only firestore:rules`) :
  les règles s'appliquent immédiatement à toute la production. Historique et retour arrière dans la
  console Firebase > Firestore > Rules.
- `deploy_cloud_run.bat` (Windows) ne fait qu'un déploiement en production, sans `--test` ni `--rollback`.
