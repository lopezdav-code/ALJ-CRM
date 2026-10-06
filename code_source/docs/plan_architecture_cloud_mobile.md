# 📱 Plan d'Architecture Cloud & Mobile — ALJ Escalade
> **Alternative à Google AppSheet : Google Cloud Firestore + Cloud Run + PWA Mobile Coachs**
> **Statut global :** Lots 1, 2, 3 et 4 terminés (236 tests unitaires validés) — Architecture Cloud & Mobile 100% opérationnelle.

Ce document consigne la feuille de route architecturale pour doter l'Amicale Laïque de Jonage (Section Escalade) d'une application mobile tout-en-un pour les entraîneurs et gestionnaires, tout en restant à un **coût d'exploitation nul (0 € / mois)**.

---

## 1. Tableau de Bord d'Avancement des Lots

| Lot | Intitulé | Statut | Fichiers Clés & Livrables |
|---|---|:---:|---|
| **Lot 1** | **Micro-service Backend (Webhooks & Emails)** | ✅ **Terminé** | `src/infrastructure/helloasso_webhook_service.py`<br>`src/infrastructure/email_dispatch_service.py`<br>`src/server.py` (`/webhooks/helloasso`, `/api/send-email`, `/api/preview-email`)<br>`tests/test_helloasso_webhook.py`, `tests/test_email_dispatch_service.py` |
| **Lot 2** | **Modélisation Firestore & Passerelle Desktop** | ✅ **Terminé** | `firestore.rules` (Règles Admin / Coach)<br>`src/infrastructure/firestore_sync.py` (Push/Pull REST v1)<br>`src/server.py` (`/api/firestore/push`, `/api/firestore/pull/{id}`)<br>`tests/test_firestore_sync.py` |
| **Lot 3** | **Application Web Mobile PWA (Design Existant)** | ✅ **Terminé** | `web/competitions.html` (Modale d'envoi d'e-mails, balises dynamiques, appels 1-clic `tel:`)<br>`web/manifest.webmanifest` & `web/sw.js` (PWA installable sur smartphone, cache hors-ligne)<br>`web/logo.png`<br>`tests/test_mobile_pwa.py` |
| **Lot 4** | **Déploiement Cloud Run & Recette en Production** | ✅ **Terminé** | `Dockerfile` Cloud Run multi-plateforme Linux<br>`requirements-docker.txt` (dépendances backend épurées)<br>`.dockerignore` (sécurisation des secrets & BDD locales)<br>`deploy_cloud_run.bat` & `deploy_cloud_run.sh`<br>`docs/guide_deploiement_cloud_run_helloasso.md`<br>`tests/test_cloud_run_lot4.py` (routes `/health`, `/`, `GET /webhooks/helloasso`) |

---

## 2. Architecture Globale Déployée

```
                        ┌──────────────────────────────────────────────┐
                        │              HELLOASSO (Serveurs)            │
                        └──────────────────────┬───────────────────────┘
                                               │ Webhook HTTP POST (Paiements)
                                               ▼
┌───────────────────────┐            ┌─────────────────────────────────────────┐
│ Application Mobile    │            │     MICRO-SERVICE GOOGLE CLOUD          │
│ PWA des Coachs        │            │     (Cloud Run en Python / FastAPI)     │
│                       │            ├─────────────────────────────────────────┤
│ • Voir les épreuves   │◄───────────┤ • /webhooks/helloasso                   │
│ • Pointer compétiteurs│ (Temps     │ • /api/send-email (Gmail API)           │
│ • Envoyer les emails  │  réel)     │ • /api/email-templates & /preview-email│
│ • Appels d'urgence    │            │ • /api/firestore/push & pull            │
└──────────┬────────────┘            └────────────────────┬────────────────────┘
           │                                              │
           │ Écritures / Sélections                       │ Écritures paiements
           ▼                                              ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        GOOGLE CLOUD FIRESTORE                                │
│       (Base de données temps réel partagée + support hors-ligne natif)       │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │ Synchronisation (bidirectionnelle)
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                  APPLICATION DESKTOP BUREAU (ALJ CRM)                        │
│            • Génération attestations PDF Word • Export Intranet FFME         │
│            • Pilotage administratif lourd • Sauvegardes SQLite               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Détail des Réalisations (Lots 1, 2, 3)

### A. Webhooks HelloAsso & Envoi d'E-mails Sécurisé (Lot 1)
- **Point d'entrée :** `POST /webhooks/helloasso`
  - Reçoit les payloads HelloAsso (`Payment`, `Order`, articles bruts).
  - Réconcilie l'épreuve et l'adhérent via `domain.competition_matching`.
  - Passe instantanément le statut du compétiteur à `Payé` et consigne la commande.
- **Points d'entrée Emails :**
  - `GET /api/email-templates` : liste les modèles du club.
  - `POST /api/preview-email` : prévisualisation avec substitution dynamique des balises (`{first_name}`, `{name_competition}`, `{montant_competition}`, `{no_competition}`, `{date_competition}`).
  - `POST /api/send-email` : expédie via l'API Gmail du club (OAuth2) avec signature HTML stylisée.

### B. Modélisation Firestore & Synchronisation (Lot 2)
- **Fichier de règles de sécurité :** `code_source/firestore.rules` (accès sécurisé par rôle Coach / Admin).
- **Service Python NoSQL :** `code_source/src/infrastructure/firestore_sync.py`
  - Convertisseur de types bidirectionnel conforme à l'API Google Cloud Firestore REST v1 (sans dépendance C/gRPC lourde).
  - Push des compétitions, participants, annuaire des adhérents et créneaux.
  - Pull des sélections et modifications mobiles vers la BDD SQLite locale.

### C. Application Mobile PWA & Design Existant (Lot 3)
- **Conservation de la charte graphique :** Palette sombre `#1E293B`, cartes blanches arrondies, boutons d'action bleu et vert, barre de navigation mobile fixe en bas d'écran.
- **Modale d'envoi d'e-mails pour les coachs :** Choix des destinataires (sélectionnés, en attente de paiement, tous), choix du modèle, aperçu en direct et bouton d'action `🚀 Envoyer via Gmail`.
- **Appel d'urgence 1-clic :** Bouton `📞 Appeler` cliquable sur chaque carte d'athlète.
- **PWA Autonome :** `web/manifest.webmanifest` et `web/sw.js` pour installation sur écran d'accueil smartphone et cache hors-ligne des compétitions.

