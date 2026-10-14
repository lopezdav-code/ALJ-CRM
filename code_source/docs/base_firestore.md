# Base des adhérents dans Firestore (v2.4.0)

Depuis le 8 octobre 2026, la base principale (ex-`database.db` partagée sur Google Drive)
est stockée dans Firestore, projet `smart-amplifier-510811-n6`.

## Organisation

| Table SQLite | Collection Firestore | ID du document |
|---|---|---|
| seasons, users, orders, purchases, purchase_options, planning, email_templates | `crm_<table>` | ID SQLite |
| app_settings, geocache (clé texte) | `crm_<table>` | `h` + SHA-1 de la clé |

Chaque document contient les colonnes de la ligne, plus :
`_modified_at` (horodatage serveur), `_modified_by` (poste), `_deleted` (ligne supprimée).

Les collections `adherents` et `planning` (annuaire lu par la PWA et le webhook) sont des
**projections** recalculées automatiquement après chaque modification d'adhérents
(au plus toutes les 3 minutes, et à la fermeture de l'application).

## Fonctionnement de l'application de bureau

- `database.db` est un **cache** : reconstruit depuis Firestore au premier lancement
  (l'ancien fichier est sauvegardé dans `data/backups/database_avant_firestore_*.db`),
  puis mis à jour de façon incrémentale.
- Des déclencheurs SQLite notent chaque ligne modifiée ; elles sont envoyées toutes les
  15 s, champ par champ, avec contrôle de version : deux postes qui modifient des champs
  différents d'un même adhérent ne s'écrasent pas.
- Les modifications des autres postes sont reçues toutes les 2 minutes, et à chaque
  « Télécharger » / synchronisation HelloAsso.
- Hors connexion : l'application travaille sur la copie locale ; les modifications
  partent au retour du réseau (pied de page : « ⏳ N modification(s) à envoyer »).
- Une copie du cache est encore déposée sur Google Drive (`GOOGLE_DRIVE_DB_ID`), en
  lecture seule (sauvegarde) ; l'annuaire web ne l'utilise plus.

## Annuaire web (`web/index.html`, URL `/index`)

- Lit `GET /api/seasons` et `GET /api/members?season=` (une saison à la fois). La liste
  est calculée sur le serveur (`domain/member_view.py`) depuis son cache SQLite des
  collections `crm_*` ; le navigateur ne lit plus Firestore.
- Réservé aux coachs/admins (rôle vérifié par l'API). Connexion Google commune avec
  `/competitions` : le bouton « Se connecter » passe par `/competitions?login=1`
  (URI de redirection OAuth déjà autorisée) puis revient sur l'annuaire
  (`sessionStorage.alj_after_login`).
- Actualisation toutes les 20 s quand la page est visible (`alj-members-sync.js`,
  ETag/304) ; le bouton 🔄 recharge immédiatement. Pas de copie hors ligne : l'annuaire
  nécessite le réseau. L'ancienne copie hors ligne du SDK Firestore (IndexedDB) est
  effacée au démarrage par `alj-firebase.js`.
- Même numéro de version que `competitions.html` (meta `alj-web-version`, titre,
  badge, `CACHE_NAME` de `sw.js`).

Code : `src/infrastructure/cloud_database.py`.

## Cloud Run

Le serveur construit son cache au premier appel d'une route de données, le rafraîchit
si la dernière réception date de plus de 30 s et envoie ses écritures (planning,
e-mails, géocodage) juste après la requête.

## Migration, vérification

```
ALJ_FIRESTORE_ACCESS_TOKEN=$(gcloud auth print-access-token) \
  python src/migrate_sqlite_to_firestore.py chemin/database.db --dry-run | --apply | --verify
```

`--verify` reconstruit un cache depuis Firestore et le compare à la source, table par
table puis via `load_direct_data` pour chaque saison.

Migration du 08/10/2026 : 1 991 documents, vérification identique pour 2025-2026
(264 adhésions) et 2026-2027 (287).

## Sauvegardes

- Restauration à un instant donné (PITR, 7 jours) activée sur Firestore.
- Sauvegarde Firestore quotidienne, conservée 14 jours.
- Copie de la base source avant migration :
  `gs://smart-amplifier-510811-n6-sauvegardes-alj/database/`.

## Retour arrière

Paramètres → « Base principale » = `drive` : l'application revient au partage du fichier
`database.db` par Google Drive (les modifications faites dans Firestore depuis la
bascule n'y figurent pas).

## Droits (firestore.rules)

Aucun accès client (`allow read, write: if false` sur tous les documents) : les pages
web passent par l'API, qui vérifie les rôles (`api_auth.py`). L'application de bureau
(jeton OAuth du club) et Cloud Run (compte de service) passent par IAM, auquel les
règles ne s'appliquent pas. Ordre de déploiement : README, section Cloud Run.
