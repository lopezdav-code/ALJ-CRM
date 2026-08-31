# 📍 Amicale Laïque de Jonage (ALJ) - Section Escalade
> **Pipeline de Gestion des Adhésions, Génération de Documents & Synchronisation Google Drive / HelloAsso**

Ce dépôt contient le code source du pipeline automatisé permettant d'importer, synchroniser, gérer et traiter les adhésions de la section escalade de l'Amicale Laïque de Jonage (ALJ) pour la saison active (par défaut 2026-2027). Il orchestre les flux de données entre **l'API HelloAsso**, **Google Drive** (via l'API Drive/Gmail) et des fichiers Excel/Word locaux pour automatiser les tâches administratives complexes (génération d'attestations, fiches de présence, listes d'urgence).

---

## 🏗️ Architecture et Rôle des Fichiers

Pour une propreté optimale, le projet sépare les fichiers de configuration, scripts de lancement, et le code source pur de l'application :

```
C:\Users\a138672\OneDrive - Worldline\Desktop\Import Export Script\code_source\
├── .env                                                         # Variables d'environnement et secrets d'API (HelloAsso, Google, SMTP)
├── install.bat                                                  # Script Batch d'installation (Venv, dépendances pip)
├── run_pipeline.bat                                             # Script Batch de lancement du pipeline principal (exécute src/create_excel.py)
├── requirements.txt                                             # Liste des dépendances Python requises
├── client_secret_*.json                                         # Fichier de secrets d'application Google Cloud pour OAuth2
├── GEMINI.md                                                    # Ce fichier de documentation et d'instructions
│
├── tests/                                                       # [DOSSIER TESTS] Regroupe toutes les suites de tests unitaires (unittest)
│   ├── test_attestation_generator.py                            # Tests pour la génération d'attestations
│   ├── test_fill_presence_cours.py                              # Tests pour la synchronisation du fichier de cours
│   └── test_presence_sheet_generator.py                         # Tests pour le générateur de fiches de présence
│
└── src/                                                         # [DOSSIER CODE PUR] Contient l'intégralité du code source Python de production
    ├── paths.py                                                 # [CHEMINS] Résolution dynamique et robuste des dossiers racines (CODE_ROOT et ROOT_DIR)
    ├── create_excel.py                                          # [MASTER COORDINATOR] Script central d'orchestration (UI console & Synchro)
    ├── helloasso_api.py                                         # Client API REST pour HelloAsso v5 (OAuth2, Pagination)
    ├── gmail_auth_helper.py                                     # Assistant OAuth2 Google pour autoriser Gmail/Drive (serveur local port 8080)
    ├── email_sender.py                                          # Envoi d'e-mails (via SMTP SSL/TLS classique ou API Gmail REST HTTPS port 443)
    ├── fill_presence_cours.py                                   # Remplissage automatique et audit du fichier Excel "Cours.xlsx"
    ├── presence_sheet_generator.py                              # Génération des fiches de présence d'un cours depuis un template et "planning.json"
    ├── urgency_contact_generator.py                             # Génération d'une fiche globale A4 des contacts d'urgence triée par nom
    ├── attestation_generator.py                                 # Génération d'attestations de paiement (génère .docx et exporte en .pdf via MS Word)
    └── server.py                                                # Serveur FastAPI pour exposer les données vers un tableau de bord (Port local)
```

### Description détaillée des Modules de `src/`

1. **`paths.py` (Résolution de chemins)**
   - Expose `CODE_ROOT` (pointe vers `code_source/` pour le `.env`, les secrets Google et les fichiers xlsx de cache) et `ROOT_DIR` (pointe vers `Import Export Script/` pour les templates et répertoires de sortie) de façon complètement dynamique. Cela garantit la compatibilité quel que soit le dossier d'exécution.

2. **`create_excel.py` (Coordonnateur Principal)**
   - Propose un menu interactif en ligne de commande pour lancer la synchronisation ou modifier les variables de configuration.
   - Télécharge l'Excel d'adhésion de référence depuis Google Drive, extrait les informations HelloAsso, synchronise les enregistrements et met à jour le fichier avant de le renvoyer sur le Drive.
   - Déclenche à la volée les générateurs d'attestations, de feuilles de présence et de listes de contacts d'urgence.

3. **`helloasso_api.py` (Client HelloAsso)**
   - Gère l'authentification OAuth2 (Client Credentials) avec HelloAsso.
   - Gère proprement la pagination de l'API REST en utilisant des jetons de continuation (`continuationToken`) pour extraire l'intégralité des campagnes, des paiements et des articles (`items`) vendus.

