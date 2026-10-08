# 🚀 Guide de Déploiement Google Cloud Run & Configuration HelloAsso
> **ALJ Escalade Manager — Architecture Cloud & Mobile (PWA & Webhooks)**
> **Modèle Économique : 0 € / mois (Garanti par les quotas Google Cloud Free Tier)**

Ce guide détaille pas-à-pas la mise en production du micro-service backend et de la PWA mobile sur Google Cloud Run, ainsi que l'interconnexion en temps réel avec HelloAsso.

---

## 1. 🏗️ Architecture et Principe de Fonctionnement

```
   [ Adhérent / Parent ]
             │
             │ (Paiement en ligne de l'inscription compétition)
             ▼
      [ HELLOASSO ]
             │
             │  POST /webhooks/helloasso (Notification instantanée)
             ▼
 ┌─────────────────────────────────────────────────────────────┐
 │           GOOGLE CLOUD RUN (FastAPI Micro-service)          │
 │                                                             │
 │  1. Réception Webhook & Rapprochement (Matching auto)      │
 │  2. Mise à jour statut participant -> "Payé"                │
 │  3. Mise à jour Firestore NoSQL & SQLite                    │
 │  4. API Envoi d'Emails (Gmail API OAuth2)                   │
 └─────────────────────────────────────────────────────────────┘
             ▲                                    │
             │ REST (Pull / Push)                 │ Envoi convocation
             │                                    ▼
 ┌───────────────────────┐            ┌────────────────────────┐
 │   PWA Mobile Coachs   │            │ Boîte Mail Compétiteur │
 │ (/competitions)       │            │ (Gmail / Notification) │
 └───────────────────────┘            └────────────────────────┘
```

### Avantages Clés :
- **Scalabilité à Zéro (`--min-instances 0`) :** Lorsque personne n'utilise l'application ou qu'aucun paiement n'arrive, aucune instance ne tourne. Facture mensuelle = **0,00 €**.
- **Haute Disponibilité :** Certificat SSL HTTPS automatique géré par Google.
- **Réaction Instantanée :** Le statut passe à « Payé » dès que la carte bancaire est validée sur HelloAsso.

---

## 2. 🚀 Méthode 1 : Déploiement via Google Cloud Shell (Recommandée)

Cette méthode ne nécessite **aucune installation** sur votre ordinateur (ni Docker, ni Python, ni gcloud). Tout s'exécute depuis le navigateur web.

