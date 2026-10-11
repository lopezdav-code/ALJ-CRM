# ALJ-CRM — Architecture & onboarding

> Gestion des adhésions de la section Escalade de l'Amicale Laïque de Jonage (ALJ).
> Ce document décrit l'état réel du code (branche `feat/nux_setup`, version `2.5.8`) et la trajectoire
> **« tout migrer vers le web »**. Il a été rédigé par lecture du code et des docs existantes ; les points
> marqués **(à vérifier)** n'ont pas été confirmés en exécutant l'application.

---

## 1. En une minute

Le dépôt contient **une seule base de code Python** (`code_source/`) qui produit **deux applications** :

| | Client lourd (desktop) | Application web |
|---|---|---|
| Techno | PySide6 (Qt) + serveur FastAPI embarqué | HTML/JS statique (sans build) servi par FastAPI |
| Où ça tourne | Poste Windows du bureau (portable zip + auto-update GitHub) | Google Cloud Run (`europe-west1`, 0→2 instances) |
| Point d'entrée | `src/app.py` | `src/server.py` (`uvicorn server:app`) |
| Données | Cache SQLite local (`data/database.db`) synchronisé avec Firestore | Firestore directement (navigateur) + cache SQLite éphémère côté serveur |
| Utilisateurs | Administrateurs/bureau | Coachs et admins (PWA smartphone + portail bureau) |

Le lien entre les deux : **Firestore** (projet GCP `smart-amplifier-510811-n6`) est la source de vérité.
Le backend `server.py` est *le même fichier* des deux côtés : le desktop le lance en thread sur
`127.0.0.1:8000-8099` (auth désactivée), Cloud Run le lance dans Docker (auth Firebase obligatoire).

```
                  HelloAsso ──webhook──┐
                  HelloAsso ◄──API v5──┤
                                       ▼
┌──────────────────────┐     ┌───────────────────────────┐     ┌──────────────────────────┐
│ DESKTOP (Windows)    │     │ CLOUD RUN — server.py     │     │ NAVIGATEUR               │
│ PySide6 presentation │     │ FastAPI + API + HTML      │     │ web/ (PWA + portail      │
│ + server.py en thread│     │ WeasyPrint (PDF)          │◄────┤ bureau), Firebase Auth   │
│ + cache SQLite       │     │ cache SQLite éphémère     │ API │ lit Firestore en direct  │
└─────────┬────────────┘     └─────────────┬─────────────┘     └────────────┬─────────────┘
          │ REST v1 (OAuth club)           │ REST v1 (metadata server)      │ SDK Firebase
          ▼                                ▼                                ▼
                         ┌─────────────────────────────────────┐
                         │ FIRESTORE  crm_* / competitions /   │
                         │ coaches / adherents / planning …    │
                         └─────────────────────────────────────┘
          Gmail API (OAuth2 club)  ·  Google Drive (copie de sauvegarde)  ·  Nominatim (géocodage)
```

---

## 2. Arborescence

