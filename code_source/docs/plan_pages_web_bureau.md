# Plan — Version web « Bureau » (ordinateur) de l'application desktop

Objectif : un portail web pour ordinateur, à côté de la PWA smartphone (`/competitions`, `/index`, inchangées),
qui reprend : annuaire des adhérents avec filtres puissants, attestations (génération + envoi), communications
(e-mails + modèles), et donne accès à la carte et à l'analyse des effectifs.

## 1. Constat sur l'existant

| Brique | État aujourd'hui | Conséquence |
|---|---|---|
| Données adhérents | Firestore `crm_*` (source de vérité), lues dans le navigateur par `web/index.html` (reconstruction de `v_adherents_legacy` en JS) | Réutilisable tel quel pour la liste et les filtres |
| E-mails | API Cloud Run : `/api/email-templates`, `/preview-email`, `/send-email`, `/email-status` + `EmailDispatchService` (variables, signature, Gmail OAuth2/SMTP) | Existe, mais pas de CRUD des modèles, pas de pièce jointe, journal d'audit dans un fichier local (perdu au redémarrage de Cloud Run) |
| Attestations | `attestation_generator.py` : Word par `python-docx` (OK sous Linux) ; PDF par **QtWebEngine** (impossible sur Cloud Run) ; données prises à l'Excel/SQLite | Il faut isoler le rendu et remplacer le moteur PDF |
| Carte / Analyse effectifs | Pages serveur `/map` et `/pivot` | Protégées par jeton : une navigation simple ne peut pas envoyer l'en-tête `Authorization` → à intégrer par `fetch` + iframe `srcdoc` (voir §5) |
| Authentification | Firebase + middleware `api_auth` (coach/admin) | Réutilisée sans changement |
| Code web | 2 gros fichiers HTML autonomes (2 700 et 850 lignes) qui dupliquent auth, version, style | Extraire un socle commun avant d'ajouter 4 pages |

## 2. Architecture cible

```
web/
  competitions.html, index.html, sw.js     ← PWA smartphone (inchangée)
  bureau/
    index.html          Accueil minimal : 4 liens
    adherents.html      Liste + filtre sous-catégories + boutons « E-mail » / « Attestation » par adhérent
    outils.html         Carte et Analyse des effectifs (iframes)
  shared/
    alj-core.js         Firebase init, login, apiFetch, rôles, badge de version, cache   [étape 0 : fait]
    alj-shell.js        Menu latéral, en-tête, contrôle connexion/rôle (startBureau())   [étape 0 : fait]
    alj-vue.js          Choix ordinateur / smartphone des pages PWA (script classique)  [étape 0 : fait]
    alj.css             Charte (reprise de la PWA) + mise en page ordinateur            [étape 0 : fait]
    alj-members.js      Chargement crm_* + reconstruction v_adherents_legacy (extrait de index.html)  [étape 1 : fait]
    alj-filters.js      Filtre « sous-catégories » repris de index.html (voir §3)        [étape 1 : fait]
```

- **Choix de la page d'accueil** (étape 0, fait) : les pages PWA (`/`, `/competitions`, `/index`) chargent
  `shared/alj-vue.js` : sur ordinateur (écran ≥ 1024 px, `any-pointer: fine`) elles renvoient vers `/bureau/`.
  `?vue=mobile` reste sur la PWA et mémorise le choix (`localStorage` `alj_vue`) ; `?vue=pwa` ouvre la PWA une fois
  (liens internes du bureau). Pas de redirection pendant la connexion (`?login=1`, retour `#access_token`).
  Un bouton 🖥️ ajouté dans l'en-tête de la PWA (sur ordinateur) revient au bureau et oublie le choix.
  Le menu Bureau a un lien « Version mobile ».
- **Un seul numéro de version web** pour tout (meta, title, badge, `CACHE_NAME`), le test `test_mobile_pwa`
  est étendu aux pages `bureau/*`.
- Pas de framework ni d'étape de build (cohérent avec l'existant) : HTML + modules ES + CSS. `server.py` sert
  `web/shared/` sous `/static-web/` et `web/bureau/` sous `/bureau/` (pages whitelistées) ; les deux préfixes sont
  publics dans `api_auth.PUBLIC_PREFIXES`, les données restent protégées par Firestore et par l'API.
- Mise en page ordinateur : menu latéral fixe, en-tête avec saison et compte, tableaux larges, panneau de détail à droite.
- Rôles : coach = lecture seule ; admin = envoi d'e-mail / d'attestation à un adhérent.

## 3. Page Adhérents (équivalent de `members.py`) — version simplifiée

