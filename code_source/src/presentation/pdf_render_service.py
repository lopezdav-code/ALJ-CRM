"""
Service de rendu PDF des attestations, exécuté exclusivement sur le thread principal (GUI).

QtWebEngine (Chromium) n'est PAS thread-safe : une QWebEnginePage doit toujours être
créée et utilisée depuis le thread principal de l'application. Les workers (QThread)
qui ont besoin d'attestations PDF émettent donc un signal `pdf_generation_requested`,
connecté par l'IHM avec une connexion bloquante (Qt.BlockingQueuedConnection) vers ce
service. Sans cela, l'application plante nativement (crash sans traceback Python) dès
la deuxième génération effectuée depuis un thread différent du premier.
"""
import threading

from PySide6.QtCore import QObject

from attestation_generator import generate_all_attestations


class PdfRenderService(QObject):
    """Propriétaire unique de la QWebEnginePage Chromium (thread principal uniquement)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._web_page = None

    def _get_web_page(self):
        """Crée paresseusement la page Chromium (une seule fois, réutilisée ensuite)."""
        if self._web_page is None:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineCore import QWebEnginePage

            # S'assurer qu'une QApplication existe (obligatoire pour Qt)
            app = QApplication.instance() or QApplication([])
            self._web_page = QWebEnginePage(self)
        return self._web_page

    def render_attestations(self, participants, output_format="pdf", test_mode=False):
        """Fusion + rendu des attestations. À appeler UNIQUEMENT depuis le thread principal.

        Retourne un dict {"success": bool, "error": str} que l'IHM recopie dans le
        worker demandeur (objet partagé par référence, cf. FFMEMergeWorker)."""
        result = {"success": False, "error": ""}
        try:
            if threading.current_thread() is not threading.main_thread():
                raise RuntimeError(
                    "PdfRenderService doit être appelé depuis le thread principal (GUI)."
                )
            web_page = self._get_web_page() if output_format in ("pdf", "both") else None
            generate_all_attestations(
                test_mode=test_mode,
                output_format=output_format,
                participants_list=participants,
                web_page=web_page,
            )
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)
            # Par précaution, on recréera une page Chromium propre au prochain appel
            if self._web_page is not None:
                try:
                    self._web_page.deleteLater()
                except Exception:
                    pass
                self._web_page = None
        return result


_service = None


def get_pdf_render_service():
    """Retourne l'instance unique du service (créée paresseusement sur le thread principal)."""
    global _service
    if _service is None:
        _service = PdfRenderService()
    return _service
