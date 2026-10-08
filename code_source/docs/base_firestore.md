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
- Une copie du cache est toujours déposée sur Google Drive (`GOOGLE_DRIVE_DB_ID`), en
  lecture seule, pour l'annuaire web `index.html`.

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

`crm_*` : lecture coachs (état civil, contacts d'urgence et santé compris), écriture
admins. L'application de bureau et Cloud Run passent par IAM.