```
ALJ-CRM/                         ← racine du dépôt
├── code_source/                 ← TOUT le code (la racine ne contient que des doublons/raccourcis, voir §9)
│   ├── src/
│   │   ├── app.py               ← entrée DESKTOP (QApplication + thread uvicorn)
│   │   ├── server.py            ← entrée WEB/API (FastAPI, ~1400 lignes)
│   │   ├── paths.py             ← CODE_ROOT / ROOT_DIR / DATA_ROOT (à utiliser, ne jamais recalculer)
│   │   ├── domain/              ← Python pur : modèles, règles d'âge, attestation (HTML), rapprochement compétitions…
│   │   ├── infrastructure/      ← accès externes : SQLite, Firestore, HelloAsso, Gmail, Drive, auth API…
│   │   ├── presentation/        ← UI Qt UNIQUEMENT (pages/, components/, workers.py, main_window.py)
│   │   └── *.py (racine src/)   ← générateurs/legacy : create_excel, attestation_generator (Word COM),
│   │                              presence_sheet_generator, urgency_contact_generator, fill_presence_cours,
│   │                              mycompet_scraper, helloasso_api, email_sender, migrate_*…
│   ├── web/
│   │   ├── index.html           ← PWA « annuaire » (smartphone)
│   │   ├── competitions.html    ← PWA « compétitions » (smartphone, 2700 lignes)
│   │   ├── sw.js, manifest.webmanifest
│   │   ├── bureau/              ← portail ordinateur : index, adherents, communications, competitions, outils
│   │   └── shared/              ← alj-firebase.js (init Firebase unique + émulateur dev), alj-core.js (login/apiFetch), alj-shell.js (menu), alj-members.js,
│   │                              alj-filters.js, alj-vue.js (redirection bureau/mobile), alj.css
│   ├── tests/                   ← 37 fichiers pytest/unittest (Qt + API + domaine)
│   ├── dev/                     ← mode dev local : émulateur Firebase (Docker), dev.env, run_server.sh, seed/ (données fictives)
│   ├── docs/                    ← docs d'architecture/plan (partiellement obsolètes, voir §8)
│   ├── doc/template/            ← modèles Word/Excel (non versionné en partie)
│   ├── launcher/ installer/     ← auto-update + installateur du mode portable Windows
│   ├── Dockerfile, requirements-docker.txt, deploy_cloud_run.{sh,bat}, firestore.rules, firebase.json
│   ├── requirements.txt         ← deps DESKTOP (PySide6, pywin32, python-docx, keyring…)
│   ├── VERSION                  ← 2.5.8 (source de vérité, doit == APP_VERSION dans domain/constants.py)
│   └── GEMINI.md                ← doc historique la plus détaillée (voir §8 pour ses limites)
├── .github/workflows/           ← release Windows (tag v*) : ruff, mypy, pytest, zip portable
└── GEMINI.md, *.bat, *.vbs…     ← doublons/raccourcis de la racine
```

### Couches (code_source/src)

- **`domain/`** — pur Python, sans I/O ni Qt. C'est la partie **directement réutilisable** par le web.
  Ex. : `attestation.build_attestation()` (HTML → PDF WeasyPrint), `age_rules`, `competition_matching`,
  `planning_groups`, `validators`, `utils.apply_template_variables`.
- **`infrastructure/`** — adaptateurs. Les plus structurants :
  - `schema_v2.py` : DDL SQLite, normalisations, vue de compatibilité `v_adherents_legacy` (**source unique**, recréée à chaque démarrage).
  - `sqlite_repository.py` : lecture/écriture (`get_members()` typé recommandé, `load_direct_data()` legacy).
  - `cloud_database.py` : réplication SQLite ⇄ Firestore (collections `crm_<table>`, triggers `_fs_*`, flush toutes les 15 s, pull toutes les 2 min, merge champ par champ).
  - `firestore_client.py` : client REST Firestore (sans gRPC) ; `competition_firestore_repository.py` : compétitions.
  - `api_auth.py` : middleware Firebase (rôles `readonly < coach < admin`, miroir de `firestore.rules`).
  - `email_dispatch_service.py`, `email_repository.py`, `helloasso_webhook_service.py`, `secret_store.py`, `google_*_client.py`.
- **`presentation/`** — Qt uniquement. Pages : Adhérents, Attestations, Communications, Exports, Import Data, Créneaux, Compétitions, Outils, Paramètres, Aide, Logs. Les opérations longues passent par `workers.py` (QThread).

---

## 3. Modèle de données

Schéma v2 (SQLite, répliqué en Firestore sous `crm_<table>`) :

`users` (identité stable inter-saisons) → `orders` (commande HelloAsso) → `purchases` (une inscription par saison)
→ `purchase_options` (assurances) ; + `seasons`, `planning` (créneaux/groupes avec bornes de naissance),
`geocache`, `email_templates`, `app_settings`.

Autres collections Firestore : `competitions/{id}` (participants **embarqués**), `coaches`, `adherents` et
`planning` (projections pour PWA/webhook, recalculées après modification), `app_settings`, `helloasso_items`.

Particularités à connaître :
- Chaque document `crm_*` porte `_modified_at`, `_modified_by`, `_deleted` (tombstone).
- Les IDs de compétitions sont `str(Date.now())` ; les anciens IDs aléatoires sont normalisés à la lecture.
- Le web reconstruit `v_adherents_legacy` **en JavaScript** (`web/shared/alj-members.js`) à partir de `crm_*` : toute évolution du schéma/vue SQL doit être répercutée des deux côtés.
- Détails : `code_source/docs/base_firestore.md`.

---

## 4. Backend `server.py` — routes