4. **`gmail_auth_helper.py` (Helper OAuth2 Google)**
   - Initialise un serveur HTTP local temporaire sur le port 8080.
   - Automatise l'obtention du `refresh_token` pour l'API Gmail/Drive à partir du fichier `client_secret_*.json` et l'enregistre de manière transparente dans le fichier `.env`.

5. **`email_sender.py` (Service d'Envoi de Mails)**
   - Conçoit les emails au format MIME multipart avec pièces jointes (.pdf ou .docx).
   - Offre deux modes d'envoi de secours :
     - **Mode Gmail API HTTPS (Port 443)** : Recommandé. Évite les blocages de ports SMTP (587/465) par les pare-feux restrictifs en communiquant directement en REST avec Google.
     - **Mode SMTP Classique** : Utilise SSL/TLS pour envoyer des messages via n'importe quel hébergeur mail traditionnel.

6. **`fill_presence_cours.py` (Synchronisation "Cours.xlsx")**
   - Rapproche et pré-remplit le fichier `Cours.xlsx` (qui gère 19 créneaux d'escalade) à partir de la base de données HelloAsso unifiée.
   - Incorpore une fonction d'audit exhaustive pour détecter les écarts de tarifs, les doublons, et les dossiers en attente.

7. **`presence_sheet_generator.py` (Fiches de Présence d'un cours)**
   - S'appuie sur `Template Export liste adhérents à imprimer.xlsx` et le planning structuré `planning.json` (situé dans le répertoire parent) pour générer des fiches de présence d'activité hebdomadaire dans le dossier `liste adhérent`.

8. **`urgency_contact_generator.py` (Fiches d'Urgence)**
   - Extrait les contacts de sécurité de l'intégralité des membres actifs inscrits.
   - Produit une feuille Excel unifiée, stylisée, et configurée pour une impression verticale A4 propre pour l'affichage en salle de sport ou le cahier d'urgence des encadrants.

9. **`attestation_generator.py` (Générateur d'Attestations de Paiement)**
   - Remplace les balises de fusion dans un modèle Word (`ATTESTATION DE PAIEMENT_adulte.docx` situé dans le dossier parent).
   - S'interface avec l'instance locale de Microsoft Word via COM (`win32com.client`) pour compiler le document Word (.docx) en fichier PDF (.pdf).

10. **`server.py` (API de Visualisation)**
    - API de backend web propulsée par FastAPI. Expose le endpoint `/api/dashboard` permettant de nourrir un tableau de bord graphique local pour la cartographie des adhérents (via `geopy`), le suivi des ventes et le dispatching des tarifs.

---

## ⚙️ Configuration du Projet (`.env`)

Toutes les configurations sont centralisées dans le fichier `.env`. En voici le schéma des variables attendues :

```env
# Authentification API HelloAsso v5
HELLOASSO_CLIENT_ID=votre_client_id_helloasso
HELLOASSO_CLIENT_SECRET=votre_client_secret_helloasso
HELLOASSO_ORG_SLUG=amicale-laique-de-jonage # Identifiant de l'association

# Spécification de la campagne de référence
CAMPAIGN_TYPE=Membership
CAMPAIGN_SLUG=adhesion-escalade-2026-2027-amicale-laique-escalade

# Synchronisation du tableur central Google Drive
GOOGLE_DRIVE_FILE_ID=identifiant_unique_du_fichier_excel_sur_drive

# Configuration d'authentification OAuth2 Google (Gmail API / Drive API)
GMAIL_CLIENT_ID=votre_client_id_google_cloud
GMAIL_CLIENT_SECRET=votre_client_secret_google_cloud
GMAIL_REFRESH_TOKEN=refresh_token_obtenu_via_auth_helper
GMAIL_USER_EMAIL=adresse_expediteur_gmail@gmail.com

# Configuration SMTP Classique (Fallback si OAuth2 Google non utilisé)
SMTP_HOST=smtp.votre_fournisseur.fr
SMTP_PORT=587
SMTP_USER=votre_username_smtp
SMTP_PASSWORD=votre_mot_de_passe_smtp
SMTP_FROM_EMAIL=adresse_expediteur_smtp@domain.com

# Contenu des e-mails d'envoi d'attestations
EMAIL_SUBJECT=Attestation de paiement escalade - Saison 2026-2027
EMAIL_BODY=Bonjour,\n\nVeuillez trouver ci-joint l’attestation de paiement relative à la licence d’escalade pour la saison 2026-2027...\n\nCordialement.
```

---

## 🚀 Installation & Utilisation

### 1. Installation de l'environnement

Pour initialiser l'environnement et installer l'ensemble des bibliothèques nécessaires, double-cliquez sur :
```bash
install.bat
```
*Ce script va créer un environnement virtuel Python (`venv`), mettre à jour `pip` et installer les paquets décrits dans `requirements.txt`.*

### 2. Autorisation Google Gmail & Drive

Avant de lancer le pipeline pour la première fois avec les services Google, vous devez autoriser l'accès en exécutant :
```bash
python src/gmail_auth_helper.py
```
1. Le script va détecter le fichier `client_secret_*.json` à la racine de `code_source/`.
2. Il va automatiquement ouvrir un onglet dans votre navigateur web par défaut.
3. Après validation et consentement, le serveur local récupère le `refresh_token` et met à jour automatiquement votre fichier `.env`.

### 3. Exécution du Pipeline Principal

Pour lancer la synchronisation complète et les générations automatiques, double-cliquez sur :
```bash
run_pipeline.bat
```
*Le script active l'environnement virtuel et exécute `src/create_excel.py` qui orchestre la récupération HelloAsso, la fusion des correctifs, la mise à jour Drive et les exports.*

### 4. Démarrage de l'API de Dashboard

Pour lancer l'API locale FastAPI sur le port 8000 :
```bash
python src/server.py
```
Vous pouvez ensuite y accéder à l'adresse `http://127.0.0.1:8000/docs` pour consulter la documentation interactive de l'API (Swagger).

---

## 🗄️ Base de Données — Schéma v2 (users / orders / purchases / purchase_options)

Depuis la version 2.0.0, la base `database.db` (racine du projet) est en **schéma v2 natif** :

- **`users`** : identité stable inter-saisons (clé unique : nom + prénom normalisés + date de naissance ISO).
- **`orders`** : commandes HelloAsso (clé naturelle `order_ref`) — payeur (`payer_*`), moyen de paiement, code promo.
- **`purchases`** : une ligne par inscription-saison (tarif, montant, statut original + normalisé).
- **`purchase_options`** : une ligne par assurance souscrite (fini les 12 colonnes `opt_*`).
- **`seasons`, `planning`, `geocache`, `email_templates`** : inchangés.

Règles de conception (respecter impérativement) :

1. **Source de vérité unique** : la couche `infrastructure/schema_v2.py` centralise DDL, normalisations
   (statuts, dates ISO, NULL legacy) et table de priorité des statuts. Ne jamais dupliquer ces tables.
2. **Vue de compatibilité** : `v_adherents_legacy` reproduit le format plat historique (colonnes `champ_*` /
   `opt_*`) pour les consommateurs existants. Elle est **recréée à chaque démarrage** depuis le code
   (`recreate_compat_view`) — toute modification passe par `COMPAT_VIEW_SQL` dans `schema_v2.py`.
3. **Lectures** : `SqliteRepository.load_direct_data()` (dicts legacy via la vue) ou
   `SqliteRepository.get_members()` (objets `Member` typés, API recommandée).
4. **Golden master** : `tests/test_ffme_golden_master.py` garantit un export CSV FFME **octet-pour-octet
   identique** à la référence (`tests/fixtures/import_ffme_reference.csv`, données locales non versionnée).
   La référence a été **renouvelée le 31/08/2026** après correction du bug `str(None)` historique
   (artefacts `'NO'` pays, `'none'`, `'NONE'` sur les valeurs NULL — 1 seule ligne affectée : HUE Magaly).
   Toute modification du générateur `generate_ffme_csv` doit laisser ce test vert, ou s'accompagner
   d'un renouvellement explicite de la référence validé par le club.
5. **Migration legacy** : le script `src/migrate_schema_v2.py` reste disponible (idempotent) pour les bases
   v1 héritées ; il est aussi déclenché automatiquement au démarrage si `PRAGMA user_version = 1`.
6. **Sauvegardes** : API backup SQLite (jamais de copie fichier brute avec WAL actif), rétention 10 jours
   dans `archive/db/`.

---

## 🧪 Tests Unitaires

Une couverture de tests unitaires est présente pour assurer le maintien de la stabilité de l'application.

### Commandes pour exécuter les tests :

Pour exécuter tous les tests unitaires du projet en une seule commande (en utilisant la venv) :
```bash
venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

Pour exécuter un fichier de test individuel :
```bash
venv\Scripts\python.exe -m unittest tests/test_presence_sheet_generator.py
venv\Scripts\python.exe -m unittest tests/test_attestation_generator.py
venv\Scripts\python.exe -m unittest tests/test_fill_presence_cours.py
```

---

## 📐 Conventions de Développement & Directives

Pour assurer la cohérence et la compatibilité du code lors d'interventions futures, respectez scrupuleusement les consignes suivantes :

### 1. Centralisation de la Résolution de Chemins
* **Utilisation de `src/paths.py`** : Ne recalculez JAMAIS manuellement `root_dir` ou `CODE_ROOT` via des chaînes d'appels à `os.path.dirname(os.path.abspath(__file__))`. Importez systématiquement `CODE_ROOT` et `ROOT_DIR` depuis `paths` pour garantir que tout fonctionne de façon transparente, que l'exécution se fasse de la racine ou de `src/`.

### 2. Normalisation administrative et sémantique
* **Normalisation des noms/prénoms** : Utilisez impérativement la fonction `normalize_string()` de `fill_presence_cours.py` pour éliminer les accents, espaces superflus et forcer le passage en minuscules pour tout rapprochement ou comparaison de chaînes (par exemple lors de l'audit de rapprochement).
* **Format des noms de fichiers** : Utilisez `clean_filename()` pour purger les caractères interdits dans les systèmes de fichiers Windows avant d'écrire des fichiers Excel ou PDF.

### 3. Gestion des Fichiers Excel et Word (Interfaçage Windows COM)
* **Microsoft Word & Excel COM (`win32com.client`)** :
  - **Important** : L'utilisation de `win32com.client` pour la conversion PDF requiert une installation locale de Microsoft Office sous Windows.
  - Veillez à toujours libérer les ressources en fermant les instances de fichiers ouvertes via COM en cas de plantage ou d'interruption (`excel_app.Quit()`, `word_app.Quit()`, ou fermeture des Workbooks), sans quoi des processus fantômes bloqueront les fichiers sur le système.
  - Utilisez `openpyxl` pour la création/modification directe et performante de tableurs sans nécessiter l'ouverture d'Excel en arrière-plan.

### 4. Traitement robuste des données HelloAsso
* Lors du traitement de champs de formulaires personnalisés (`customFields`), les réponses peuvent résider indifféremment dans l'attribut `answer` ou `value`. Recherchez systématiquement les deux attributs pour prévenir les valeurs manquantes.
* Ne modifiez pas l'identifiant des fichiers sur Google Drive lors de la mise à jour (upload). Utilisez l'API de mise à jour de contenu (`PATCH` avec `uploadType=media`) pour conserver l'ID de fichier originel et préserver l'intégrité des liens partagés de l'association.

### 5. Styles et Chartes graphiques (Feuilles de présence et Fiches d'urgence)
* Pour toute modification cosmétique de tableaux générés, respectez scrupuleusement la charte graphique établie :
  - Police : **Segoe UI** (taille 16 en gras pour les titres de créneaux, 9 standard pour les données d'adhérents).
  - Couleurs de marque : Bleu foncé (**#1E3A8A** / `1E3A8A`) pour les en-têtes et bordures de structure, Orange (**#EA580C** / `EA580C`) pour l'urgence.
  - Grille de lecture : Alternance zébrée grise/blanche pour améliorer la lisibilité à l'impression.
  - Lignes de quadrillage : Assurez-vous que le quadrillage d'impression est activé (`ws.views.sheetView[0].showGridLines = True`) pour une impression papier impeccable des cases de présence.

### 6. Versionnement et Incrémentation de l'application
* **Incrémentation de la Version** : Le numéro de version de l'application (défini par la variable globale `APP_VERSION` au sein du fichier `src/domain/constants.py`) doit impérativement être incrémenté (par exemple de `1.0.0` à `1.0.1` ou `1.0.2` selon la criticité des changements) à chaque modification de code source, correction de bug ou ajout de fonctionnalité métier. Cela garantit un suivi et une traçabilité rigoureuse des versions et des déploiements auprès du club.

### 7. Gestion des Fichiers et Scripts Temporaires (Propreté du dépôt)
* **Emplacement obligatoire (`scripts_temporaires/`)** : Afin de garder la racine du projet propre, tous les scripts ad-hoc (ex: scripts de diagnostic préfixés par `check_` ou `query_`), requêtes d'exploration ponctuelles sur la base de données SQLite ou prototypes jetables de code doivent impérativement être créés ou stockés dans le dossier `scripts_temporaires/` situé à la racine du projet. Aucun script temporaire ou fichier de débogage "one-shot" ne doit être commité ou laissé à la racine ou dans le dossier `code_source/src/`.