1. Connectez-vous sur la console Google Cloud : [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Sélectionnez votre projet Google Cloud (ex: `alj-2027`).
3. Cliquez sur l'icône **Activer Cloud Shell** `>_` en haut à droite de l'écran.
4. Dans le terminal Cloud Shell qui s'ouvre au bas de l'écran, clonez le projet ou téléversez le dossier du code :
   ```bash
   git clone <URL_DU_DEPOT_GIT>
   cd ALJ-CRM/code_source
   ```
5. Rendez le script de déploiement exécutable et lancez-le :
   ```bash
   chmod +x deploy_cloud_run.sh
   ./deploy_cloud_run.sh
   ```
6. Le script compile l'image conteneur via Google Cloud Build et déploie le service sur Cloud Run en région `europe-west1`.
7. À la fin, l'URL publique de votre service est affichée :
   ```
   https://alj-escalade-api-xxxxxxxx-ew.a.run.app
   ```

---

## 3. 💻 Méthode 2 : Déploiement depuis votre PC Windows

Si vous préférez déployer depuis votre machine locale :

1. Téléchargez et installez le **Google Cloud SDK** : [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)
2. Ouvrez une invite de commande (cmd) et authentifiez-vous :
   ```cmd
   gcloud auth login
   gcloud config set project alj-2027
   ```
3. Activez les API nécessaires (une seule fois par projet) :
   ```cmd
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com
   ```
4. Double-cliquez sur `deploy_cloud_run.bat` à la racine du projet ALJ-CRM (ou dans `code_source/`).
5. Confirmez le déploiement en appuyant sur `O`.

---

## 4. ⚙️ Configuration des Variables d'Environnement en Production

Pour que le serveur communique avec HelloAsso, Gmail et Firestore, configurez les variables d'environnement de votre service Cloud Run sans avoir besoin de modifier le code :

```bash
gcloud run services update alj-escalade-api \
    --region europe-west1 \
    --update-env-vars \
CLIENT_ID="VOTRE_CLIENT_ID_HELLOASSO",\
CLIENT_SECRET="VOTRE_CLIENT_SECRET_HELLOASSO",\
CAMPAIGN_SLUG="adhesion-escalade-2026-2027-amicale-laique-escalade-2",\
ACTIVE_SEASON="2026-2027",\
GMAIL_SENDER_EMAIL="contact@alj-escalade.fr",\
GOOGLE_PROJECT_ID="alj-2027"
```

*Note : Ces variables peuvent également être saisies directement dans l'interface graphique Google Cloud Console (Cloud Run → alj-escalade-api → Modifier et déployer une nouvelle révision → Variables et secrets).*

---

## 5. 🔔 Configuration du Webhook dans HelloAsso

Dès que votre URL Cloud Run est active, configurez les notifications HelloAsso :

1. Rendez-vous sur l'espace d'administration HelloAsso : [https://admin.helloasso.com/](https://admin.helloasso.com/)
2. Dans le menu de gauche, rendez-vous dans **Mon association** puis **Intégrations & API** (ou **Paramètres / Notifications Webhook**).
3. Cliquez sur **Ajouter une URL de notification** ou **Nouveau Webhook**.
4. Renseignez l'URL publique générée, **avec le jeton secret** :
   ```
   https://alj-escalade-api-xxxxxxxx-ew.a.run.app/webhooks/helloasso?token=<HELLOASSO_WEBHOOK_TOKEN>
   ```
5. Cochez les événements à surveiller :
   - ✅ **Paiement (Payment)** : Déclenché lors de tout règlement par carte bancaire.
   - ✅ **Commande (Order)** : Déclenché lors de la finalisation d'un panier d'inscription.
6. Cliquez sur **Enregistrer** (ou **Tester le webhook**).
   - Le serveur FastAPI répond instantanément `HTTP 200 OK` avec le statut actif grâce à la route de probe `GET /webhooks/helloasso`.

### 🔒 Sécurité de l'API et du webhook

- **Jeton du webhook** : stocké dans Secret Manager (secret `helloasso-webhook-token`) et injecté dans la variable `HELLOASSO_WEBHOOK_TOKEN` :
  ```bash
  gcloud secrets versions access latest --secret helloasso-webhook-token   # lire le jeton
  gcloud run services update alj-escalade-api --region europe-west1 \
      --update-secrets HELLOASSO_WEBHOOK_TOKEN=helloasso-webhook-token:latest
  ```
  Une notification sans le bon `?token=` est refusée (`401`).
- **Relecture HelloAsso** : si `HELLOASSO_CLIENT_ID` / `HELLOASSO_CLIENT_SECRET` sont configurés sur Cloud Run, le serveur ne lit que les identifiants d'articles dans la notification et relit montant, état, payeur et champs personnalisés auprès de l'API HelloAsso. Un contenu falsifié est donc sans effet.
  Identifiants rangés dans Secret Manager (`helloasso-client-id`, `helloasso-client-secret`, `helloasso-org-slug`) :
  ```bash
  gcloud run services update alj-escalade-api --region europe-west1 \
      --update-secrets HELLOASSO_CLIENT_ID=helloasso-client-id:latest,HELLOASSO_CLIENT_SECRET=helloasso-client-secret:latest,HELLOASSO_ORG_SLUG=helloasso-org-slug:latest
  ```
- **Fail-closed** : en production, une notification qui ne peut être vérifiée ni par le jeton ni par l'API est refusée (`503`).
- **API `/api/*`, `/map`, `/pivot`, `/docs`** : réservées aux comptes connectés à la PWA. La PWA envoie le jeton Firebase (`Authorization: Bearer …`) ; le serveur vérifie sa signature et applique les rôles de `firestore.rules` (coach requis, admin pour `POST /api/planning`). Restent publics : `/`, `/competitions`, `/annuaire`, `/health`, `/api/web-version`, `/sw.js`, `/manifest.webmanifest` et le webhook. Contrôle actif dans l'image Docker (`ALJ_API_AUTH=required`), désactivé pour le serveur local de l'application de bureau.

---

## 6. 🧪 Protocole de Recette de Bout en Bout

### Test A : Vérification de Santé de l'API
Dans votre navigateur web, ouvrez :
```
https://alj-escalade-api-xxxxxxxx-ew.a.run.app/health
```
Réponse attendue :
```json
{
  "status": "healthy",
  "service": "alj-escalade-api",
  "version": "2.3.0",
  "season": "2026-2027",
  "timestamp": "2026-10-06T..."
}
```

### Test B : Installation de la PWA Mobile par les Coachs
1. Sur un smartphone (iOS Safari ou Android Chrome), ouvrez :
   ```
   https://alj-escalade-api-xxxxxxxx-ew.a.run.app/competitions
   ```
2. Sur Android : appuyez sur la bannière **« Ajouter à l'écran d'accueil »**.
3. Sur iOS : appuyez sur **Partager** puis **« Sur l'écran d'accueil »**.
4. L'icône de l'ALJ Escalade s'affiche comme une véritable application native autonome, avec support hors-ligne grâce au Service Worker.

### Test C : Simulation d'un Paiement Webhook
Vous pouvez simuler l'envoi d'un webhook HelloAsso sans attendre un vrai paiement via PowerShell :

```powershell
$body = @{
    eventType = "Payment"
    data = @{
        id = 99901
        amount = 1500
        state = "Processed"
        payer = @{ firstName = "Lucas"; lastName = "MARTIN" }
        customFields = @(
            @{ name = "Numéro de licence FFME"; answer = "710083" },
            @{ name = "Numéro de la compétition"; answer = "18846" }
        )
    }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "https://alj-escalade-api-xxxxxxxx-ew.a.run.app/webhooks/helloasso?token=<HELLOASSO_WEBHOOK_TOKEN>" `
    -Method Post -ContentType "application/json" -Body $body
```
Vérifiez dans la PWA mobile que l'adhérent Lucas MARTIN passe immédiatement en badge vert **« Payé (15.00 €) »**.

*Si les identifiants API HelloAsso sont configurés, ce paiement simulé est ignoré (l'article 99901 n'existe pas chez HelloAsso) : c'est le comportement attendu de la protection.*

### Test D : Envoi d'E-mail depuis Smartphone
1. Dans la PWA `/competitions`, cliquez sur une compétition.
2. Cliquez sur le bouton bleu **« Envoyer un e-mail »**.
3. Sélectionnez le modèle **« Convocation compétition »**.
4. Vérifiez que l'aperçu dynamique remplace `{PRENOM}`, `{NOM_COMPETITION}`, `{LIEU}` et `{DATE_COMPETITION}`.
5. Cliquez sur **« Envoyer l'e-mail »** et vérifiez la confirmation d'expédition via l'API Gmail.
