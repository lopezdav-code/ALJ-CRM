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
        for elem in ("members-table", "members-tbody", "detail-pane", "search-input",
                      "season-select", "export-csv-btn", "status-chips", "filter-box"):
            self.assertIn(f'id="{elem}"', html)

    def test_adherents_email_modal_and_api_wiring(self):
        """L'Étape 2 intègre la modale d'e-mail et le câblage aux endpoints d'e-mail."""
        html = _read(os.path.join(BUREAU, "adherents.html"))
        for elem in ("email-modal", "em-template-select", "em-subject", "em-body",
                      "em-signature", "em-preview-box", "em-submit-btn", "em-cancel-btn"):
            self.assertIn(f'id="{elem}"', html)
        self.assertIn('apiFetch("/api/email-templates")', html)
        self.assertIn('apiFetch("/api/send-email"', html)

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
        for path in ("/bureau", "/bureau/", "/bureau/adherents", "/bureau/outils",
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
        for path in ("/bureau", "/bureau/", "/bureau/adherents", "/static-web/alj-core.js"):
            self.assertIsNone(r("GET", path), path)
        self.assertEqual(r("GET", "/api/email-status"), "coach")


if __name__ == "__main__":
    unittest.main()
