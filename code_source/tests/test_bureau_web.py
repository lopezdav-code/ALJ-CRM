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

_tests_dir = os.path.dirname(os.path.abspath(__file__))
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
        for name in ("index.html", "adherents.html", "outils.html"):
            html = _read(os.path.join(BUREAU, name))
            self.assertIn(f'<meta name="alj-web-version" content="{version}">', html, name)
            self.assertRegex(html, rf"<title>[^<]*\(v{version}\)</title>", name)

    def test_service_worker_precaches_portal(self):
        sw = _read(get_sw().path)
        version = _current_version()
        self.assertIn(f'CACHE_NAME = "alj-escalade-v{version}"', sw)
        for asset in ("/bureau/", "/bureau/adherents", "/bureau/outils",
                      "/static-web/alj.css", "/static-web/alj-core.js",
                      "/static-web/alj-shell.js", "/static-web/alj-vue.js",
                      "/static-web/alj-members.js", "/static-web/alj-filters.js"):
            self.assertIn(f'"{asset}"', sw)

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
                      "edit-save-btn", "edit-badge-rouge", "edit-autonomie-bloc",
                      "edit-tarifs-container", "edit-email-primary", "edit-email-secondary", "edit-phone"):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn('apiFetch("/api/members/update"', html)

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
                    "badge_rouge": "Oui",
                    "autonomie_bloc": "Oui",
                    "email_primary": "luc.bernard@nouveau.fr",
                    "email_secondary": "parent.luc@example.com",
                    "phone": "06 99 88 77 66",
                    "tarif_name": "Cours Ados 1 (Lundi)"
                }
            }

            res = update_member_api(payload)
            self.assertEqual(res.get("status"), "success")

            # Vérification dans la table users
            conn = SqliteRepository.get_connection()
            u = conn.execute("SELECT * FROM users WHERE id = 50").fetchone()
            self.assertEqual(u["badge_rouge"], "Oui")
            self.assertEqual(u["autonomie_bloc"], "Oui")
            self.assertEqual(u["email_primary"], "luc.bernard@nouveau.fr")
            self.assertEqual(u["email_secondary"], "parent.luc@example.com")
            self.assertEqual(u["phone"], "06 99 88 77 66")

            # Vérification dans la table purchases (créneau)
            p = conn.execute("SELECT * FROM purchases WHERE id = 70").fetchone()
            self.assertEqual(p["tarif_name"], "Cours Ados 1 (Lundi)")
            self.assertEqual(p["is_modified"], "Oui")
            conn.close()
        finally:
            SqliteRepository.set_db_path(orig_db_path)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_season_tarifs_endpoint(self):
        """GET /api/season-tarifs retourne les tarifs disponibles de la saison active."""
        from server import get_season_tarifs_api
        res = get_season_tarifs_api("2026-2027")
        self.assertEqual(res.get("status"), "success")
        self.assertIn("tarifs", res)
        self.assertIsInstance(res["tarifs"], list)

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
        for elem in ("template-select", "btn-save-tpl", "btn-new-tpl", "btn-del-tpl",
                      "sender-email", "sender-name", "subject-input", "body-input",
                      "signature-checkbox", "whatsapp-input", "pv-from", "pv-subject", "pv-body"):
            self.assertIn(f'id="{elem}"', html)

        self.assertIn('apiFetch("/api/email-templates"', html)
        self.assertIn('apiFetch("/api/whatsapp-template"', html)

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

            # 3. Suppression du modèle
            res_del = delete_email_template_api("Test Nouveau Modèle")
            self.assertEqual(res_del.get("status"), "success")

            # 4. Vérification que le modèle a disparu
            res_list2 = get_email_templates()
            names2 = [t["name"] for t in res_list2.get("templates", [])]
            self.assertNotIn("Test Nouveau Modèle", names2)
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
        for path in ("/bureau", "/bureau/", "/bureau/adherents", "/bureau/communications", "/bureau/outils",
                     "/static-web/alj.css", "/static-web/alj-shell.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get("/bureau/inconnue").status_code, 404)
        self.assertEqual(self.client.get("/api/email-status").status_code, 401)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)

    def test_portal_content_types(self):
        self.assertIn("text/html", self.client.get("/bureau/").headers["content-type"])
        self.assertIn("javascript", self.client.get("/static-web/alj-shell.js").headers["content-type"])
        self.assertIn("text/css", self.client.get("/static-web/alj.css").headers["content-type"])

    def test_required_role_for_portal(self):
        r = api_auth.required_role
        for path in ("/bureau", "/bureau/", "/bureau/adherents", "/bureau/communications", "/static-web/alj-core.js"):
            self.assertIsNone(r("GET", path), path)
        self.assertEqual(r("GET", "/api/email-status"), "coach")


if __name__ == "__main__":
    unittest.main()
