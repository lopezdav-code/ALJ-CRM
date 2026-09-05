# 🗺️ Cartographie de l'Architecture Actuelle
> **Analyse technique et fonctionnelle de l'application ALJ Escalade**

Ce document présente une analyse détaillée de l'architecture actuelle du projet de gestion administrative pour la section escalade de l'Amicale Laïque de Jonage (ALJ). Il a été rédigé par un architecte logiciel senior pour servir de base solide avant toute opération de migration ou de refactorisation.

---

## 1. Cartographie des Modules Actuels

L'application est structurée à plat sous le répertoire `code_source/src/` (les fichiers sources Python ont été récemment regroupés dans `src/` pour séparer le code de la configuration racine).

Voici le rôle et les responsabilités de chaque composant de l'application :

| Module | Rôle principal | Dépendances directes | Complexité / Qualité |
| :--- | :--- | :--- | :--- |
| **`create_excel.py`** | **Master Coordonnateur & UI** : Gère l'interface Tkinter principale, les boîtes de dialogue de configuration, le rapprochement HelloAsso/Excel, les exports et le dessin des statistiques. | `tkinter`, `openpyxl`, `win32com.client`, `helloasso_api`, `email_sender`, `presence_sheet_generator`, `urgency_contact_generator`, `server` | **Très élevée (~3500 lignes)**. Monolithique. Mélange de logique de présentation (UI), logique métier (pipeline de rapprochement) et logique de persistence (Excel, Drive). |
| **`helloasso_api.py`** | **Client HelloAsso** : Gère l'authentification et l'interrogation de l'API REST v5 HelloAsso, y compris la pagination par jeton de continuation. | `requests`, `python-dotenv` | **Basse**. Code propre et ciblé. |
| **`email_sender.py`** | **Service d'Envoi d'E-mails** : Envoie des messages MIME individuels/lots avec pièces jointes en SMTP (SSL/TLS) ou via l'API Gmail REST (OAuth2). | `smtplib`, `requests`, `urllib`, `email` | **Moyenne**. Bonne séparation, mais contient de la logique OAuth2 imbriquée. |
| **`gmail_auth_helper.py`** | **Assistant d'Authentification** : Lance un serveur local (port 8080) pour capturer le code d'autorisation OAuth2 de Google et enregistrer le `refresh_token` dans le `.env`. | `http.server`, `webbrowser`, `urllib` | **Moyenne**. Technique et ciblé. |
| **`fill_presence_cours.py`**| **Remplissage de "Cours.xlsx"** : Gère la synchronisation de la grille d'activité et fournit les utilitaires de normalisation sémantique des adhérents. | `openpyxl`, `pandas` | **Élevée (~560 lignes)**. Contient des fonctions d'audit sémantique lourdes et la fonction critique de normalisation des chaînes de caractères. |
| **`presence_sheet_generator.py`** | **Générateur de Fiches de Présence** : Crée les feuilles Excel de présence hebdomadaires par groupe en utilisant `planning.json` et un tableur de modèle. | `openpyxl`, `json` | **Basse-Moyenne (~590 lignes)**. Logique d'écriture Excel ciblée. |
| **`urgency_contact_generator.py`** | **Fiches d'Urgence** : Extrait et met en page les fiches de contacts d'urgence A4 pour les groupes actifs. | `openpyxl` | **Basse (~220 lignes)**. Code ciblé d'écriture Excel. |
| **`attestation_generator.py`** | **Générateur d'Attestations** : Fusionne les informations d'adhésion dans un document Word et s'interface avec MS Word via COM pour l'export PDF. | `python-docx`, `win32com.client` | **Moyenne (~275 lignes)**. Gère l'automation Windows COM pour MS Word. |
| **`server.py`** | **Serveur Backend local** : Expose les données d'adhésion consolidées via FastAPI pour d'éventuels dashboards locaux. | `fastapi`, `uvicorn`, `helloasso_api` | **Basse (~180 lignes)**. Simple serveur d'API local. |
| **`paths.py`** | **Résolution de chemins** : Abstraction permettant de résoudre dynamiquement `CODE_ROOT` et `ROOT_DIR`. | `os` | **Basse**. Très propre. |

---

## 2. Dépendances Externes du Projet

Le projet s'appuie sur plusieurs packages externes listés dans `requirements.txt` :

1.  **Manipulation de documents** :
    *   `openpyxl` : Lecture et écriture de fichiers Excel de manière native (très performant).
    *   `pandas` : Utilisé dans `fill_presence_cours.py` pour manipuler les structures de données tabulaires.
    *   `python-docx` : Lecture et écriture native des documents Word (`.docx`).
2.  **Automation Windows COM (Office)** :
    *   `pywin32` (`win32com.client`) : Nécessaire pour piloter Microsoft Word et Excel directement sur la machine Windows pour l'export PDF et certaines opérations Excel.
3.  **Communication & Web** :
    *   `requests` : Client HTTP pour communiquer avec HelloAsso et Google.
    *   `fastapi` & `uvicorn` : Framework web pour le dashboard d'API local.
