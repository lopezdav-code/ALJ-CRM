# 📈 Plan de Migration et Modernisation de l'Application
> **Passage progressif et sécurisé de Tkinter à PySide6 / Qt**

Ce document décrit le plan stratégique et technique conçu par un architecte logiciel senior pour moderniser l'application ALJ Escalade. Il détaille la refactorisation de l'architecture, la mise en place d'un modèle d'exécution asynchrone (multithreading Qt) et la migration de l'interface graphique de Tkinter vers PySide6 (Qt).

---

## 1. Objectifs de l'Architecture Cible

L'architecture cible repose sur une séparation stricte des responsabilités (Clean Architecture / N-Tier) structurée comme suit :

1.  **Couche Présentation (`presentation/`)** : Gérée par **PySide6**. Aucune logique métier, aucun appel réseau, et aucune écriture de fichier ne s'y déroulent directement. Elle observe les modèles de présentation et interagit avec les cas d'utilisation via des signaux Qt.
2.  **Couche Application (`application/`)** : Contient les cas d'utilisation métier (`use_cases/`) et les Workers asynchrones (`workers/` héritant de `QThread`/`QRunnable`) pour exécuter les opérations lourdes en arrière-plan sans bloquer l'IHM.
3.  **Couche Domaine (`domain/`)** : Contient les modèles de données structurés (`Member`, `Payment`, `Course`), les validateurs (adresses mail, structures de données) et les constantes (saisons, codes couleurs). Cette couche est 100% pure Python, sans dépendance externe ou graphique, ce qui la rend extrêmement facile à tester unitairement.
4.  **Couche Infrastructure (`infrastructure/`)** : Gère l'accès aux services externes et disques (client HelloAsso, Gmail REST client, Google Drive client, parseur/générateur Excel et Word, ainsi que le trousseau système sécurisé `keyring`).
5.  **Couche Configuration (`config/`)** : Charge, valide et centralise les paramètres de l'application (fichiers `.env`, mappages des tarifs et templates).

---

## 2. Découpage en Lots de Développement (Phasage)

Afin de garantir la stabilité de l'application et d'éviter l'effet tunnel, la migration est découpée en **5 lots incrémentaux**. À la fin de chaque lot, l'application reste exécutable et entièrement testable.

### 📅 Lot 1 : Consolidation du Domaine, de la Sécurité et Corrections de Base
*   **Objectifs** : Résoudre les bugs prioritaires (calcul de montants, découplage des saisons), et créer les classes de modèles stables.
*   **Actions** :
    1.  Créer les modèles de données immuables `domain/models.py` (Adhérent, Paiement, etc.).
    2.  Ajouter les validateurs rigoureux dans `domain/validators.py` pour sécuriser les e-mails et les montants (virgules, espaces, valeurs vides).
    3.  Centraliser la gestion de la saison active dans une variable de configuration dynamique (plus de `2026-2027` codé en dur).
    4.  Établir un protocole de génération de noms de fichiers uniques (combinant identifiant HelloAsso + nom) pour éviter les collisions et écrasements accidentels.
    5.  Créer les tests unitaires associés pour valider ces règles métier.

### 📅 Lot 2 : Rénovation de la Couche Infrastructure et Découplage du Monolithe
*   **Objectifs** : Extraire la logique métier et les intégrations externes (Drive, Excel, Word, Mail) de l'interface `create_excel.py`.
*   **Actions** :
    1.  Extraire les fonctions d'écriture Excel dans `infrastructure/excel_repository.py`.
    2.  Extraire les fonctions de téléchargement/versement Google Drive dans `infrastructure/google_drive_client.py`.
    3.  Sécuriser la gestion des secrets et jetons d'authentification en créant `infrastructure/secret_store.py` (intégration de `keyring` pour stocker de façon chiffrée sous Windows les secrets d'API et mots de passe).
    4.  Extraire l'envoi d'e-mails et la journalisation d'envoi dans `infrastructure/email_repository.py` avec création d'un fichier de journal d'audit local.

### 📅 Lot 3 : Création du Squelette PySide6, Navigation et Pages de Base
*   **Objectifs** : Mettre en place le moteur d'affichage PySide6 et la fenêtre principale avec navigation fluide par barre latérale.
*   **Actions** :
    1.  Créer la fenêtre principale `presentation/main_window.py` avec une barre latérale de navigation sobre et moderne (Palette : bleu profond `#163A5F`, bleu d'action `#2563EB`, surfaces `#FFFFFF`).
    2.  Créer les pages d'accueil (`pages/dashboard.py`) et de paramètres (`pages/settings.py`) reliées aux configurations réelles de l'application.
    3.  Remplacer les popups Tkinter par des boîtes de dialogue natives Qt (`QMessageBox`, `QFileDialog`).

### 📅 Lot 4 : Grille d'Adhérents Performance (Modèle QAbstractTableModel) et Fiche Individuelle
*   **Objectifs** : Afficher de façon fluide et performante plusieurs centaines d'adhérents avec filtres et tris instantanés sans lag.
*   **Actions** :
    1.  Implémenter `MemberTableModel` héritant de `QAbstractTableModel` pour alimenter un composant `QTableView` moderne.
    2.  Ajouter une barre de recherche globale en temps réel, des filtres multicritères (statuts, tarifs) et le tri dynamique des colonnes.
    3.  Concevoir le panneau latéral de détails d'adhérent (fiche d'identité, coordonnées d'urgence, historiques) s'ouvrant d'un clic sur une ligne.
    4.  Implémenter la barre d'action de masse contextuelle (visible uniquement en cas de sélection multiple).

### 📅 Lot 5 : Workers Asynchrones (Multithreading Qt), Progression et Finalisation
*   **Objectifs** : Rendre l'application extrêmement réactive en déléguant toutes les tâches de calcul et de réseau à des threads d'arrière-plan avec barre de progression interactive.
*   **Actions** :
    1.  Développer les workers Qt (`QThread` / `QThreadPool` / `QRunnable`) pour :
        *   La synchronisation HelloAsso (`SyncMembershipWorker`).
        *   L'envoi d'e-mails groupés (`EmailCampaignWorker`).
        *   La compilation d'attestations Word/PDF (`AttestationGeneratorWorker`).
    2.  Intégrer des barres de progression non bloquantes, des notifications de succès temporaires et des boîtes de dialogue de progression annulables.
    3.  Assurer la traçabilité des opérations en connectant le logger à la page de logs de l'interface paramètres.
    4.  Passer tous les tests d'intégration et désactiver définitivement Tkinter en renommant l'entrée principale vers `app.py`.

---

## 3. Matrice de Risques du Plan de Migration

| Risque identifié | Niveau | Mesure d'atténuation |
| :--- | :--- | :--- |
| **Effet tunnel (IHM inutilisable pendant la migration)** | Moyen | **Phasage progressif** : Le lot 1 et le lot 2 conservent l'IHM Tkinter en cours d'exécution tout en purgeant son code interne. L'IHM PySide6 est intégrée au lot 3. |
| **Perte de compatibilité avec Microsoft Word COM** | Élevé | La logique d'interaction COM dans `attestation_generator.py` est encapsulée dans une interface `DocumentGenerator`. Si l'automation COM échoue sous Windows, un fallback d'écriture en format `.docx` seul est automatiquement proposé à l'utilisateur. |
| **Conflits de Threads (Écritures Excel simultanées)** | Élevé | **Mutex de fichiers** : Utilisation de verrous mémoires au niveau applicatif et désactivation temporaire des contrôles de l'IHM Qt pendant qu'un Worker écrit dans un fichier Excel ou communique sur le réseau. |
