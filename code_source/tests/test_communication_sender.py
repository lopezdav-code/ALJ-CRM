import os
import sys
import base64
import sqlite3
import email as email_lib
import unittest
from email.header import decode_header, make_header
from email.utils import parseaddr
from unittest.mock import patch, MagicMock

# Ajustement du chemin pour importer les modules depuis 'src'
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.sqlite_repository import SqliteRepository, DEFAULT_SENDER_EMAIL, DEFAULT_SENDER_NAME
from infrastructure.email_repository import EmailRepository


def decode_from_header(raw_value: str):
    """Décode un en-tête From (RFC 2047) et retourne (nom_affiché, adresse)."""
    decoded = str(make_header(decode_header(raw_value)))
    return parseaddr(decoded)

try:
    from PySide6.QtWidgets import QApplication
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


class TempDbTestCase(unittest.TestCase):
    """Base commune : BDD SQLite isolée dans un fichier temporaire pour chaque test."""

    def setUp(self):
        self.original_db_path = SqliteRepository.get_db_path()
        self.test_db_path = os.path.join(_test_dir, "test_sender_database.db")
        SqliteRepository.set_db_path(self.test_db_path)

    def tearDown(self):
        SqliteRepository.set_db_path(self.original_db_path)
        for suffix in ("", "-wal", "-shm"):
            p = self.test_db_path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


class TestSenderEmailDatabase(TempDbTestCase):

    def test_default_sender_email_constant(self):
        """L'adresse du club est bien la constante attendue."""
        self.assertEqual(DEFAULT_SENDER_EMAIL, "inscription@alj-escalade.fr")

    def test_default_sender_name_constant(self):
        """Le nom d'affichage par défaut est bien la constante attendue."""
        self.assertEqual(DEFAULT_SENDER_NAME, "Amicale Laïque Jonage - Inscriptions")

    def test_default_templates_have_sender(self):
        """Les modèles par défaut sont créés avec l'adresse et le nom d'expédition du club."""
        SqliteRepository.setup_database()
        templates = SqliteRepository.get_email_templates()
        self.assertTrue(templates)
        for t in templates:
            self.assertIn("sender_email", t)
            self.assertEqual(t["sender_email"], DEFAULT_SENDER_EMAIL)
            self.assertEqual(t["sender_name"], DEFAULT_SENDER_NAME)

    def test_save_template_with_sender_roundtrip(self):
        """Enregistrement d'un modèle avec adresse + nom d'expédition puis relecture."""
        SqliteRepository.setup_database()
        self.assertTrue(SqliteRepository.save_email_template(
            "Test Sender", "Objet", "Corps",
            sender_email="inscription@alj-escalade.fr", sender_name="Amicale Laïque Jonage - Inscriptions"
        ))
        tmpl = next(t for t in SqliteRepository.get_email_templates() if t["name"] == "Test Sender")
        self.assertEqual(tmpl["sender_email"], "inscription@alj-escalade.fr")
        self.assertEqual(tmpl["sender_name"], "Amicale Laïque Jonage - Inscriptions")

        # Mise à jour de l'expéditeur du même modèle
        self.assertTrue(SqliteRepository.save_email_template(
            "Test Sender", "Objet 2", "Corps 2",
            sender_email="contact@alj-escalade.fr", sender_name="ALJ Escalade"
        ))
        tmpl = next(t for t in SqliteRepository.get_email_templates() if t["name"] == "Test Sender")
        self.assertEqual(tmpl["sender_email"], "contact@alj-escalade.fr")
        self.assertEqual(tmpl["sender_name"], "ALJ Escalade")
        self.assertEqual(tmpl["subject"], "Objet 2")

    def test_save_template_empty_sender_falls_back_to_default(self):
        """Une adresse / un nom vide retombe sur les valeurs par défaut du club."""
        SqliteRepository.setup_database()
        self.assertTrue(SqliteRepository.save_email_template("Test Vide", "Objet", "Corps", sender_email="  ", sender_name=""))
        tmpl = next(t for t in SqliteRepository.get_email_templates() if t["name"] == "Test Vide")
        self.assertEqual(tmpl["sender_email"], DEFAULT_SENDER_EMAIL)
        self.assertEqual(tmpl["sender_name"], DEFAULT_SENDER_NAME)

    def test_migration_adds_sender_column_to_legacy_db(self):
        """Une BDD existante sans colonne sender_email est migrée et complétée automatiquement."""
        # Créer une BDD « legacy » avec l'ancien schéma de email_templates
        conn = sqlite3.connect(self.test_db_path)
        conn.execute("""
            CREATE TABLE email_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL
            )
        """)
        conn.execute("INSERT INTO email_templates (name, subject, body) VALUES ('Legacy', 'Sujet', 'Corps')")
        conn.commit()
        conn.close()

        SqliteRepository.setup_database()

        templates = {t["name"]: t for t in SqliteRepository.get_email_templates()}
        self.assertIn("Legacy", templates)
        self.assertEqual(templates["Legacy"]["sender_email"], DEFAULT_SENDER_EMAIL)
        self.assertEqual(templates["Legacy"]["sender_name"], DEFAULT_SENDER_NAME)

    def test_app_settings_roundtrip(self):
        """Réglages génériques (adresse par défaut / liste des adresses) en BDD."""
        self.assertIsNone(SqliteRepository.get_app_setting("default_sender_email"))
        self.assertTrue(SqliteRepository.save_app_setting("default_sender_email", "bureau@alj-escalade.fr"))
        self.assertEqual(SqliteRepository.get_app_setting("default_sender_email"), "bureau@alj-escalade.fr")
        # Clé inexistante → valeur par défaut
        self.assertEqual(SqliteRepository.get_app_setting("inexistant", "x"), "x")