**Tableau** : colonnes principales (nom, prénom, catégorie, tarif, statut, créneaux, e-mail, téléphone, licence),
tri simple, 287 lignes tout en mémoire, panneau de détail à droite (fiche complète comme l'annuaire mobile).

**Filtre unique : la sélection des sous-catégories (tarifs)**, reprise telle quelle du panneau « Filtres » de
`index.html` (saison + cases à cocher par catégorie/sous-catégorie, « tout sauf liste d'attente » par défaut,
code extrait dans `alj-filters.js`). Une recherche texte simple (nom) est conservée, comme dans l'annuaire.
Pas d'opérateurs ET/OU, pas de négation, pas de filtres enregistrés.

**Export CSV** de la liste affichée : option bon marché, à garder si le temps le permet.

**Lecture seule** : aucune écriture de fiche sur le web (étape d'édition supprimée) ; les modifications restent
dans l'application de bureau.

**Boutons par adhérent (admin uniquement)** : « ✉️ E-mail » et « 📄 Attestation » (voir §4 et §5).

## 4. Attestation (équivalent de `documents.py` + `attestation_generator.py`) — un adhérent à la fois

Pas de page dédiée : action depuis la fiche d'un adhérent.
1. **Refactor serveur** : fonction pure `build_attestation(member, season, date_jour) -> html` sans fichiers ni Qt
   (PDF uniquement). Règles conservées : ignorer montant 0 € et commandes annulées ; payeur par défaut = adhérent.
2. **PDF** par **WeasyPrint** (`libpango` dans le Dockerfile, ≈ +60 Mo). Pas de `python-docx`.
3. **API** (admin) : `POST /api/attestations/preview` (PDF dans une fenêtre, aperçu) et
   `POST /api/attestations/send` (PDF créé en mémoire, joint à l'e-mail, non sauvegardé, puis mise à jour de la date d'envoi).
4. Pas d'envoi en lot, pas de ZIP, pas de barre de progression.

## 5. E-mail — un destinataire à la fois

- **Point d'entrée unique** : bouton « ✉️ E-mail » sur la fiche d'un adhérent (page Adhérents), admin uniquement.
- Fenêtre : choix d'un modèle **existant**, sujet/corps modifiables, aperçu fidèle (API `preview-email` existante),
  bouton « Envoyer » vers l'adresse de l'adhérent, via la route d'envoi existante, expéditeur = compte Gmail déjà configuré.
- **Pas de page Communications**, pas de gestion des modèles (création, modification, suppression restent dans
  l'application de bureau), pas d'envoi groupé, pas d'historique d'envoi (reporté), pas de limite par minute, pas d'anti-doublon.
- Garde-fous conservés : admin seulement, confirmation « Envoyer à Prénom Nom <adresse> ? ». Un seul destinataire par action rend
  le plafond de 500 par jour et le mode test inutiles à ce stade ; à ajouter avec l'envoi groupé.
- Prérequis : vérifier `/api/email-status` (identifiants Gmail en variables d'environnement ; à passer dans Secret Manager plus tard).

## 6. Page Outils

`/map` et `/pivot` sont chargés par `apiFetch` puis affichés en `iframe srcdoc` (le jeton ne passe pas par une
navigation simple). **On garde les iframes** ; pas de refonte en lecture Firestore.

## 7. Accueil Bureau

Page minimale : liens vers Adhérents, Outils, Compétitions et Version mobile. Pas de KPI.

## 8. Étapes et estimation

| # | Étape | Contenu | Jours |
|---|---|---|---|
| 0 | Socle | `shared/*`, route `/bureau`, menu latéral, accueil à 4 liens, redirection ordinateur, tests de version | 1 — **fait (v13)** |
| 1 | Adhérents | Tableau, détail, filtre sous-catégories repris de l'index, recherche | 1,5 — **fait (v14)** |
| 2 | E-mail | Bouton, fenêtre modèle/aperçu, envoi à un adhérent | 0,5 — **fait (v15)** |
| 3 | Attestation | Refactor, WeasyPrint, aperçu, envoi + date d'envoi | 2 |
| 4 | Outils | Iframes carte et effectifs | 0,5 |
| 5 | Recette | Tests navigateur sans écran, essai réel admin/coach, déploiement | 1 |

Total : **environ 6,5 jours** (contre 12). Une étape = un déploiement, version web +1.

## 9. Tests

- Pytest : `build_attestation` (mêmes textes que l'ancien générateur), routes (rôles, 401), version cohérente sur les pages `bureau/*`.
- Filtre : même nombre de résultats que `index.html` sur la vraie base (264 / 287).
- Puppeteer avec faux Firebase (comme l'annuaire) : filtre, fiche, envoi simulé, boutons absents pour un coach.
- Test PDF : rendu d'une attestation, texte vérifié par `pdftotext`.

## 10. Risques

- **Envoi d'e-mail à la mauvaise personne** : confirmation avec nom et adresse, un seul destinataire.
- **Image Docker plus lourde et démarrage à froid plus lent** (WeasyPrint) ; à mesurer.
- **Données sensibles** (santé, urgences) : coachs et admins seulement, pas de stockage local persistant.
- **Quotas Gmail** : non concernés tant que l'envoi reste unitaire.

## 11. Décisions (réponses de l'utilisateur)

1. Écriture des fiches sur le web : **supprimée** (lecture seule).
2. Envoi d'e-mails et d'attestations : **administrateurs uniquement**.
3. Gestion des modèles d'e-mails sur le web : **reportée** ; on utilise les modèles existants.
4. Filtres : **uniquement la sélection des sous-catégories**, identique à celle de la page index ; pas de filtres enregistrés.
5. E-mail : **un seul destinataire**, depuis le bouton « E-mail » de la page Adhérents. Pas d'envoi groupé ni d'historique pour l'instant.
6. Attestations : PDF seul via WeasyPrint, créé en mémoire et joint à l'e-mail, non sauvegardé ; traitées comme l'e-mail (un adhérent à la fois, hypothèse à confirmer).
7. Outils : iframes conservées. Accueil : minimal.
8. Expéditeur : compte Gmail déjà configuré. Arrivée sur ordinateur : **redirection automatique** vers `/bureau`, lien « Version mobile ».
