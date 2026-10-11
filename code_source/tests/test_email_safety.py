"""
E-mails built from member data (public HelloAsso form): personalised values must
never add markup to the HTML part nor inject headers, while the template's own
formatting (<b>, links, line breaks) keeps working.
"""

import os
import sys
import unittest
from email import message_from_string
from unittest.mock import MagicMock, patch

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_tests_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from domain.utils import apply_template_variables, sanitize_email_header  # noqa: E402
from infrastructure.email_dispatch_service import EmailDispatchService  # noqa: E402

EVIL_NAME = '<a href="https://evil.example">Pay here</a>'


class TestPersonalisedHtml(unittest.TestCase):

    def _preview(self, body, first_name):
        with patch.object(EmailDispatchService, "get_competition_context", return_value={}):
            return EmailDispatchService.preview(
                subject="Hello {first_name}", body=body,
                recipient={"first_name": first_name, "last_name": "X", "email": "x@example.com"},
                add_signature=False)

    def test_member_value_cannot_add_markup(self):
        html = self._preview("Hello {first_name}", EVIL_NAME)["body_html"]
        self.assertNotIn("evil.example\"", html)
        self.assertNotIn("<a ", html)
        self.assertIn("&lt;a href=", html.lower())

    def test_template_formatting_still_works(self):
        html = self._preview('<b>Hello</b> {first_name}\n<a href="https://alj-escalade.fr">site</a>',
                             "Hermione")["body_html"]
        self.assertIn("<b>Hello</b> Hermione", html)
        self.assertIn('<a href="https://alj-escalade.fr"', html)
        self.assertIn("<br>", html)

    def test_plain_text_keeps_raw_value(self):
        self.assertEqual(self._preview("Hi {first_name}", "R&D")["body_plain"], "Hi R&D")

    def test_escape_option(self):
        member = {"first_name": "<b>x</b>", "last_name": "y"}
        self.assertEqual(apply_template_variables("{first_name}", member, escape_html=True), "&lt;B&gt;X&lt;/B&gt;")
        self.assertEqual(apply_template_variables("{first_name}", member), "<B>X</B>")


class TestHeaders(unittest.TestCase):

    def test_sanitize_email_header(self):
        self.assertEqual(sanitize_email_header("Hello\r\nBcc: evil@example.com"), "Hello Bcc: evil@example.com")
        self.assertEqual(sanitize_email_header(None), "")

    def test_smtp_message_has_no_injected_header(self):
        from infrastructure.email_repository import EmailRepository
        secrets = {"SMTP_HOST": "localhost", "SMTP_PORT": "1025", "SMTP_USER": "u", "SMTP_PASSWORD": "p",
                   "SMTP_FROM_EMAIL": "office@example.com"}
        smtp = MagicMock()
        with patch("infrastructure.email_repository.SecretStore.get_secret", side_effect=lambda k: secrets.get(k, "")), \
             patch("smtplib.SMTP", return_value=smtp), patch.object(EmailRepository, "log_audit"):
            ok = EmailRepository.send_email(
                to_email="victim@example.com\r\nBcc: spy@example.com",
                subject="Hi\r\nBcc: spy@example.com", body="body",
                from_name="Club\r\nReply-To: spy@example.com")
        self.assertTrue(ok)
        _, envelope_to, text = smtp.sendmail.call_args.args
        self.assertNotIn("\n", str(envelope_to))
        msg = message_from_string(text)
        self.assertIsNone(msg["Bcc"])
        self.assertIsNone(msg["Reply-To"])


class TestSendPermissions(unittest.TestCase):
    """A coach may only write to known members/payers; nobody may send as a foreign address."""

    KNOWN = {"harry.potter@hogwarts.example", "molly.weasley@hogwarts.example"}

    def setUp(self):
        patcher = patch.object(EmailDispatchService, "known_member_emails", return_value=self.KNOWN)
        patcher.start()
        self.addCleanup(patcher.stop)

    def reason(self, emails, sender=None, is_admin=False):
        return EmailDispatchService.unauthorized_send_reason(
            [{"email": e} for e in emails], sender, is_admin=is_admin)

    def test_coach_known_recipients(self):
        self.assertIsNone(self.reason(["Harry.Potter@hogwarts.example", "molly.weasley@hogwarts.example"]))

    def test_coach_unknown_recipient_refused(self):
        self.assertIn("spy@evil.example", self.reason(["harry.potter@hogwarts.example", "spy@evil.example"]))

    def test_admin_any_recipient(self):
        self.assertIsNone(self.reason(["anyone@example.com"], is_admin=True))

    def test_sender_allowlist(self):
        self.assertIsNone(self.reason([], sender="inscription@alj-escalade.fr"))
        self.assertIsNotNone(self.reason([], sender="president@evil.example", is_admin=True))


class TestSendEmailRoute(unittest.TestCase):

    def setUp(self):
        from fastapi.testclient import TestClient
        from server import app
        self.client = TestClient(app)

    def _send(self, claims, payload):
        with patch.dict(os.environ, {"ALJ_API_AUTH": "required"}), \
             patch("infrastructure.api_auth.verify_firebase_token", return_value=claims), \
             patch.object(EmailDispatchService, "known_member_emails",
                          return_value={"harry.potter@hogwarts.example"}), \
             patch.object(EmailDispatchService, "dispatch_emails",
                          return_value={"status": "success", "sent_count": 1}) as dispatch:
            resp = self.client.post("/api/send-email", json=payload, headers={"Authorization": "Bearer t"})
        return resp, dispatch

    def test_coach_to_unknown_address_refused(self):
        coach = {"sub": "c", "email": "coach@example.com", "email_verified": True, "coach": True}
        resp, dispatch = self._send(coach, {"subject": "s", "body": "b",
                                            "recipients": [{"email": "spy@evil.example"}]})
        self.assertEqual(resp.status_code, 403)
        dispatch.assert_not_called()

    def test_coach_to_member_allowed(self):
        coach = {"sub": "c", "email": "coach@example.com", "email_verified": True, "coach": True}
        resp, dispatch = self._send(coach, {"subject": "s", "body": "b",
                                            "recipients": [{"email": "harry.potter@hogwarts.example"}]})
        self.assertEqual(resp.status_code, 200)
        dispatch.assert_called_once()

    def test_admin_to_any_address_allowed(self):
        admin = {"sub": "a", "email": "albus@alj-escalade.fr", "email_verified": True}
        resp, dispatch = self._send(admin, {"subject": "s", "body": "b",
                                            "recipients": [{"email": "partner@example.org"}]})
        self.assertEqual(resp.status_code, 200)
        dispatch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