class TestEmailRepositoryFrom(unittest.TestCase):
    """Vérifie que l'adresse d'expédition choisie est bien utilisée dans le message envoyé."""

    OAUTH_SECRETS = {
        "GMAIL_USER_EMAIL": "club@gmail.com",
        "GMAIL_CLIENT_ID": "client-id",
        "GMAIL_REFRESH_TOKEN": "refresh-token",
        "SMTP_HOST": "", "SMTP_PORT": "", "SMTP_USER": "", "SMTP_PASSWORD": "", "SMTP_FROM_EMAIL": "",
    }

    SMTP_SECRETS = {
        "GMAIL_USER_EMAIL": "", "GMAIL_CLIENT_ID": "", "GMAIL_REFRESH_TOKEN": "",
        "SMTP_HOST": "smtp.alj-escalade.fr", "SMTP_PORT": "587",
        "SMTP_USER": "club@alj-escalade.fr", "SMTP_PASSWORD": "secret",
        "SMTP_FROM_EMAIL": "club@alj-escalade.fr",
    }

    def _patch_secret_store(self, secrets):
        return patch(
            "infrastructure.email_repository.SecretStore.get_secret",
            side_effect=lambda key: secrets.get(key, ""),
        )

    def test_gmail_api_uses_chosen_from(self):
        """Mode Gmail API : l'en-tête From du message envoyé porte le nom et l'adresse choisis."""
        captured = {}

        class FakeResponse:
            status_code = 200
            text = "OK"

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

        with self._patch_secret_store(self.OAUTH_SECRETS), \
             patch("infrastructure.google_drive_client.GoogleDriveClient.get_access_token", return_value="fake-token"), \
             patch("infrastructure.email_repository.requests.post", side_effect=fake_post):
            EmailRepository.send_email(
                "dest@example.com", "Sujet", "Corps",
                from_email="inscription@alj-escalade.fr",
                from_name="Amicale Laïque Jonage - Inscriptions"
            )

        raw = captured["payload"]["raw"]
        msg = email_lib.message_from_bytes(base64.urlsafe_b64decode(raw))
        from_name, from_addr = decode_from_header(msg["From"])
        self.assertEqual(from_addr, "inscription@alj-escalade.fr")
        self.assertEqual(from_name, "Amicale Laïque Jonage - Inscriptions")
        self.assertEqual(msg["To"], "dest@example.com")
        self.assertIn("/users/club@gmail.com/messages/send", captured["url"])

    def test_gmail_api_from_without_display_name(self):
        """Mode Gmail API : sans nom fourni, seul l'adresse figure dans l'en-tête From."""
        captured = {}

        class FakeResponse:
            status_code = 200
            text = "OK"

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return FakeResponse()

        with self._patch_secret_store(self.OAUTH_SECRETS), \
             patch("infrastructure.google_drive_client.GoogleDriveClient.get_access_token", return_value="fake-token"), \
             patch("infrastructure.email_repository.requests.post", side_effect=fake_post):
            EmailRepository.send_email(
                "dest@example.com", "Sujet", "Corps",
                from_email="inscription@alj-escalade.fr", from_name="  "
            )

        msg = email_lib.message_from_bytes(base64.urlsafe_b64decode(captured["payload"]["raw"]))
        self.assertEqual(msg["From"], "inscription@alj-escalade.fr")

    def test_gmail_api_default_from_without_choice(self):
        """Mode Gmail API : sans adresse choisie, on retombe sur le compte configuré."""
        captured = {}

        class FakeResponse:
            status_code = 200
            text = "OK"

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return FakeResponse()

        with self._patch_secret_store(self.OAUTH_SECRETS), \
             patch("infrastructure.google_drive_client.GoogleDriveClient.get_access_token", return_value="fake-token"), \
             patch("infrastructure.email_repository.requests.post", side_effect=fake_post):
            EmailRepository.send_email("dest@example.com", "Sujet", "Corps", from_email="   ")

        msg = email_lib.message_from_bytes(base64.urlsafe_b64decode(captured["payload"]["raw"]))
        self.assertEqual(msg["From"], "club@gmail.com")

    def test_smtp_uses_chosen_from_header(self):
        """Mode SMTP : l'en-tête From porte le nom + adresse choisis, l'enveloppe reste le compte authentifié."""
        captured = {}
        fake_server = MagicMock()

        def fake_sendmail(from_addr, to_addrs, msg_string):
            captured["envelope_from"] = from_addr
            captured["msg_string"] = msg_string

        fake_server.sendmail.side_effect = fake_sendmail

        with self._patch_secret_store(self.SMTP_SECRETS), \
             patch("infrastructure.email_repository.smtplib.SMTP", return_value=fake_server):
            EmailRepository.send_email(
                "dest@example.com", "Sujet", "Corps",
                from_email="inscription@alj-escalade.fr",
                from_name="Amicale Laïque Jonage - Inscriptions"
            )

        self.assertEqual(captured["envelope_from"], "club@alj-escalade.fr")
        msg = email_lib.message_from_string(captured["msg_string"])
        from_name, from_addr = decode_from_header(msg["From"])
        self.assertEqual(from_addr, "inscription@alj-escalade.fr")
        self.assertEqual(from_name, "Amicale Laïque Jonage - Inscriptions")
        fake_server.login.assert_called_once_with("club@alj-escalade.fr", "secret")