| Catégorie | Routes |
|---|---|
| Pages | `/`, `/index`, `/competitions`, `/bureau`, `/bureau/{page}` (liste blanche), `/sw.js`, `/manifest.webmanifest`, `/static-web/*`, `/annuaire` |
| Santé/version | `/health`, `/api/web-version` |
| Données | `/api/dashboard`, `/api/planning` (GET/POST), `/api/season-tarifs`, `/api/members/update` |
| Outils | `/map`, `/pivot` (pages HTML générées côté serveur, chargées en `iframe srcdoc`) |
| E-mail | `/api/email-templates` (GET/POST/DELETE), `/api/whatsapp-template`, `/api/preview-email`, `/api/send-email`, `/api/email-status` |
| Attestations | `/api/attestations/preview`, `/api/attestations/send` (PDF en mémoire, admin) |
| HelloAsso | `/webhooks/helloasso` (GET/POST), `/api/helloasso/sync` |

**Auth** : `ALJ_API_AUTH=required` (Docker) ou présence de `K_SERVICE` (Cloud Run) → jeton Firebase obligatoire, fail-closed.
Pages statiques publiques (`PUBLIC_PATHS` / `PUBLIC_PREFIXES`), données protégées. Les listes d'e-mails admin/coach sont **codées en dur** dans `api_auth.py` *et* `firestore.rules` (un test vérifie la cohérence — modifier les deux).

---

## 5. Front web

- **Aucun framework ni build** : HTML + JS ES modules + CSS, Firebase SDK, `fetch` via `apiFetch` (`alj-core.js`, ajoute le jeton Bearer).
- **Deux « vues »** : PWA smartphone (`/competitions`, `/index`) et portail bureau (`/bureau/*`). `alj-vue.js` redirige automatiquement les écrans ≥ 1024 px vers `/bureau/` (`?vue=mobile` pour forcer la PWA).
- **Un seul numéro de version web** à garder synchronisé : `<meta alj-web-version>`, `<title>`, badge, et `CACHE_NAME` de `sw.js` (le test `test_mobile_pwa` le vérifie). Chaque déploiement visible = version web +1 (actuellement v19).
- Rôles : coach/readonly = lecture ; admin = envoi e-mail/attestation, écritures.
- Plan et décisions du portail : `code_source/docs/plan_pages_web_bureau.md`.

---

## 6. Où en est la migration vers le web