4.  **Utilitaires de données** :
    *   `python-dotenv` : Chargement des fichiers de configuration `.env`.
    *   `geopy` : Géocodage de l'adresse des adhérents pour les statistiques géographiques.
    *   `pillow` (PIL) : Traitement d'images pour le positionnement de logos.

---

## 3. Risques Techniques Identifiés

En analysant la base de code, plusieurs risques majeurs pour la stabilité, la sécurité et la maintenabilité ont été identifiés :

### 🚨 Risque 1 : Opérations bloquantes dans le thread principal (UI Freeze)
Toutes les opérations d'envergure — la synchronisation HelloAsso (requêtes HTTP paginées), les téléchargements/versements Google Drive, l'envoi d'e-mails par lots, la compilation d'attestations via Word COM — s'exécutent de manière synchrone dans le même thread que l'interface graphique Tkinter. 
*   **Conséquence** : L'interface Windows freeze ("Ne répond pas"), ce qui dégrade fortement l'expérience utilisateur et peut amener l'utilisateur à forcer l'arrêt de l'application en plein traitement.

### 🚨 Risque 2 : Saisons et configurations d'années codées en dur
De nombreuses fonctions font référence à des configurations temporelles figées, par exemple `2026-2027` ou `Adhésions escalade-2026-2027-...`.
*   **Conséquence** : Chaque changement de saison nécessite l'intervention d'un développeur pour modifier le code source, ce qui est contraire aux bonnes pratiques de l'ingénierie logicielle.

### 🚨 Risque 3 : Automation COM (`win32com.client`) non robuste et dépendante d'Office
L'export PDF des attestations s'appuie sur le pilotage en tâche de fond de MS Word.
*   **Conséquence** : Si l'utilisateur n'a pas MS Word installé localement sous Windows, ou si une exception survient pendant le traitement sans appeler `.Quit()`, des processus Word fantômes (`WINWORD.EXE`) restent actifs en mémoire, verrouillant les fichiers de manière permanente.

### 🚨 Risque 4 : Absence de modèle de données structuré (Modèle MVC/MVVM absent)
L'application ne possède pas de classes de modèles représentant un "Adhérent" (`Member`), un "Paiement" (`Payment`), ou un "Cours" (`Course`). Les données sont transportées sous forme de dictionnaires JSON bruts non typés (`p.get("user_firstName")`), multipliant les risques de fautes de frappe (`KeyError`) et de régressions lors des refactorisations.

### 🚨 Risque 5 : Sécurité et gestion des secrets
Les variables d'environnement sensibles comme `HELLOASSO_CLIENT_SECRET` ou `SMTP_PASSWORD` sont lues et écrites directement en clair dans le fichier `.env`. De plus, Tkinter affiche ces secrets en clair dans les fenêtres d'options si l'utilisateur ouvre les paramètres devant des tiers.

---

## 4. Fonctionnalités Métier Identifiées

1.  **Synchronisation de Base de Données (HelloAsso <=> Excel local <=> Google Drive)** :
    *   Téléchargement transparent de la feuille d'adhésion de référence depuis Google Drive.
    *   Récupération des adhésions depuis HelloAsso et fusion intelligente avec les correctifs manuels de l'association.
    *   Réimport/Upload automatique du fichier consolidé sur Google Drive.
2.  **Traitement des montants et des adhésions** :
    *   Calcul de l'âge de l'adhérent pour valider le tarif appliqué (Adulte vs Enfant/Jeune).
    *   Extraction des options d'assurance (Base, Base +, Base ++, ski, VTT, trail).
3.  **Génération documentaire** :
    *   Génération de reçus fiscaux et d'attestations nominatives au format `.docx` et compilation en `.pdf`.
4.  **Gestion de la présence et de la logistique d'activité** :
    *   Rapprochement et alimentation du fichier `Cours.xlsx` contenant les 19 créneaux horaires.
    *   Génération de fiches de présence à imprimer avec quadrillage Excel activé pour les émulations de cours.
    *   Fiche récapitulative unifiée des contacts d'urgence au format A4 vertical pour la sécurité des encadrants.
5.  **Communications ciblées** :
    *   Envoi automatisé des attestations par e-mail via l'API Gmail ou via un serveur SMTP avec possibilité d'enregistrer la date d'envoi dans le tableur central.

---

## 5. Éléments Non Vérifiables Faute de Fichiers

Certains éléments référencés dans le code d'origine pointent vers des ressources locales situées en dehors du périmètre immédiat du dossier de code source :
*   **Fichiers modèles et d'accompagnement** :
    *   `doc/template/Template Export liste adhérents à imprimer.xlsx` (modèle des fiches de présence).
    *   `planning.json` et `tarif_mapping.json` (attendus dans le dossier parent).
    *   `doc/template/ATTESTATION DE PAIEMENT_adulte.docx` (modèle d'attestation).
    *   `exports/liste adhérent/Cours.xlsx` (sorties du remplissage des cours).
*   **Ressources visuelles** :
    *   `logo.png` (recherché pour agrémenter les feuilles de présence d'un entête visuel).

*Note d'architecture : L'utilisation de notre utilitaire `paths.py` résout parfaitement la localisation de ces dépendances physiques en pointant dynamiquement vers le dossier parent `Import Export Script` sans nécessiter leur déplacement dans la structure du dépôt de code.*