---

## 4. Détail des Réalisations du Lot 4 (Déploiement Cloud Run & Production)

Le **Lot 4** finalise l'infrastructure de production conteneurisée et son intégration avec l'écosystème :

### A. Conteneurisation & Optimisation Cloud Run
- **Fichier `code_source/Dockerfile` :**
  - Base `python:3.11-slim` multi-plateforme.
  - Dépendances épurées via `code_source/requirements-docker.txt` (exclusion de `PySide6`, `pywin32` et `python-docx` réservés au client lourd Windows).
  - Port d'écoute dynamique configuré sur la variable d'environnement `PORT` (8080 par défaut sur Cloud Run).
  - Sonde de santé interne `HEALTHCHECK` intégrée.
  - Exécution sous utilisateur non-root `appuser` pour une sécurité renforcée.
- **Sécurisation via `.dockerignore` :**
  - Exclusion stricte des fichiers de secrets (`.env`), des caches (`.pytest_cache/`, `__pycache__/`) et des bases SQLite locales contenant des données personnelles réelles.

### B. Routes de Production & Endpoints
- **`GET /health` :** Retourne le statut de santé du service (`"healthy"`), la version (`APP_VERSION = "2.3.0"`), la saison active et l'horodatage.
- **`GET /` :** Redirige automatiquement vers la PWA `/competitions` ou fournit l'annuaire d'accès.
- **`GET /webhooks/helloasso` :** Répond `HTTP 200 OK` avec le descriptif du webhook, permettant à HelloAsso et aux sondes de surveillance de valider immédiatement la disponibilité de l'endpoint lors de la configuration.
- **`POST /webhooks/helloasso` :** Rapprochement automatique des paiements et mise à jour instantanée du statut des compétiteurs.

### C. Déploiement Automatisé & Documentation
- **Scripts de déploiement en 1 clic :**
  - `code_source/deploy_cloud_run.bat` & `deploy_cloud_run.bat` (racine) pour Windows.
  - `code_source/deploy_cloud_run.sh` pour Google Cloud Shell et Linux.
  - Paramètres Cloud Run optimisés pour le Free Tier : région `europe-west1`, mémoire `512Mi`, CPU `1`, scaling de 0 à 2 instances (`--min-instances 0` garantit un coût de 0 € au repos).
- **Guide complet de mise en production :**
  - `code_source/docs/guide_deploiement_cloud_run_helloasso.md` détaillant le déploiement Cloud Shell (sans outil à installer), la configuration des variables d'environnement, la déclaration du Webhook dans l'interface HelloAsso et le protocole de recette de bout en bout.

---

## 5. Bilan Global du Projet Cloud & Mobile
L'ensemble des 4 lots est désormais **achevé, testé (236 tests unitaires au vert) et prêt pour la mise en ligne**. L'association dispose d'une infrastructure moderne, réactive en temps réel, accessible sur mobile par les coachs, et pérenne à 0 €/mois.