Correspondance entre les pages du client lourd et ce qui existe déjà sur le web (**estimation d'après le code, à valider fonctionnellement**) :

| Page desktop | Équivalent web | État | Reste à faire / remarques |
|---|---|---|---|
| 👥 Adhérents | `bureau/adherents.html` | Partiel | Liste, filtre sous-catégories, détail, e-mail, attestation, mise à jour via `/api/members/update`. Pas d'ajout d'adhérent ni d'édition de tarif **(à vérifier)** ; plan initial : « lecture seule ». |
| 📄 Attestations | bouton par adhérent | Partiel | Unitaire seulement (WeasyPrint). Pas de génération en lot / ZIP. Word/COM n'existe pas côté web. |
| ✉️ Communications | `bureau/communications.html` | Partiel/Avancé | CRUD des modèles + envoi unitaire. Envoi groupé, historique d'envoi, quotas Gmail : à construire. |
| 📦 Exports | — | **Absent** | Export CSV FFME (`create_excel.generate_ffme_csv`, golden master), fiches de présence (Excel/openpyxl), cahier d'urgence A4, anciens adhérents, MyCompet. |
| 📥 Import Data | — | **Absent** | Imports FFME / autonomes / saison + rapprochement manuel (`ManualMatchDialog`). Nécessite upload de fichiers. |
| 🧗 Créneaux (groupes) | — (`/api/planning` seulement) | **Absent** (UI) | Édition groupes/créneaux, vue semaine, export planning Excel, QR codes. |
| 🏆 Compétitions | `bureau/competitions.html` + PWA | Avancé | Participants, e-mails, HelloAsso. Le rapprochement manuel et le bilan de saison étaient « bureau only » dans la doc **(à vérifier)**. |
| 🔧 Outils | `bureau/outils.html` | Fait (iframes) | Carte + tableau croisé. Géocodage en lot et sync HelloAsso : `/api/helloasso/sync` existe. |
| ⚙️ Paramètres | — | **Absent** | Secrets (HelloAsso, Google OAuth, SMTP) via `SecretStore` (keyring) sur desktop, variables d'env./Secret Manager sur Cloud Run. |
| Gmail Contacts | — | **Absent** | `gmail_contact.py` + `google_contacts_client.py`. |
| ❓ Aide / 📋 Logs | — | Absent | Logs : Cloud Logging côté Cloud Run. |

### Obstacles techniques récurrents

1. **Dépendances Windows/desktop** hors `presentation/` : `attestation_generator.py` (Word COM, `pywin32`), `secret_store.py` et `google_drive_client.py` (`keyring`), `app.py`. Le Docker les exclut volontairement (`requirements-docker.txt`).
2. **Logique métier coincée dans des fichiers legacy ou des workers Qt** : `create_excel.py` (exports FFME, ~590 lignes restantes), `presentation/workers.py` (1234 lignes), générateurs Excel de `src/`. À extraire vers `domain/` + `infrastructure/` puis exposer en routes FastAPI avant de construire l'écran web.
3. **Système de fichiers** : le desktop lit/écrit dans `data/`, `exports/`, `archive/`. Cloud Run est éphémère → génération **en mémoire** puis téléchargement (comme les attestations), jamais de persistance locale.
4. **Cache SQLite côté serveur** : reconstruit depuis Firestore au premier appel de données (`CloudDatabase.ensure_fresh`, 30 s) et flush après chaque écriture. Une route d'écriture doit passer par `SqliteRepository` pour être répliquée.
5. **Durée des requêtes** : timeout Cloud Run 300 s, mémoire 1 GiB (Pandas/WeasyPrint) ; les traitements lourds (géocodage Nominatim à 1,5 s/adresse) doivent rester en tâche de fond.
6. **Données personnelles/RGPD** (santé, urgences, mineurs) : ne jamais committer de BDD/exports ; golden master FFME non versionné (`tests/fixtures/`).

### Démarche recommandée pour chaque page à migrer

1. Sortir la logique de la page Qt / du worker vers `domain/` (pur) ou `infrastructure/`.
2. Exposer une route FastAPI (rôle explicite : `admin` pour toute écriture/envoi).
3. Écrire le test (pytest sur la route, ou test de fonction pure).
4. Ajouter l'écran dans `web/bureau/` en réutilisant `alj-core.js`, `alj-shell.js`, `alj.css`.
5. Incrémenter la version web (meta/title/badge/`sw.js`) et déployer.
6. Une fois la parité atteinte, retirer la page Qt correspondante.

Fin de parcours : supprimer `presentation/`, `app.py`, `launcher/`, `installer/`, `make_portable.py`, la CI de release Windows, `PySide6`/`pywin32`/`python-docx`/`keyring` de `requirements.txt`, puis convertir `server.py` en simple backend (aujourd'hui il charge `SqliteRepository`, `helloasso_api`, etc. — acceptable).

---

## 7. Démarrer en local

> Environnement cible historique : Windows. Vous êtes sous WSL/Linux : le **backend + le web** tournent bien sous Linux (c'est l'image Docker) ; le **desktop Qt** et `pywin32` non (ou difficilement).

### 7.1 Installation (une fois)

```bash
# Debian/Ubuntu : module venv + libs Pango pour WeasyPrint (cf. Dockerfile) ; Docker pour l'émulateur
sudo apt install python3-venv libpango-1.0-0 libpangoft2-1.0-0

cd code_source
python3 -m venv venv && source venv/bin/activate                   # venv/ est ignoré par git
pip install -r requirements-docker.txt -r requirements-dev.txt     # profil « web » (sans Qt/pywin32) + Faker
```

L'image Docker utilise Python **3.11** ; une version plus récente fonctionne, mais en cas d'échec d'installation
d'une roue (pandas, lxml…), revenir à 3.11.

### 7.2 Mode dev sur l'émulateur Firebase (recommandé)

Front + API + Firestore entièrement locaux, sur le projet fictif **`demo-alj`** de l'émulateur Firebase
(Auth + Firestore), avec des **données fictives** (univers Harry Potter). Mode d'emploi : `code_source/dev/README.md`.

```bash
cd code_source
docker compose -f dev/docker-compose.yml up -d     # émulateur Firebase (UI :4000) + Mailpit (UI :8025)
set -a && source dev/dev.env && set +a
python dev/seed/seed_emulator.py                    # réinitialise + données fictives + comptes de connexion
dev/run_server.sh                                   # http://localhost:8080/bureau/
```

Connexion par le sélecteur de comptes de l'émulateur : `albus.dumbledore@alj-escalade.fr` (admin),
`severus.snape@poudlard.example` (coach), `argus.filch@poudlard.example` (lecture seule).

Fonctionnement :

- **Source unique côté serveur** : `src/infrastructure/runtime_env.py`. `ALJ_ENV=dev` redirige l'URL Firestore, le jeton
  (`owner`, admin de l'émulateur) et le projet (`demo-alj`) de `cloud_database.RestStore` et `FirestoreClient` ;
  active le rafraîchissement du cache comme sur Cloud Run. Sans `ALJ_ENV`, rien ne change (production, client lourd).
- **E-mails** : aucun code spécifique. `dev.env` dirige le SMTP de l'application (`SMTP_HOST=localhost`,
  `SMTP_PORT=1025`, variables `GMAIL_*` vides) vers **Mailpit** (conteneur de `dev/docker-compose.yml`), qui capture
  tout sans relayer : http://localhost:8025. `dev/check_env.py` (lancé par `run_server.sh`) vérifie la configuration
  effective, `.env` du dépôt compris (le `.env` racine est chargé en `override=True`), et refuse de démarrer si
  l'API Gmail est active ou si le SMTP n'est pas local.
- **Navigateur** : `GET /runtime-config.js` (jamais mis en cache par `sw.js`) définit `window.ALJ_RUNTIME` ;
  `web/shared/alj-firebase.js` est la **seule** initialisation Firebase de toutes les pages (configuration du projet
  comprise) et branche l'émulateur en dev, avec un bandeau « DEV ». La détection ne repose pas sur `localhost` :
  le serveur embarqué du desktop sert aussi ces pages en local et doit rester en production.
- **Garde-fous** : un projet `demo-*` n'existe pas chez Google (aucun accès réel possible, même mal configuré) ;
  `runtime_env.validate()` refuse le mode dev sur Cloud Run (`K_SERVICE`) ou sans variables d'émulateur ;
  le seed refuse de s'exécuter hors émulateur ; les tests retirent les variables dev (`tests/conftest.py`).
- L'émulateur applique le vrai `firestore.rules` et conserve ses données dans `dev/.emulator-data/` (ignoré par git).
- Limites : `/api/dashboard` et la synchro HelloAsso interrogent l'API HelloAsso réelle (lecture) ; sans identifiants,
  ces écrans sont en erreur. Les attestations Word/COM restent propres au desktop.

### 7.3 Serveur seul, sans émulateur

Pour un simple contrôle de l'API (aucune page connectée utilisable : la connexion Google réelle refuse `localhost`) :

```bash
ALJ_API_AUTH=off MEMBER_BACKEND=drive ALJ_DATA_DIR=./data-dev \
  uvicorn server:app --app-dir src --host 127.0.0.1 --port 8080 --reload
# Docker (identique à la prod) :
docker build -t alj . && docker run -p 8080:8080 -e ALJ_API_AUTH=off -e MEMBER_BACKEND=drive alj
```

- `ALJ_API_AUTH=off` : désactive le contrôle du jeton Firebase côté API (mode du serveur embarqué du desktop).
- `ALJ_DATA_DIR` : dossier du cache SQLite `database.db` (défaut : `<racine du dépôt>/data`), créé vide au premier accès.
- `MEMBER_BACKEND` : `firestore` par défaut. **Hors mode dev**, `firestore` pousse les écritures du serveur local vers le
  **Firestore de production** (`CloudDatabase.after_write`) ; `drive` = SQLite local seul.
- ⚠️ Hors mode dev, les pages web lisent et écrivent **le Firestore de production** directement depuis le navigateur
  (compétitions, coachs, éléments HelloAsso…), quel que soit `MEMBER_BACKEND`.

Desktop (Windows) : `install.bat` puis `run_pipeline.bat` / `Lancer_ALJ.vbs` (→ `src/app.py`).

**Configuration / secrets** : `code_source/.env` (non versionné) ou `SecretStore` (keyring) ; sur Cloud Run, variables d'environnement / Secret Manager.
Clés principales : `HELLOASSO_CLIENT_ID/SECRET/ORG_SLUG`, `CAMPAIGN_SLUG`, `GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN/USER_EMAIL`, `SMTP_*`, `GOOGLE_DRIVE_*`, `MEMBER_BACKEND` (`firestore`|`drive`), `ALJ_DATA_DIR`, `ALJ_API_AUTH`. Ne jamais afficher ni committer ces valeurs.

**Tests** (depuis `code_source/`) :

```bash
python -m pytest tests --ignore=tests/test_app_smoke.py ...   # voir .github/workflows pour la liste complète
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_presentation_lot4.py
```
La CI lance les tests Qt **en processus séparés** (crashs natifs sinon) ; `ruff check src` et `mypy` (limité à `schema_v2.py` et `constants.py`) sont bloquants. Les tests de la couche web/API (`test_bureau_web`, `test_mobile_pwa`, `test_api_security`, `test_cloud_run_lot4`, `test_helloasso_webhook`) ne nécessitent pas Qt — ce sont les plus utiles pour la migration. `test_ffme_golden_master` nécessite un fichier de référence local non versionné.

**Déploiement web** : `code_source/deploy_cloud_run.sh` (ou `.bat`) → `gcloud run deploy alj-escalade-api --source . --memory 1Gi --min-instances 0 --max-instances 2 --timeout 300 --allow-unauthenticated` (l'auth est applicative). Règles Firestore : `firebase deploy --only firestore:rules` (`firebase.json`). Guide : `docs/guide_deploiement_cloud_run_helloasso.md`.

**Release desktop** : tag `vX.Y.Z` → GitHub Actions (Windows) → zip portable + `SHA256SUMS`. Le tag, `VERSION` et `APP_VERSION` doivent être identiques (`build_release_assets.py --check-tag`).

---

## 8. Pièges & dette connue

- **Documentation partiellement périmée** : `GEMINI.md` (racine et `code_source/`) décrit encore Tkinter, un fonctionnement 100 % Windows/Excel/Drive et des chemins de l'ancien poste. `docs/architecture_actuelle.md` et `docs/plan_migration.md` datent de la migration Tkinter→PySide6. `plan_architecture_cloud_mobile.md` annonce `APP_VERSION 2.3.0`, `512Mi`. `pyproject.toml` dit `2.0.5`. **Faire confiance au code et à `VERSION`, puis `base_firestore.md` et `plan_pages_web_bureau.md` (les plus récents).**
- `GEMINI.md` impose une convention utile : scripts de diagnostic jetables dans `scripts_temporaires/` (ignoré par git), jamais à la racine.
- **Duplication du front** : `competitions.html` (2700 lignes) et `index.html` dupliquent historiquement auth/style ; le portail `bureau/` utilise `shared/`. Ne pas dupliquer davantage.
- **Admins codés en dur** (`api_auth.py` + `firestore.rules`) : à terme, passer par une collection de rôles.
- **Qt/GC** : conserver des références Python sur les `QGraphicsTextItem` (`_text_items`) dans `PlanningWeekView`.
- **Word COM** : toujours `Quit()` dans un `finally` (uniquement tant que le desktop existe).
- **Exports FFME** : CSV strict (`;`, dates `jj/mm/aaaa`) ; le golden master doit rester vert ou être renouvelé avec accord du club.
- **Sauvegardes** : API backup SQLite (jamais de copie brute avec WAL), PITR Firestore 7 j, export quotidien 14 j, retour arrière via `MEMBER_BACKEND=drive`.
- **État git au moment de la rédaction** : `.gitignore` et `code_source/requirements.txt` modifiés (non committés), `.claude/` non suivi.
- Le dépôt contient aussi `.agents/`, `.idea/`, `.jolli/` (outillage local).

---

## 9. Pour commencer concrètement

1. Lire dans l'ordre : ce fichier → `code_source/docs/base_firestore.md` → `code_source/docs/plan_pages_web_bureau.md` → `src/server.py` → `web/shared/alj-core.js` → `web/bureau/adherents.html` (page de référence).
2. Lancer le serveur en local et ouvrir `/bureau/` (§7) ; lancer les tests web/API.
3. Choisir une page « Absent » du tableau §6 — le meilleur premier candidat est **Exports** (FFME CSV + fiches de présence) : forte valeur, logique isolée, golden master déjà en place pour sécuriser le refactor.
4. Décider des questions ouvertes avec le club : envoi groupé (quotas Gmail, anti-doublon), droit d'écriture sur le web, hébergement des secrets (Secret Manager), sort de `database.db` Drive (retour arrière).
