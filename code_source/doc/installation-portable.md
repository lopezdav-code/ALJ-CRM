# ALJ Escalade Manager — Installation portable & mises à jour

## Première installation (5 minutes)

1. Télécharger **`ALJ_Portable_vX.Y.Z.zip`** depuis la page
   [Releases du projet](https://github.com/lopezdav-code/ALJ-CRM/releases)
   (dernière release, section *Assets*).
2. Extraire le dossier **`ALJ`** où vous voulez : sur le disque dur, sur une clé USB...
   (clic droit → *Extraire tout*).
3. Double-cliquer sur **`Lancer-ALJ.bat`**.

Au premier lancement :
- l'application démarre directement (tout est embarqué, aucune installation) ;
- pour l'envoi d'e-mails / Google Drive, cliquer sur *Paramètres* dans l'application
  et suivre l'assistant de connexion Google (1 clic, propre à chaque ordinateur).

> Si Windows affiche « Windows a protégé votre PC », cliquer
> **Informations complémentaires → Exécuter quand même** (application non signée).

## Mises à jour automatiques

À **chaque démarrage**, le programme vérifie discrètement la dernière version publiée :

| Situation | Comportement |
|---|---|
| Nouvelle version disponible | Téléchargement (~1 Mo), vérification de l'empreinte, mise à jour puis lancement |
| Pas de réseau / GitHub indisponible | Lancement direct de la version installée (jamais bloquant) |
| Déjà à jour | Lancement direct |

Les **données ne sont jamais touchées** par une mise à jour : le dossier `data\`
(cache local, journaux) est conservé, et la base de référence reste sur Google Drive.

## En cas de problème après une mise à jour

Double-cliquer sur **`Restaurer-version-precedente.bat`** : la version précédente
(dossier `app_old\`) est remise en place immédiatement.

## Structure du dossier (pour information)

```
ALJ\
├── runtime\    Python embarqué + dépendances (ne pas modifier)
├── app\        code de l'application (géré par les mises à jour)
├── data\       cache local, journal d'audit e-mail (vos données)
├── launcher\   programme de mise à jour
├── updater.json           configuration (repo GitHub)
├── Lancer-ALJ.bat         point d'entrée
└── Restaurer-version-precedente.bat   plan B
```

## Pour les développeurs — publier une nouvelle version

1. Mettre à jour `APP_VERSION` dans `code_source/src/domain/constants.py`
   **et** `code_source/VERSION` (ils doivent être identiques).
2. Committer puis créer le tag : `git tag v2.0.9 && git push origin v2.0.9`.
3. La CI vérifie la cohérence des versions, lance lint/mypy/tests, construit
   `alj_source_v2.0.9.zip` + `ALJ_Portable_v2.0.9.zip` + `SHA256SUMS.txt`
   et les publie automatiquement dans la release.
4. Les utilisateurs reçoivent la mise à jour au prochain démarrage.
