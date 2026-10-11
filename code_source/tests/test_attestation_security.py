"""
Attestation PDF security: member data (public HelloAsso form) and request values must
never inject markup into the attestation HTML, and WeasyPrint must never read server
files or the network while rendering it.
"""

import os
import re
import sys
import unittest
import zlib

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_tests_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from domain.attestation import (  # noqa: E402
    _render_minimal_pdf_with_pydyf,
    build_attestation,
    render_attestation_pdf,
)

INJECTION = '<a rel="attachment" href="file:///etc/hostname">x</a>'


def _weasyprint_available() -> bool:
    try:
        from weasyprint import HTML
        HTML(string="<p>x</p>").write_pdf()
        return True
    except Exception:
        return False


def _pdf_contains(pdf: bytes, needle: bytes) -> bool:
    """True if `needle` appears in the PDF, raw or inside a Flate-compressed stream."""
    if needle in pdf:
        return True
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            if needle in zlib.decompress(m.group(1)):
                return True
        except zlib.error:
            continue
    return False


class TestAttestationEscaping(unittest.TestCase):

    def test_member_and_request_values_are_escaped(self):
        member = {"first_name": INJECTION, "last_name": INJECTION, "payer": f"{INJECTION} {INJECTION}",
                  "amount": 150}
        html = build_attestation(member, season=INJECTION, date_jour=INJECTION)
        self.assertNotIn('rel="attachment"', html.lower())
        self.assertNotIn("<a ", html.lower())
        self.assertIn("&lt;", html)

    def test_regular_names_unchanged(self):
        html = build_attestation({"first_name": "Hermione", "last_name": "Granger", "amount": 150},
                                 season="2026-2027", date_jour="1 September 2026")
        self.assertIn("Hermione", html)
        self.assertIn("GRANGER", html)
        self.assertIn("150,00", html)

    def test_fallback_renderer_shows_plain_text(self):
        html = build_attestation({"first_name": "Seamus", "last_name": "O'Flaherty & Co", "amount": 150},
                                 season="2026-2027", date_jour="1 September 2026")
        pdf = _render_minimal_pdf_with_pydyf(html)
        self.assertTrue(_pdf_contains(pdf, b"O'FLAHERTY & CO"))
        self.assertFalse(_pdf_contains(pdf, b"&amp;"))


@unittest.skipUnless(_weasyprint_available(), "WeasyPrint (Pango) not available")
class TestAttestationRendering(unittest.TestCase):

    def test_local_files_are_never_embedded(self):
        """Even raw markup reaching the renderer cannot read a server file."""
        with open("/etc/hostname", "rb") as f:
            secret = f.read().strip()
        pdf = render_attestation_pdf(f"<p>{INJECTION}</p><img src='file:///etc/hostname'>")
        self.assertNotIn(b"/EmbeddedFile", pdf)
        self.assertFalse(_pdf_contains(pdf, secret))

    def test_embedded_images_still_rendered(self):
        html = build_attestation({"first_name": "Harry", "last_name": "Potter", "amount": 150},
                                 season="2026-2027")
        if "data:image" not in html:
            self.skipTest("no logo or signature image available")
        pdf = render_attestation_pdf(html)
        self.assertIn(b"/Subtype /Image", pdf)


if __name__ == "__main__":
    unittest.main()
