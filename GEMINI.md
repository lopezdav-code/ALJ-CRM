# Projet : Pipeline d'Adhésion HelloAsso & FFME (Amicale Laïque de Jonage)

## Vue d'Ensemble
Ce projet est un pipeline d'automatisation développé en Python permettant de gérer les adhésions à la section Escalade de l'Amicale Laïque de Jonage. Il récupère les données depuis l'API HelloAsso et automatise plusieurs tâches chronophages de gestion administrative.

Les fonctionnalités principales incluent :
1. **Synchronisation des adhésions :** Importation des inscrits depuis HelloAsso vers un fichier de suivi Excel (stocké localement ou sur Google Drive).
2. **Génération d'attestations :** Création automatique d'attestations de paiement (au format Word `.docx` et PDF via l'automatisation COM de Microsoft Word).
3. **Communication :** Envoi groupé d'e-mails contenant les attestations générées via l'API Gmail (OAuth2) ou par SMTP.
4. **Génération de fichiers d'export :** Création de fichiers CSV structurés pour l'import dans l'intranet de la FFME, et génération de fiches de présence (format A3) au format Excel.
5. **Dashboard interactif :** Une interface locale FastAPI couplée à une interface graphique (Tkinter) permettant la visualisation des statistiques et le paramétrage du système.

## Architecture et Technologies Principales
*   **Langage :** Python 3
*   **API & Web :** FastAPI, `requests` (Appels API HelloAsso, Google Drive API, Gmail API).
*   **Manipulation de données :** `pandas`, `openpyxl` (pour Excel), `python-docx` (pour Word).
*   **Automatisation Windows :** `pywin32` (indispensable pour piloter Word et Excel localement afin de générer des PDF et manipuler les classeurs via COM).
*   **Configuration :** Variables d'environnement gérées via `python-dotenv` dans le dossier `code_source`.

## Structure du Répertoire
*   `code_source/` : Contient l'intégralité du code source Python (`create_excel.py`, `attestation_generator.py`, `server.py`, etc.), le fichier `.env` (non versionné) et `requirements.txt`.
*   `archive/` : Dossier contenant l'historique et les sauvegardes des fichiers générés.
*   `scripts_temporaires/` : Dossier dédié pour stocker les scripts ad-hoc de diagnostic, de tests temporaires, de requêtes ponctuelles ou de débogage afin de garder la racine du projet propre.
*   `attestation/` : Dossier de destination des attestations générées (Fichiers PDF et DOCX).
*   `liste adhérent/` : Dossier de destination des fiches de présence générées.
*   `venv/` : L'environnement virtuel Python local.
*   `*.docx` & `*.xlsx` (à la racine) : Fichiers modèles (Templates) utilisés pour la génération (ex: `ATTESTATION DE PAIEMENT_adulte.docx`, `Template Export liste adhérents à imprimer.xlsx`).
*   `*.bat` & Raccourcis : Scripts de lancement pour les utilisateurs finaux sous Windows.

## Scripts Clés
*   `code_source/create_excel.py` : Script central orchestrant l'interface graphique (Tkinter) et la synchronisation des données (téléchargement Drive, appel API HelloAsso, fusion Excel).
*   `code_source/attestation_generator.py` : Générateur d'attestations utilisant `python-docx` et `win32com.client`.
*   `code_source/server.py` : Serveur FastAPI local fournissant des endpoints de Dashboard (`/api/dashboard`) et de gestion du planning.
*   `code_source/email_sender.py` : Module d'envoi d'e-mails gérant l'authentification OAuth2 (Gmail) ou SMTP classique.

## Exécution et Environnement
Le projet est conçu exclusivement pour un environnement **Windows** disposant de la suite **Microsoft Office** installée, car il repose sur `win32com.client` (`pywin32`) pour piloter Word et Excel de manière programmatique.

1.  **Installation :** Lancer `code_source/install.bat` pour créer le `venv` et installer les dépendances (ou exécuter `pip install -r code_source/requirements.txt` manuellement).
2.  **Lancement de l'interface utilisateur :** Exécuter `code_source/run_pipeline.bat` ou le raccourci `Lancer le Pipeline d'Adhésion.lnk` situé à la racine. Cela lance le menu principal interactif en Python.
3.  **Lancement du serveur API de Dashboard :** Exécuter `python code_source/server.py` (par défaut sur le port `8000`).

## Conventions de Développement et Règles de Sécurité
*   **Sécurité des Identifiants :** Le fichier `code_source/.env` contient des secrets critiques (Tokens HelloAsso, Google OAuth2, SMTP). **Ne jamais le versionner ou l'afficher dans les logs.**
*   **Manipulation Office (COM) :** Lors de modifications impliquant `win32com`, toujours s'assurer que les instances d'application (ex: `word_app.Quit()`, `excel_app.Quit()`) sont proprement fermées dans les blocs `finally` ou via la gestion d'erreurs pour éviter de laisser des processus fantômes en arrière-plan.
*   **Formats de Fichiers :** L'export FFME requiert un CSV strict (séparateur `;`, encodage spécifique, format de date `jj/mm/aaaa`). Toute modification sur la génération de ce fichier (`generate_ffme_csv`) doit respecter le cahier des charges de la fédération.
*   **Fichiers et Scripts Temporaires (Diagnostic / Débogage) :** Tous les scripts de diagnostic temporaires, analyses ad-hoc, requêtes ponctuelles (par exemple les scripts préfixés par `check_` ou `query_`), ou fichiers de test jetables doivent impérativement être placés dans le dossier `scripts_temporaires/` situé à la racine du projet afin de maintenir un espace de travail propre et ordonné. Aucun fichier temporaire ou script de test "one-shot" ne doit être créé ou laissé directement à la racine ou dans le dossier du code source.