class TestWorkerSenderPropagation(unittest.TestCase):

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible")
    def test_worker_accepts_sender_email(self):
        """Le worker de campagne propage l'adresse et le nom d'expédition vers EmailRepository."""
        from presentation.workers import SendEmailCampaignWorker

        worker = SendEmailCampaignWorker(
            "Sujet", "Corps", [],
            sender_email="inscription@alj-escalade.fr",
            sender_name="Amicale Laïque Jonage - Inscriptions"
        )
        self.assertEqual(worker.sender_email, "inscription@alj-escalade.fr")
        self.assertEqual(worker.sender_name, "Amicale Laïque Jonage - Inscriptions")

        # Adresse / nom vides / espaces → None (retombe sur le compte configuré)
        worker_empty = SendEmailCampaignWorker("Sujet", "Corps", [], sender_email="   ", sender_name="")
        self.assertIsNone(worker_empty.sender_email)
        self.assertIsNone(worker_empty.sender_name)

        # Comportement historique conservé (sans les arguments)
        worker_legacy = SendEmailCampaignWorker("Sujet", "Corps", [])
        self.assertIsNone(worker_legacy.sender_email)
        self.assertIsNone(worker_legacy.sender_name)


@unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
class TestCommunicationsPageSender(TempDbTestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_page_has_sender_combo_with_default(self):
        """La page Communication expose un sélecteur d'expédition prérempli avec l'adresse et le nom du club."""
        from presentation.pages.communications import CommunicationsPage
        page = CommunicationsPage()
        self.assertTrue(page.sender_email_combo.isEditable())
        self.assertEqual(page.sender_email_combo.currentText(), DEFAULT_SENDER_EMAIL)
        self.assertIn(DEFAULT_SENDER_EMAIL, [page.sender_email_combo.itemText(i) for i in range(page.sender_email_combo.count())])
        self.assertEqual(page.sender_name_input.text(), DEFAULT_SENDER_NAME)

    def test_save_template_stores_sender_and_reload_restores_it(self):
        """Enregistrer un modèle mémorise son expéditeur ; la sélection du modèle le restaure."""
        from presentation.pages.communications import CommunicationsPage
        page = CommunicationsPage()

        page.template_selector.setCurrentText("Attestation standard")
        page.sender_email_combo.setCurrentText("inscription@alj-escalade.fr")
        page.sender_name_input.setText("Amicale Laïque Jonage - Inscriptions")

        with patch("presentation.pages.communications.QMessageBox.warning") as mock_warn, \
             patch("presentation.pages.communications.QMessageBox.critical") as mock_crit:
            page.on_save_template_clicked()

        mock_warn.assert_not_called()
        mock_crit.assert_not_called()

        tmpl = next(t for t in SqliteRepository.get_email_templates() if t["name"] == "Attestation standard")
        self.assertEqual(tmpl["sender_email"], "inscription@alj-escalade.fr")
        self.assertEqual(tmpl["sender_name"], "Amicale Laïque Jonage - Inscriptions")

        # En changeant l'expéditeur à l'écran puis en re-sélectionnant le modèle, les valeurs enregistrées reviennent
        page.sender_email_combo.setCurrentText("autre@exemple.fr")
        page.sender_name_input.setText("Autre Nom")
        idx = page.template_selector.findText("Attestation standard")
        page.on_template_selected(idx)
        self.assertEqual(page.sender_email_combo.currentText(), "inscription@alj-escalade.fr")
        self.assertEqual(page.sender_name_input.text(), "Amicale Laïque Jonage - Inscriptions")

    def test_save_template_rejects_invalid_sender(self):
        """Un enregistrement avec une adresse invalide est refusé (message d'avertissement)."""
        from presentation.pages.communications import CommunicationsPage
        page = CommunicationsPage()
        page.template_selector.setCurrentText("Attestation standard")
        page.sender_email_combo.setCurrentText("pas-un-email")

        with patch("presentation.pages.communications.QMessageBox.warning") as mock_warn:
            page.on_save_template_clicked()

        mock_warn.assert_called_once()
        tmpl = next(t for t in SqliteRepository.get_email_templates() if t["name"] == "Attestation standard")
        # Le modèle conserve l'adresse d'origine (seed) et non l'adresse invalide
        self.assertNotEqual(tmpl["sender_email"], "pas-un-email")

    def test_save_sender_default_persists(self):
        """Le bouton Enregistrer de l'expédition persiste l'adresse + le nom par défaut + la liste."""
        from presentation.pages.communications import CommunicationsPage
        page = CommunicationsPage()
        page.sender_email_combo.setCurrentText("bureau@alj-escalade.fr")
        page.sender_name_input.setText("ALJ Escalade - Bureau")

        with patch("presentation.pages.communications.QMessageBox.warning") as mock_warn:
            page.on_save_sender_clicked()

        mock_warn.assert_not_called()
        self.assertEqual(SqliteRepository.get_app_setting("default_sender_email"), "bureau@alj-escalade.fr")
        self.assertEqual(SqliteRepository.get_app_setting("default_sender_name"), "ALJ Escalade - Bureau")
        saved = SqliteRepository.get_app_setting("sender_emails") or ""
        self.assertIn("bureau@alj-escalade.fr", saved)

        # Une nouvelle page recharge l'expéditeur par défaut enregistré dans la liste déroulante
        page2 = CommunicationsPage()
        page2.init_sender_combo()
        self.assertEqual(page2.sender_email_combo.currentText(), "bureau@alj-escalade.fr")
        self.assertEqual(page2.sender_name_input.text(), "ALJ Escalade - Bureau")

        # Un modèle sans expédition retombe sur l'adresse et le nom par défaut sauvegardés
        SqliteRepository.save_email_template("Sans Expédition", "Objet", "Corps", sender_email="   ")
        # Neutraliser le backfill auto du schéma en vidant les colonnes directement
        conn = sqlite3.connect(self.test_db_path)
        conn.execute("UPDATE email_templates SET sender_email = '', sender_name = '' WHERE name = 'Sans Expédition'")
        conn.commit()
        conn.close()
        page3 = CommunicationsPage()
        idx = page3.template_selector.findText("Sans Expédition")
        page3.on_template_selected(idx)
        self.assertEqual(page3.sender_email_combo.currentText(), "bureau@alj-escalade.fr")
        self.assertEqual(page3.sender_name_input.text(), "ALJ Escalade - Bureau")

    def test_form_is_scrollable_for_small_screens(self):
        """Le formulaire de droite est défilable (lisible sur les petits écrans),
        la barre de progression et les logs restant en dehors de la zone défilante."""
        from presentation.pages.communications import CommunicationsPage
        page = CommunicationsPage()
        self.assertTrue(page.form_scroll.widgetResizable())
        self.assertIs(page.form_scroll.widget(), page.form_frame)
        self.assertGreaterEqual(page.form_frame.minimumWidth(), 540)
        # La barre de progression et les logs ne doivent pas être dans la zone défilante
        self.assertIsNot(page.progress_bar.parent(), page.form_frame)
        self.assertIsNot(page.log_area.parent(), page.form_frame)

    def test_save_sender_invalid_shows_warning(self):
        """Une adresse sans '@' est refusée avec un avertissement et non enregistrée."""
        from presentation.pages.communications import CommunicationsPage
        page = CommunicationsPage()
        page.sender_email_combo.setCurrentText("pas-un-email")

        with patch("presentation.pages.communications.QMessageBox.warning") as mock_warn:
            page.on_save_sender_clicked()

        mock_warn.assert_called_once()
        self.assertIsNone(SqliteRepository.get_app_setting("default_sender_email"))

    def test_new_template_uses_current_sender(self):
        """La création d'un nouveau modèle enregistre l'adresse d'expédition courante."""
        from presentation.pages.communications import CommunicationsPage
        page = CommunicationsPage()
        page.sender_email_combo.setCurrentText("inscription@alj-escalade.fr")

        with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("Modèle Test Expédition", True)), \
             patch("presentation.pages.communications.QMessageBox.warning"), \
             patch("presentation.pages.communications.QMessageBox.critical"):
            page.on_new_template_clicked()

        tmpl = next(t for t in SqliteRepository.get_email_templates() if t["name"] == "Modèle Test Expédition")
        self.assertEqual(tmpl["sender_email"], "inscription@alj-escalade.fr")


if __name__ == "__main__":
    unittest.main()
