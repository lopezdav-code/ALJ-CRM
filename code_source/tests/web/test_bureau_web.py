"""
Tests du portail « bureau » (ordinateur) et de son socle web/shared/ :
- routes publiques (pages) sans données, ressources communes servies ;
- numéro de version identique (pages, service worker, pages PWA) ;
- redirection ordinateur -> /bureau/ (script alj-vue.js) ;
- rôles du socle identiques à l'API et à firestore.rules.
"""

import os
import re
import sys
import unittest
from unittest.mock import patch

_tests_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_code_root = os.path.dirname(_tests_dir)
_src_dir = os.path.join(_code_root, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from fastapi.testclient import TestClient

from infrastructure import api_auth
from server import (
    app, get_bureau_home, get_bureau_page, get_competitions_page, get_annuaire_page,
    get_sw, get_web_version,
)

WEB = os.path.join(_code_root, "web")
BUREAU = os.path.join(WEB, "bureau")
SHARED = os.path.join(WEB, "shared")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _current_version():
    return get_web_version()["web_version"]


class TestBureauFiles(unittest.TestCase):

    def test_pages_exist(self):
        for name in ("index.html", "adherents.html", "outils.html"):
            self.assertTrue(os.path.exists(os.path.join(BUREAU, name)), name)
        for name in ("alj.css", "alj-core.js", "alj-shell.js", "alj-vue.js",
                      "alj-members.js", "alj-filters.js"):
            self.assertTrue(os.path.exists(os.path.join(SHARED, name)), name)

    def test_routes_serve_only_known_pages(self):
        self.assertEqual(get_bureau_home().status_code, 200)
        self.assertEqual(get_bureau_page("adherents").status_code, 200)
        self.assertEqual(get_bureau_page("outils").status_code, 200)
        self.assertEqual(get_bureau_page("index.html").status_code, 404)
        self.assertEqual(get_bureau_page("..%2Fserver.py").status_code, 404)
        self.assertEqual(get_bureau_page("inconnue").status_code, 404)

    def test_pages_are_static_shells_without_member_data(self):
        """Les pages n'embarquent aucune donnée : elles chargent le socle et lisent Firestore après connexion."""
        for name in ("index.html", "adherents.html", "outils.html"):
            html = _read(os.path.join(BUREAU, name))
            self.assertIn('href="/static-web/alj.css"', html, name)
            self.assertIn('import { startBureau } from "/static-web/alj-shell.js"', html, name)
            self.assertIn("firebase-firestore-compat.js", html, name)
            self.assertNotIn("crm_users", html, name)
            self.assertNotIn("crm_orders", html, name)

    def test_bureau_pages_share_web_version(self):
        version = _current_version()
        self.assertRegex(version, r"^\d+$")
        for name in ("index.html", "adherents.html", "communications.html", "competitions.html", "planning.html", "outils.html", "parametres.html"):
            html = _read(os.path.join(BUREAU, name))
            self.assertIn(f'<meta name="alj-web-version" content="{version}">', html, name)
            self.assertRegex(html, rf"<title>[^<]*\(v{version}\)</title>", name)

    def test_service_worker_precaches_portal(self):
        sw = _read(get_sw().path)
        version = _current_version()
        self.assertIn(f'CACHE_NAME = "alj-escalade-v{version}"', sw)
        for asset in ("/bureau/", "/bureau/adherents", "/bureau/communications", "/bureau/competitions", "/bureau/planning", "/bureau/outils", "/bureau/parametres",
                      "/static-web/alj.css", "/static-web/alj-core.js",
                      "/static-web/alj-shell.js", "/static-web/alj-vue.js",
                      "/static-web/alj-members.js", "/static-web/alj-filters.js"):
            self.assertIn(f'"{asset}"', sw)

    def test_planning_file_structure(self):
        """La nouvelle page planning.html doit contenir la grille visuelle, le tableau, la modale et les exports."""
        html = _read(os.path.join(BUREAU, "planning.html"))
        self.assertIn("alj-shell.js", html)
        self.assertIn("pane-visual", html)
        self.assertIn("pane-table", html)
        self.assertIn("btn-create-slot", html)
        self.assertIn("btn-print-grid", html)
        self.assertIn("btn-export-excel-grid", html)
        self.assertIn("slot-modal", html)

    def test_parametres_file_structure(self):
        """La nouvelle page parametres.html doit contenir l'outil de connexion Google, la gestion SQLite et le batch résultats."""
        html = _read(os.path.join(BUREAU, "parametres.html"))
        self.assertIn("alj-shell.js", html)
        self.assertIn("alj-firebase.js", html)
        self.assertIn("google-status-badge", html)
        self.assertIn("btn-google-reconnect", html)
        self.assertIn("btn-google-test", html)
        self.assertIn("btn-force-update-sqlite", html)
        self.assertIn("btn-full-rebuild-sqlite", html)
        self.assertIn("sqlite-status-badge", html)
        self.assertIn("sqlite-file-info", html)
        # Nouveaux éléments du batch de résultats MyCompet
        self.assertIn("results-notif-email", html)
        self.assertIn("btn-save-notif-email", html)
        self.assertIn("btn-run-results-batch", html)
        self.assertIn("results-batch-last-run", html)
        self.assertIn("results-batch-report", html)
        self.assertIn("Suivi Automatique des Résultats MyCompet", html)

    def test_competitions_results_cron_and_settings_endpoints(self):
        """Vérifie les endpoints de configuration et de cron du batch des résultats MyCompet."""
        from server import (
            app,
            get_competitions_results_settings_api,
            update_competitions_results_settings_api,
            api_cron_fetch_competition_results
        )

        # 1. GET /api/settings/competitions-results
        res = get_competitions_results_settings_api()
        self.assertEqual(res.get("status"), "success")
        self.assertIn("notification_email", res)
        self.assertIn("@", res["notification_email"])
        self.assertIn("cron_schedule", res)

        # 2. POST /api/settings/competitions-results
        up_res = update_competitions_results_settings_api({"notification_email": "test.notif@alj-jonage.fr"})
        self.assertEqual(up_res.get("status"), "success")
        self.assertEqual(up_res.get("notification_email"), "test.notif@alj-jonage.fr")

        # Rétablir l'adresse par défaut
        update_competitions_results_settings_api({"notification_email": "david.lopez@alj-jonage.fr"})

        # 3. POST /api/competitions/cron/fetch-results
        with patch("infrastructure.competition_results_batch_service.CompetitionResultsBatchService.run_daily_batch") as mock_batch:
            mock_batch.return_value = {
                "status": "success",
                "competitions_checked": 0,
                "competitions_updated": 0,
                "email_sent": False
            }
            client = TestClient(app)
            cron_resp = client.post("/api/competitions/cron/fetch-results?force=true")
            self.assertEqual(cron_resp.status_code, 200)
            self.assertEqual(cron_resp.json().get("status"), "success")
            mock_batch.assert_called_once()

    def test_cloud_db_status_endpoint(self):
        """Vérifie l'endpoint GET /api/cloud-db/status."""
        from server import get_cloud_db_status_api
        res = get_cloud_db_status_api()
        self.assertEqual(res.get("status"), "success")
        self.assertIn("db_exists", res)
        self.assertIn("pending", res)

    def test_outils_no_longer_has_google_reconnect(self):
        """L'onglet Google a été déplacé vers parametres.html : outils contient map, pivot, fiches de présence et FFME."""
        html = _read(os.path.join(BUREAU, "outils.html"))
        self.assertNotIn("btn-google-reconnect", html)
        self.assertIn("pane-map", html)
        self.assertIn("pane-pivot", html)
        self.assertIn("pane-presence", html)
        self.assertIn("pane-ffme", html)
        self.assertIn("btn-download-autonome", html)
        self.assertIn("btn-download-cours", html)
        self.assertIn("btn-download-ffme", html)

    def test_ffme_api_stats_and_export(self):
        """Vérifie le calcul des statistiques et le téléchargement du fichier CSV FFME."""
        import shutil
        import tempfile
        from infrastructure.sqlite_repository import SqliteRepository
        from server import get_ffme_stats_api, export_ffme_api

        # Seeded temporary database: never read data/database.db (absent in CI, personal data locally).
        original_db_path = SqliteRepository.get_db_path()
        tmpdir = tempfile.mkdtemp(prefix="alj_ffme_test_")
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)
        self.addCleanup(SqliteRepository.set_db_path, original_db_path)
        SqliteRepository.set_db_path(os.path.join(tmpdir, "database.db"))
        SqliteRepository.setup_database()
        SqliteRepository.upsert_members([{
            "order_ref": "ORD-1",
            "order_date": "2026-08-20T10:00:00",
            "status": "Validated",
            "tarif_name": "Adultes autonomes",
            "amount": 150.0,
            "user_lastName": "MARTIN",
            "user_firstName": "Leo",
            "payer_email": "leo.martin@test.fr",
            "champ_Date de naissance de l'adhérent": "1990-05-15",
            "champ_Sexe": "M",
            "champ_Adresse : numéro et nom de rue": "10 Rue des Fleurs",
            "champ_Code postal": "69000",
            "champ_Ville": "Lyon",
            "champ_Téléphone ": "0612345678",
        }], "2026-2027")

        # 1. Statistiques
        stats = get_ffme_stats_api("2026-2027")
        self.assertEqual(stats.get("status"), "success")
        self.assertIn("estimated_total", stats)
        self.assertIn("renewals_count", stats)
        self.assertIn("new_licences_count", stats)

        # 2. Export CSV avec include_termine=True
        resp = export_ffme_api(season="2026-2027", include_termine=True)
        self.assertEqual(resp.headers.get("content-type"), "text/csv; charset=utf-8")
        self.assertIn("attachment", resp.headers.get("content-disposition", ""))
        csv_text = resp.body.decode("utf-8")
        self.assertIn("numero de licence;nom;prenom", csv_text)
        self.assertIn("MARTIN", csv_text)

    def test_pivot_table_configuration_and_fields(self):
        """Vérifie la présence du filtre Âge, des colonnes Statut & Sexe, et de l'exclusion par défaut d'Annulé."""
        from server import get_pivot_table
        resp = get_pivot_table(season="2026-2027")
        self.assertEqual(resp.status_code, 200)
        html = resp.body.decode("utf-8")

        # 1. Vérification de la configuration PivotTable.js
        self.assertIn('"Statut", "Sexe"', html)
        self.assertIn('"Statut": ["Annulé"]', html)
        self.assertIn('"Groupe / Tarif": ["Liste d\'attente cours"]', html)

        # 2. Vérification des attributs dans les données
        self.assertIn('"Âge"', html)
        self.assertIn('"Tranche d\'Âge"', html)
        self.assertIn('"Sexe"', html)
        self.assertIn('"Statut"', html)

    def test_adherents_page_imports_exist_in_modules(self):
        """Chaque symbole importé par adherents.html doit être exporté par alj-members.js et alj-filters.js."""
        html = _read(os.path.join(BUREAU, "adherents.html"))
        members_js = _read(os.path.join(SHARED, "alj-members.js"))
        filters_js = _read(os.path.join(SHARED, "alj-filters.js"))

        m_block = re.search(r"import\s*\{([^}]+)\}\s*from\s*\"/static-web/alj-members\.js\"", html, re.S).group(1)
        for sym in [s.strip() for s in m_block.split(",") if s.strip()]:
            self.assertRegex(members_js, rf"export (function|const|async function) {sym}\b", sym)

        f_block = re.search(r"import\s*\{([^}]+)\}\s*from\s*\"/static-web/alj-filters\.js\"", html, re.S).group(1)
        for sym in [s.strip() for s in f_block.split(",") if s.strip()]:
            self.assertRegex(filters_js, rf"export (function|const|async function) {sym}\b", sym)

    def test_adherents_formatters_names_city_phone(self):
        """Vérifie l'harmonisation d'affichage pour les noms, prénoms, villes et téléphones."""
        members_js = _read(os.path.join(SHARED, "alj-members.js"))
        html = _read(os.path.join(BUREAU, "adherents.html"))

        # Vérification des exports et imports
        for fn in ("fmtLastName", "fmtFirstName", "fmtCity", "fmtPhone"):
            self.assertIn(f"export function {fn}", members_js)
            self.assertIn(fn, html)

        # Vérification du regex / logique de téléphone
        self.assertIn("replace(/(\\d{2})(?=\\d)/g, \"$1 \")", members_js)

    def test_adherents_page_elements(self):
        """La page adherents.html contient le tableau, les filtres et le panneau de détail."""
        html = _read(os.path.join(BUREAU, "adherents.html"))
        members_js = _read(os.path.join(SHARED, "alj-members.js"))
        filters_js = _read(os.path.join(SHARED, "alj-filters.js"))
        for elem in ("members-table", "members-tbody", "detail-pane", "search-input",
                      "season-select", "export-csv-btn", "status-chips", "filter-box"):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn("Attestation envoyée", html)
        self.assertIn("email_sent_date", members_js)
        self.assertIn('data-sort="order_date"', html)
        self.assertIn("Date d'inscription", html)
        self.assertIn("order_date", filters_js)

    def test_adherents_columns_diplome_and_city(self):
        """Vérifie le masquage des colonnes Tarif/Catégorie et l'ajout des colonnes Diplôme et Ville."""
        html = _read(os.path.join(BUREAU, "adherents.html"))
        members_js = _read(os.path.join(SHARED, "alj-members.js"))
        filters_js = _read(os.path.join(SHARED, "alj-filters.js"))

        # 1. Vérification des colonnes du tableau
        thead_match = re.search(r"<table[^>]*id=\"members-table\"[^>]*>.*?<thead>(.*?)</thead>", html, re.S)
        self.assertIsNotNone(thead_match)
        thead = thead_match.group(1)

        # Les colonnes Tarif et Catégorie doivent être masquées (absentes du thead)
        self.assertNotIn('data-sort="tarif_name"', thead)
        self.assertNotIn('data-sort="categorie"', thead)

        # Les nouvelles colonnes Diplôme et Ville doivent être présentes
        self.assertIn('data-sort="diplome"', thead)
        self.assertIn('data-sort="city"', thead)
        self.assertIn("Diplôme", thead)
        self.assertIn("Ville", thead)

        # 2. Pictogrammes / badges attendus
        self.assertIn("🔴", html)  # Badge rouge (rond rouge)
        self.assertIn("🧗", html)  # Autonomie bloc (picto du grimpeur)
        self.assertIn("🟠", html)  # Passeport Orange (rond orange)

        # 3. Helpers et propagation des champs
        self.assertIn("raw_passports", members_js)
        self.assertIn("getMemberDiplomes", members_js)
        self.assertIn("export function getMemberDiplomes", members_js)
        self.assertIn("diplome", filters_js)
        self.assertIn("ville", filters_js)

    def test_adherents_email_modal_and_api_wiring(self):
        """L'Étape 2 intègre la modale d'e-mail et le câblage aux endpoints d'e-mail."""
        html = _read(os.path.join(BUREAU, "adherents.html"))
        for elem in ("email-modal", "em-template-select", "em-subject", "em-body",
                      "em-signature", "em-preview-box", "em-submit-btn", "em-cancel-btn"):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn('apiFetch("/api/email-templates")', html)
        self.assertIn('apiFetch("/api/send-email"', html)

    def test_adherents_attestation_modal_and_api_wiring(self):
        """L'Étape 3 intègre la modale d'attestation, le choix du template d'e-mail et le câblage aux endpoints PDF."""
        html = _read(os.path.join(BUREAU, "adherents.html"))
        for elem in ("attestation-modal", "att-download-btn", "att-send-btn", "att-pdf-frame",
                      "att-preview-loading", "att-ineligible-warn", "att-template-select",
                      "att-to-email", "att-email-subject", "att-email-body", "att-email-signature"):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn('apiFetch("/api/attestations/preview"', html)
        self.assertIn('apiFetch("/api/attestations/send"', html)
        self.assertIn("Attestation échéance", html)

    def test_build_attestation_pure_function_rules(self):
        """build_attestation respecte les règles de montant, d'annulation, de signature et de payeur."""
        from domain.attestation import build_attestation, get_safe_pdf_filename, render_attestation_pdf

        # 1. Validation montant manquant ou nul
        with self.assertRaises(ValueError):
            build_attestation({"first_name": "Jean", "last_name": "Dupont", "amount": 0})
        with self.assertRaises(ValueError):
            build_attestation({"first_name": "Jean", "last_name": "Dupont", "amount": -10})

        # 2. Validation commande annulée
        with self.assertRaises(ValueError):
            build_attestation({"first_name": "Jean", "last_name": "Dupont", "amount": 150, "status": "Annulé"})

        # 3. Payeur par défaut = adhérent
        m = {"first_name": "alex", "last_name": "martin", "amount": 195, "season_name": "2026-2027"}
        html = build_attestation(m, season="2026-2027", date_jour="14 juillet 2026")
        self.assertIn("MARTIN", html)
        self.assertIn("Alex", html)
        self.assertIn("195,00", html)
        self.assertIn("14 juillet 2026", html)
        self.assertIn("2026-2027", html)

        # 4. Signature & tampon garantis en base64 dans le HTML
        self.assertIn("data:image/jpeg;base64,", html)

        # 5. Rendu PDF valide
        pdf_bytes = render_attestation_pdf(html)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 300)

        # 6. Nom de fichier sécurisé
        fn = get_safe_pdf_filename(m["last_name"], m["first_name"], "CMD-99")
        self.assertEqual(fn, "Attestation_MARTIN_Alex_CMD-99.pdf")

    def test_attestation_endpoints_require_admin_role(self):
        """Les endpoints /api/attestations exigent le rôle admin."""
        from infrastructure.api_auth import required_role
        self.assertEqual(required_role("POST", "/api/attestations/preview"), "admin")
        self.assertEqual(required_role("POST", "/api/attestations/send"), "admin")

    def test_send_attestation_records_email_sent_date(self):
        """send_attestation_api enregistre la date d'envoi dans SQLite et utilise le modèle par défaut."""
        import tempfile
        import shutil
        from infrastructure.sqlite_repository import SqliteRepository
        from server import send_attestation_api

        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_attestation.db")
        orig_db_path = SqliteRepository.get_db_path()
        try:
            SqliteRepository.set_db_path(db_path)
            SqliteRepository.setup_database()
            conn = SqliteRepository.get_connection()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO seasons (id, name, is_active) VALUES (1, '2026-2027', 1)")
            c.execute("""
                INSERT INTO users (id, last_name, first_name, last_name_key, first_name_key, email_primary, birth_date)
                VALUES (10, 'DUPONT', 'Jean', 'dupont', 'jean', 'jean.dupont@example.com', '1990-01-01')
            """)
            c.execute("""
                INSERT INTO orders (id, season_id, order_ref, order_date, payer_first_name, payer_last_name, payer_email)
                VALUES (20, 1, 'CMD-TEST-ATT', '2026-09-15', 'Jean', 'Dupont', 'jean.dupont@example.com')
            """)
            c.execute("""
                INSERT INTO purchases (id, order_id, user_id, tarif_name, amount, status)
                VALUES (30, 20, 10, 'Adulte', 180.0, 'Payé')
            """)
            conn.commit()
            conn.close()

            payload = {
                "member": {
                    "user_id": 10,
                    "purchase_id": 30,
                    "first_name": "Jean",
                    "last_name": "DUPONT",
                    "email_primary": "jean.dupont@example.com",
                    "order_ref": "CMD-TEST-ATT",
                    "amount": 180.0,
                    "status": "Payé"
                },
                "season": "2026-2027"
            }

            with patch("infrastructure.email_repository.EmailRepository.send_email", return_value=True) as mock_send:
                res = send_attestation_api(payload)

            self.assertEqual(res.get("status"), "success")
            self.assertTrue(res.get("email_sent_date"))

            # Vérifier les paramètres de l'envoi d'e-mail (conforme desktop)
            mock_send.assert_called_once()
            _, kwargs = mock_send.call_args
            self.assertEqual(kwargs.get("from_email"), "inscription@alj-escalade.fr")
            self.assertEqual(kwargs.get("from_name"), "Amicale Laïque Jonage - Inscriptions")
            self.assertIn("Attestation de paiement", kwargs.get("subject", ""))
            self.assertIsNotNone(kwargs.get("html_body"))
            self.assertIn("Amicale Laïque", kwargs.get("html_body", ""))

            # Vérifier que la date est enregistrée en base SQLite
            conn = SqliteRepository.get_connection()
            row = conn.execute("SELECT email_sent_date FROM purchases WHERE id = 30").fetchone()
            conn.close()
            self.assertIsNotNone(row["email_sent_date"])
            self.assertEqual(row["email_sent_date"], res["email_sent_date"])
        finally:
            SqliteRepository.set_db_path(orig_db_path)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_member_edit_ui_elements(self):
        """La page adherents.html contient le bouton Modifier et la modale d'édition complète."""
        html = _read(os.path.join(BUREAU, "adherents.html"))
        for elem in ("btn-action-edit", "member-edit-modal", "edit-modal-close", "edit-cancel-btn",
                      "edit-save-btn", "edit-licence", "edit-badge-rouge", "edit-autonomie-bloc",
                      "edit-tarifs-container", "edit-email-primary", "edit-email-secondary", "edit-phone",
                      "edit-address", "edit-zip", "edit-city",
                      "edit-commentaire", "btn-insert-comment-date"):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn('apiFetch("/api/members/update"', html)

    def test_member_add_ui_elements(self):
        """La page adherents.html contient le bouton d'ajout et la modale complète d'ajout manuel."""
        html = _read(os.path.join(BUREAU, "adherents.html"))
        for elem in (
            "btn-add-member", "member-add-modal", "add-modal-close", "add-cancel-btn",
            "add-save-btn", "add-last-name", "add-first-name", "add-birth-date",
            "add-gender", "add-tarifs-container", "add-status", "add-amount",
            "add-licence", "add-badge-rouge", "add-autonomie-bloc",
            "add-email-primary", "add-email-secondary", "add-phone",
            "add-address", "add-zip", "add-city", "add-emergency-name",
            "add-emergency-phone", "add-commentaire", "btn-insert-add-comment-date"
        ):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn('apiFetch("/api/members/create"', html)

    def test_member_add_requires_admin_role(self):
        """Les endpoints de création manuelle d'adhérents exigent le rôle admin."""
        from infrastructure.api_auth import required_role
        self.assertEqual(required_role("POST", "/api/members/create"), "admin")
        self.assertEqual(required_role("POST", "/api/members/add"), "admin")

    def test_member_add_endpoint_and_sqlite_persistence(self):
        """add_member_api persiste le nouvel adhérent, la commande et l'achat dans SQLite."""
        import tempfile
        import shutil
        from infrastructure.sqlite_repository import SqliteRepository
        from server import add_member_api

        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_member_add.db")
        orig_db_path = SqliteRepository.get_db_path()
        try:
            SqliteRepository.set_db_path(db_path)
            SqliteRepository.setup_database()
            conn = SqliteRepository.get_connection()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO seasons (id, name, is_active) VALUES (1, '2026-2027', 1)")
            conn.commit()
            conn.close()

            payload = {
                "season": "2026-2027",
                "fields": {
                    "last_name": "VALENTIN",
                    "first_name": "Claire",
                    "birth_date": "2010-05-14",
                    "gender": "Femme",
                    "tarif_name": "Cours Ados 1 (Lundi)",
                    "status": "Validé",
                    "amount": 195.0,
                    "licence_ffme": "654321",
                    "badge_rouge": "Oui",
                    "autonomie_bloc": "Oui",
                    "email_primary": "claire.valentin@example.com",
                    "email_secondary": "parents.valentin@example.com",
                    "phone": "06 11 22 33 44",
                    "address": "15 rue des Alpes",
                    "zip_code": "69330",
                    "city": "Jonage",
                    "emergency1_name": "VALENTIN Marc",
                    "emergency1_phone": "06 99 88 77 66",
                    "commentaires_correctif": "Inscription manuelle web bureau"
                }
            }

            res = add_member_api(payload)
            self.assertEqual(res.get("status"), "success")
            self.assertTrue(res.get("order_ref", "").startswith("MANUEL-"))

            # Vérification dans SQLite
            conn = SqliteRepository.get_connection()
            u = conn.execute("SELECT * FROM users WHERE last_name = 'VALENTIN'").fetchone()
            self.assertIsNotNone(u)
            self.assertEqual(u["first_name"], "Claire")
            self.assertEqual(u["birth_date"], "2010-05-14")
            self.assertEqual(u["gender"], "Femme")
            self.assertEqual(u["licence_ffme"], "654321")
            self.assertEqual(u["badge_rouge"], "Oui")
            self.assertEqual(u["autonomie_bloc"], "Oui")
            self.assertEqual(u["email_primary"], "claire.valentin@example.com")
            self.assertEqual(u["email_secondary"], "parents.valentin@example.com")
            self.assertEqual(u["phone"], "06 11 22 33 44")
            self.assertEqual(u["address"], "15 rue des Alpes")
            self.assertEqual(u["zip_code"], "69330")
            self.assertEqual(u["city"], "Jonage")
            self.assertEqual(u["emergency1_name"], "VALENTIN Marc")
            self.assertEqual(u["emergency1_phone"], "06 99 88 77 66")

            p = conn.execute("SELECT * FROM purchases WHERE user_id = ?", (u["id"],)).fetchone()
            self.assertIsNotNone(p)
            self.assertEqual(p["tarif_name"], "Cours Ados 1 (Lundi)")
            self.assertEqual(float(p["amount"]), 195.0)
            self.assertEqual(p["status_normalized"], "Validé")
            self.assertEqual(p["commentaires_correctif"], "Inscription manuelle web bureau")

            o = conn.execute("SELECT * FROM orders WHERE id = ?", (p["order_id"],)).fetchone()
            self.assertIsNotNone(o)
            self.assertEqual(o["order_ref"], res["order_ref"])
            self.assertEqual(o["payer_email"], "claire.valentin@example.com")
            conn.close()
        finally:
            SqliteRepository.set_db_path(orig_db_path)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_member_add_validation(self):
        """add_member_api rejette les requêtes avec champs obligatoires manquants."""
        from server import add_member_api

        # Nom manquant
        res = add_member_api({"fields": {"first_name": "Jean", "birth_date": "2000-01-01", "tarif_name": "Licence"}})
        self.assertEqual(res.status_code, 400)

        # Date de naissance manquante
        res = add_member_api({"fields": {"last_name": "DUPONT", "first_name": "Jean", "tarif_name": "Licence"}})
        self.assertEqual(res.status_code, 400)

        # Tarif manquant
        res = add_member_api({"fields": {"last_name": "DUPONT", "first_name": "Jean", "birth_date": "2000-01-01"}})
        self.assertEqual(res.status_code, 400)

    def test_member_update_requires_admin_role(self):
        """L'endpoint /api/members/update exige le rôle admin."""
        from infrastructure.api_auth import required_role
        self.assertEqual(required_role("POST", "/api/members/update"), "admin")

    def test_member_update_endpoint_and_sqlite_persistence(self):
        """update_member_api persiste les badges, emails, téléphone et créneau dans SQLite."""
        import tempfile
        import shutil
        from infrastructure.sqlite_repository import SqliteRepository
        from server import update_member_api

        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_member_edit.db")
        orig_db_path = SqliteRepository.get_db_path()
        try:
            SqliteRepository.set_db_path(db_path)
            SqliteRepository.setup_database()
            conn = SqliteRepository.get_connection()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO seasons (id, name, is_active) VALUES (1, '2026-2027', 1)")
            c.execute("""
                INSERT INTO users (id, last_name, first_name, last_name_key, first_name_key, email_primary, email_secondary, phone, badge_rouge, autonomie_bloc)
                VALUES (50, 'BERNARD', 'Luc', 'bernard', 'luc', 'luc@old.fr', '', '0600000000', 'Non', 'Non')
            """)
            c.execute("""
                INSERT INTO orders (id, season_id, order_ref)
                VALUES (60, 1, 'CMD-BERNARD-1')
            """)
            c.execute("""
                INSERT INTO purchases (id, order_id, user_id, tarif_name, amount, status)
                VALUES (70, 60, 50, 'Séance autonome', 130.0, 'Payé')
            """)
            conn.commit()
            conn.close()

            payload = {
                "user_id": 50,
                "purchase_id": 70,
                "order_ref": "CMD-BERNARD-1",
                "fields": {
                    "licence_ffme": "778899",
                    "address": "12 chemin du Moulin",
                    "zip_code": "69330",
                    "city": "Jonage",
                    "badge_rouge": "Oui",
                    "autonomie_bloc": "Oui",
                    "email_primary": "luc.bernard@nouveau.fr",
                    "email_secondary": "parent.luc@example.com",
                    "phone": "06 99 88 77 66",
                    "tarif_name": "Cours Ados 1 (Lundi)",
                    "status": "Annulé",
                    "commentaires_correctif": "Certificat médical papier fourni en main propre le 14/10."
                }
            }

            res = update_member_api(payload)
            self.assertEqual(res.get("status"), "success")

            # Vérification dans la table users
            conn = SqliteRepository.get_connection()
            u = conn.execute("SELECT * FROM users WHERE id = 50").fetchone()
            self.assertEqual(u["licence_ffme"], "778899")
            self.assertEqual(u["address"], "12 chemin du Moulin")
            self.assertEqual(u["zip_code"], "69330")
            self.assertEqual(u["city"], "Jonage")
            self.assertEqual(u["badge_rouge"], "Oui")
            self.assertEqual(u["autonomie_bloc"], "Oui")
            self.assertEqual(u["email_primary"], "luc.bernard@nouveau.fr")
            self.assertEqual(u["email_secondary"], "parent.luc@example.com")
            self.assertEqual(u["phone"], "06 99 88 77 66")

            # Vérification dans la table purchases (créneau & statut & commentaire)
            p = conn.execute("SELECT * FROM purchases WHERE id = 70").fetchone()
            self.assertEqual(p["tarif_name"], "Cours Ados 1 (Lundi)")
            self.assertEqual(p["status"], "Annulé")
            self.assertEqual(p["status_normalized"], "Annulé")
            self.assertEqual(p["commentaires_correctif"], "Certificat médical papier fourni en main propre le 14/10.")
            self.assertEqual(p["is_modified"], "Oui")

            # Vérification dans la table orders (statut de commande)
            o = conn.execute("SELECT * FROM orders WHERE id = 60").fetchone()
            self.assertEqual(o["status"], "Annulé")
            self.assertEqual(o["status_normalized"], "Annulé")
            conn.close()
        finally:
            SqliteRepository.set_db_path(orig_db_path)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_cloud_db_endpoint(self):
        """Vérifie l'endpoint POST /api/cloud-db/sync."""
        from server import sync_cloud_db_api
        with patch("infrastructure.cloud_database.CloudDatabase.is_enabled", return_value=True):
            with patch("infrastructure.cloud_database.CloudDatabase.sync", return_value={"status": "ok", "errors": []}):
                res = sync_cloud_db_api(force=True)
                self.assertEqual(res.get("status"), "success")

    def test_season_tarifs_endpoint(self):
        """GET /api/season-tarifs retourne les tarifs disponibles de la saison active."""
        from server import get_season_tarifs_api
        res = get_season_tarifs_api("2026-2027")
        self.assertEqual(res.get("status"), "success")
        self.assertIn("tarifs", res)
        self.assertIsInstance(res["tarifs"], list)
        self.assertIn("Licence sèche", res["tarifs"])

    def test_planning_item_crud_and_export(self):
        """Vérifie la création, modification, suppression et export Excel des créneaux de planning."""
        from server import save_planning_item_api, delete_planning_item_api, export_planning_api, get_planning
        
        # 1. Création d'un nouveau créneau
        new_slot = {
            "id": 0,
            "groupe": "Test Nouveau Créneau Web",
            "jour": "Mardi",
            "horaires": "19:00 - 20:30",
            "type": "cours",
            "categorie_age": "Adultes",
            "encadrants": ["Test Coach"],
            "helloasso_tarifs": ["Licence sèche"]
        }
        res_create = save_planning_item_api(new_slot)
        self.assertEqual(res_create.get("status"), "success")
        saved_id = res_create["item"]["id"]
        self.assertGreater(saved_id, 0)

        # 2. Modification du créneau
        new_slot["id"] = saved_id
        new_slot["groupe"] = "Test Créneau Modifié Web"
        res_update = save_planning_item_api(new_slot)
        self.assertEqual(res_update.get("status"), "success")

        # Vérification dans la liste
        planning = get_planning()
        found = next((x for x in planning if x.get("id") == saved_id), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["groupe"], "Test Créneau Modifié Web")

        # 3. Export Excel (grille et liste)
        resp_export_grid = export_planning_api(mode="grid", season="2026-2027")
        self.assertEqual(resp_export_grid.headers.get("content-type"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("attachment", resp_export_grid.headers.get("content-disposition", ""))
        self.assertGreater(len(resp_export_grid.body), 1000)

        resp_export_list = export_planning_api(mode="list", season="2026-2027")
        self.assertEqual(resp_export_list.headers.get("content-type"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertGreater(len(resp_export_list.body), 1000)

        # 4. Suppression
        res_del = delete_planning_item_api(saved_id)
        self.assertEqual(res_del.get("status"), "success")

    def test_outils_page_tabs_and_iframes_wiring(self):
        """La page outils.html contient les onglets Carte et TCD."""
        html = _read(os.path.join(BUREAU, "outils.html"))
        for elem in ("tab-btn-map", "tab-btn-pivot", "pane-map", "pane-pivot",
                      "iframe-map", "iframe-pivot", "pivot-season-select", "tools-refresh-btn"):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn('apiFetch("/map")', html)
        self.assertIn('apiFetch(url)', html)
        self.assertIn('frame.srcdoc = html;', html)

    def test_communications_page_ui_and_wiring(self):
        """La page communications.html reprend le design desktop et contient tous les contrôles."""
        html = _read(os.path.join(BUREAU, "communications.html"))
        shell = _read(os.path.join(SHARED, "alj-shell.js"))
        index = _read(os.path.join(BUREAU, "index.html"))

        # Vérification du menu et du lien
        self.assertIn('/bureau/communications', shell)
        self.assertIn('/bureau/communications', index)

        # Contrôles de la page
        for elem in ("template-select", "template-name-input", "btn-save-tpl", "btn-new-tpl", "btn-del-tpl",
                      "sender-email", "sender-name", "subject-input", "body-input",
                      "signature-checkbox", "whatsapp-input", "pv-from", "pv-subject", "pv-body"):
            self.assertIn(f'id="{elem}"', html)

        self.assertIn('apiFetch("/api/email-templates"', html)
        self.assertIn('apiFetch("/api/whatsapp-template"', html)

    def test_competitions_desktop_page_ui_and_wiring(self):
        """La page bureau/competitions.html est adaptée aux grands écrans d'ordinateur tout en préservant le mobile."""
        html = _read(os.path.join(BUREAU, "competitions.html"))
        shell = _read(os.path.join(SHARED, "alj-shell.js"))
        index = _read(os.path.join(BUREAU, "index.html"))

        # Vérification des liens du menu et de l'accueil
        self.assertIn('/bureau/competitions', shell)
        self.assertIn('/bureau/competitions', index)

        # La vue mobile existe toujours séparément et n'est pas altérée
        mobile_html = _read(get_competitions_page().path)
        self.assertIn('id="page-comps"', mobile_html)
        self.assertIn('id="page-participants"', mobile_html)

        # Éléments grand écran de la page bureau
        for elem in ("comps-list-container", "comp-workspace", "comp-search-input",
                      "comp-form-modal", "comp-email-modal", "btn-add-comp", "btn-fetch-results",
                      "btn-nav-comps", "btn-nav-helloasso", "btn-nav-bilan", "btn-nav-coachs",
                      "section-competitions", "section-helloasso", "section-bilan", "section-coachs"):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn("comp-layout", html)
        self.assertIn("part-chip-all", html)
        self.assertIn("part-chip-selected", html)
        self.assertIn("part-chip-unpaid", html)
        self.assertIn("part-chip-non-invite", html)
        self.assertIn("btn-remove-all-non-invites", html)
        self.assertIn("Retirer tous les compétiteurs non invités", html)
        self.assertIn("part-status-select", html)
        self.assertIn("⚠️ Absent", html)
        self.assertIn("🔄 Report", html)
        self.assertIn('apiFetch("/api/helloasso/sync"', html)
        self.assertIn('apiFetch("/api/send-email"', html)
        self.assertIn("/fetch-results", html)
        self.assertIn("hasResults", html)
        self.assertIn("🏆 Résultats", html)

    @patch("mycompet_scraper.fetch_and_parse_mycompet_results")
    @patch("infrastructure.firestore_client.FirestoreClient.get_document")
    @patch("infrastructure.firestore_client.FirestoreClient.update_fields")
    def test_fetch_competition_results_endpoint(self, mock_update, mock_get, mock_scraper):
        mock_get.return_value = {
            "id": "comp_123",
            "nom": "Test Comp",
            "participants": [
                {"nom": "BULAND", "prenom": "Julia", "num_licence": "930654"},
                {"nom": "DUPONT", "prenom": "Jean", "num_licence": "000000"}
            ]
        }
        mock_scraper.return_value = [
            {"nom": "BULAND", "prenom": "Julia", "licence": "930654", "classement": "9", "categorie": "U13Femme"}
        ]
        client = TestClient(app, base_url="http://localhost")
        resp = client.post(
            "/api/competitions/comp_123/fetch-results",
            json={"url": "13660"},
            headers={"Host": "localhost", "Origin": "http://localhost"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["matched_count"], 1)
        self.assertEqual(data["total_scraped"], 1)
        mock_update.assert_called_once()

    def test_email_template_crud_endpoints_and_sqlite(self):
        """Les endpoints POST et DELETE /api/email-templates modifient correctement SQLite."""
        import tempfile
        import shutil
        from infrastructure.sqlite_repository import SqliteRepository
        from server import save_email_template_api, delete_email_template_api, get_email_templates

        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_tpl.db")
        orig_db_path = SqliteRepository.get_db_path()
        try:
            SqliteRepository.set_db_path(db_path)
            SqliteRepository.setup_database()

            # 1. Création d'un nouveau modèle
            payload = {
                "name": "Test Nouveau Modèle",
                "subject": "Sujet de test personnalisé",
                "body": "Bonjour {first_name}, corps de test.",
                "sender_email": "test@alj-escalade.fr",
                "sender_name": "ALJ Test"
            }
            res_save = save_email_template_api(payload)
            self.assertEqual(res_save.get("status"), "success")

            # 2. Vérification dans la liste
            res_list = get_email_templates()
            self.assertEqual(res_list.get("status"), "success")
            names = [t["name"] for t in res_list.get("templates", [])]
            self.assertIn("Test Nouveau Modèle", names)

            # 3. Renommage du modèle (old_name -> name)
            rename_payload = {
                "name": "Test Modèle Renommé",
                "old_name": "Test Nouveau Modèle",
                "subject": "Sujet mis à jour",
                "body": "Bonjour {first_name}, corps mis à jour.",
                "sender_email": "test@alj-escalade.fr",
                "sender_name": "ALJ Test"
            }
            res_rename = save_email_template_api(rename_payload)
            self.assertEqual(res_rename.get("status"), "success")

            res_list_renamed = get_email_templates()
            names_renamed = [t["name"] for t in res_list_renamed.get("templates", [])]
            self.assertIn("Test Modèle Renommé", names_renamed)
            self.assertNotIn("Test Nouveau Modèle", names_renamed)

            # 4. Suppression du modèle
            res_del = delete_email_template_api("Test Modèle Renommé")
            self.assertEqual(res_del.get("status"), "success")

            # 5. Vérification que le modèle a disparu
            res_list2 = get_email_templates()
            names2 = [t["name"] for t in res_list2.get("templates", [])]
            self.assertNotIn("Test Modèle Renommé", names2)
        finally:
            SqliteRepository.set_db_path(orig_db_path)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_whatsapp_template_endpoints(self):
        """GET et POST /api/whatsapp-template enregistrent et lisent le texte WhatsApp."""
        import tempfile
        import shutil
        from infrastructure.sqlite_repository import SqliteRepository
        from server import get_whatsapp_template_api, save_whatsapp_template_api

        temp_dir = tempfile.mkdtemp()
        db_path = os.path.join(temp_dir, "test_wa.db")
        orig_db_path = SqliteRepository.get_db_path()
        try:
            SqliteRepository.set_db_path(db_path)
            SqliteRepository.setup_database()

            res_save = save_whatsapp_template_api({"template": "Rejoignez le groupe WhatsApp du club : https://chat.whatsapp.com/xxx"})
            self.assertEqual(res_save.get("status"), "success")

            res_get = get_whatsapp_template_api()
            self.assertEqual(res_get.get("status"), "success")
            self.assertIn("chat.whatsapp.com", res_get.get("template", ""))
        finally:
            SqliteRepository.set_db_path(orig_db_path)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_email_template_write_requires_admin_role(self):
        """Les modifications de templates d'emails exigent le rôle admin."""
        from infrastructure.api_auth import required_role
        self.assertEqual(required_role("POST", "/api/email-templates"), "admin")
        self.assertEqual(required_role("DELETE", "/api/email-templates/Test"), "admin")
        self.assertEqual(required_role("POST", "/api/whatsapp-template"), "admin")
        self.assertEqual(required_role("GET", "/api/email-templates"), "coach")

    def test_apply_template_variables_adherents_extension(self):
        """Les variables {tarif} et {season} sont correctement résolues pour les adhérents."""
        from domain.utils import apply_template_variables
        member = {
            "first_name": "camille",
            "last_name": "durand",
            "licence_ffme": "654321",
            "tarif_name": "Jeunes 2010",
            "season_name": "2026-2027"
        }
        text = "Bonjour {first_name} {Nom}, votre inscription au groupe {tarif} pour la saison {season} (licence {num_licence}) est validée."
        rendered = apply_template_variables(text, member)
        self.assertEqual(
            rendered,
            "Bonjour Camille DURAND, votre inscription au groupe Jeunes 2010 pour la saison 2026-2027 (licence 654321) est validée."
        )

    def test_pwa_entry_pages_check_device_before_rendering(self):
        """competitions.html et index.html chargent alj-vue.js avant Firebase (redirection ordinateur)."""
        for page in (get_competitions_page().path, get_annuaire_page().path):
            html = _read(page)
            self.assertIn('<script src="/static-web/alj-vue.js"></script>', html, page)
            self.assertLess(html.index("alj-vue.js"), html.index("firebase-app-compat.js"), page)
        self.assertIn('href="/index?vue=pwa"', _read(get_competitions_page().path))
        self.assertIn('COMPETITIONS_URL + "?vue=pwa"', _read(get_annuaire_page().path))

    def test_device_redirect_rules(self):
        js = _read(os.path.join(SHARED, "alj-vue.js"))
        # Ordinateur : écran large et pointeur fin (souris), pas tactile
        self.assertIn("(min-width: 1024px) and (any-pointer: fine)", js)
        self.assertIn('var BUREAU = "/bureau/";', js)
        # Choix explicites : ?vue=mobile (mémorisé), ?vue=pwa (une fois), connexion Google
        self.assertIn('vue === "mobile"', js)
        self.assertIn('pwaDemandee = vue === "mobile" || vue === "pwa"', js)
        self.assertIn('params.get("login") === "1"', js)
        self.assertIn("access_token=", js)

    def test_shell_imports_exist_in_core(self):
        """Chaque nom importé par alj-shell.js doit être exporté par alj-core.js."""
        shell = _read(os.path.join(SHARED, "alj-shell.js"))
        core = _read(os.path.join(SHARED, "alj-core.js"))
        block = re.search(r"import\s*\{(.*?)\}\s*from\s*\"/static-web/alj-core.js\"", shell, re.S).group(1)
        names = [n.strip() for n in block.split(",") if n.strip()]
        self.assertTrue(names)
        for name in names:
            self.assertRegex(core, rf"export (function|const|async function) {name}\b", name)

    def test_bureau_imports_exist_in_core(self):
        """Every name imported from alj-core.js by the bureau pages and shared modules is exported."""
        core = _read(os.path.join(SHARED, "alj-core.js"))
        for path in (os.path.join(BUREAU, "competitions.html"),
                     os.path.join(BUREAU, "adherents.html"),
                     os.path.join(SHARED, "alj-filters.js")):
            block = re.search(r"import\s*\{([^}]+)\}\s*from\s*\"/static-web/alj-core\.js\"", _read(path)).group(1)
            names = [n.strip() for n in block.split(",") if n.strip()]
            self.assertTrue(names, path)
            for name in names:
                self.assertRegex(core, rf"export (function|const|async function) {name}\b", f"{path}: {name}")

    def test_core_roles_match_api_and_rules(self):
        core = _read(os.path.join(SHARED, "alj-core.js"))

        def js_list(name):
            body = re.search(r"export const %s = \[(.*?)\];" % name, core, re.S).group(1)
            return set(re.findall(r'"([^"]+)"', body))

        self.assertEqual(js_list("ADMIN_EMAILS"), set(api_auth.ADMIN_EMAILS))
        self.assertEqual(js_list("COACH_EMAILS"), set(api_auth.ADMIN_EMAILS) | set(api_auth.COACH_EMAILS))
        self.assertEqual(js_list("READONLY_EMAILS"), set(api_auth.READONLY_EMAILS))


class TestBureauAccess(unittest.TestCase):
    """Le portail reste public (pages) tandis que l'API reste protégée."""

    def setUp(self):
        self.env = patch.dict(os.environ, {"ALJ_API_AUTH": "required"})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()

    def test_portal_public_api_protected(self):
        for path in ("/bureau", "/bureau/", "/bureau/adherents", "/bureau/communications", "/bureau/competitions", "/bureau/planning", "/bureau/outils", "/bureau/parametres",
                     "/static-web/alj.css", "/static-web/alj-shell.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/bureau/inconnue").status_code, 404)
        self.assertEqual(self.client.get("/api/email-status").status_code, 401)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)

    def test_portal_content_types(self):
        self.assertIn("text/html", self.client.get("/bureau/").headers["content-type"])
        self.assertIn("text/html", self.client.get("/bureau/planning").headers["content-type"])
        self.assertIn("javascript", self.client.get("/static-web/alj-shell.js").headers["content-type"])
        self.assertIn("text/css", self.client.get("/static-web/alj.css").headers["content-type"])

    def test_required_role_for_portal(self):
        r = api_auth.required_role
        for path in ("/bureau", "/bureau/", "/bureau/adherents", "/bureau/communications", "/bureau/competitions", "/bureau/planning", "/bureau/outils", "/bureau/parametres", "/static-web/alj-core.js"):
            self.assertIsNone(r("GET", path), path)
        self.assertEqual(r("GET", "/api/email-status"), "coach")


class TestSingleFirebaseInit(unittest.TestCase):
    """Centralised Firebase initialisation (alj-firebase.js) and runtime configuration
    served by the server (/runtime-config.js): the basis of the emulator dev mode."""

    PAGES = [os.path.join(WEB, "competitions.html"), os.path.join(WEB, "index.html")] + [
        os.path.join(BUREAU, n) for n in sorted(os.listdir(BUREAU)) if n.endswith(".html")]

    def test_pages_load_config_then_init(self):
        sdk = '<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore-compat.js"></script>'
        for path in self.PAGES:
            html = _read(path)
            i_sdk = html.index(sdk)
            i_cfg = html.index('<script src="/runtime-config.js"></script>')
            i_init = html.index('<script src="/static-web/alj-firebase.js"></script>')
            self.assertLess(i_sdk, i_cfg, path)
            self.assertLess(i_cfg, i_init, path)

    def test_firebase_config_defined_once(self):
        files = self.PAGES + [os.path.join(SHARED, n) for n in os.listdir(SHARED) if n.endswith(".js")]
        owners = [os.path.basename(p) for p in files if "apiKey:" in _read(p)]
        self.assertEqual(owners, ["alj-firebase.js"])
        for path in files:
            self.assertNotIn("firebase.initializeApp(", _read(path).replace(
                "firebase.initializeApp(config)", ""), path)

    def test_service_worker_does_not_cache_config(self):
        sw = _read(get_sw().path)
        self.assertIn('"/static-web/alj-firebase.js"', sw)
        self.assertNotIn('"/runtime-config.js",', sw)
        self.assertIn('url.pathname === "/runtime-config.js"', sw)

    def test_runtime_config_is_public(self):
        self.assertIsNone(api_auth.required_role("GET", "/runtime-config.js"))


class TestSharedModuleImports(unittest.TestCase):
    """Every name imported from /static-web/*.js is exported by that module
    (otherwise a SyntaxError on page load, invisible on the server side)."""

    IMPORT_RE = re.compile(r'import\s*\{([^}]*)\}\s*from\s*"/static-web/([\w.-]+\.js)"')
    EXPORT_RE = re.compile(r'^export\s+(?:async\s+)?(?:function\*?|const|let|class)\s+(\w+)', re.M)

    def test_imported_names_are_exported(self):
        files = [os.path.join(WEB, n) for n in os.listdir(WEB) if n.endswith(".html")]
        files += [os.path.join(BUREAU, n) for n in os.listdir(BUREAU) if n.endswith(".html")]
        files += [os.path.join(SHARED, n) for n in os.listdir(SHARED) if n.endswith(".js")]
        for path in files:
            for names, module in self.IMPORT_RE.findall(_read(path)):
                exported = set(self.EXPORT_RE.findall(_read(os.path.join(SHARED, module))))
                for name in filter(None, (n.split(" as ")[0].strip() for n in names.split(","))):
                    with self.subTest(page=os.path.basename(path), module=module, name=name):
                        self.assertIn(name, exported)


if __name__ == "__main__":
    unittest.main()
