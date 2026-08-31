import os
import sys
import unittest

# S'assurer de charger src dans sys.path pour les tests
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

try:
    from PySide6.QtCore import QThread
    from presentation.workers import (
        SyncHelloAssoWorker, 
        GenerateAttestationsWorker, 
        SendEmailCampaignWorker
    )
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

class TestPresentationLot5(unittest.TestCase):

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester les workers asynchrones")
    def test_workers_instantiation(self):
        """Vérifie que tous les workers asynchrones s'instancient sans erreurs de dépendances."""
        sync_worker = SyncHelloAssoWorker("file_id_123", "campaign_slug")
        self.assertIsNotNone(sync_worker)
        self.assertTrue(isinstance(sync_worker, QThread))

        gen_worker = GenerateAttestationsWorker()
        self.assertIsNotNone(gen_worker)
        self.assertTrue(isinstance(gen_worker, QThread))

        email_worker = SendEmailCampaignWorker("Subject", "Body", [])
        self.assertIsNotNone(email_worker)
        self.assertTrue(isinstance(email_worker, QThread))

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester les workers asynchrones")
    def test_documents_page_auto_open_and_folder_btn(self):
        """Vérifie que DocumentsPage permet d'ouvrir le dossier et d'ouvrir automatiquement une attestation unique."""
        from unittest.mock import patch, MagicMock
        from PySide6.QtWidgets import QApplication
        from presentation.pages.documents import DocumentsPage
        from domain.models import Member
        
        app = QApplication.instance() or QApplication([])
        page = DocumentsPage()
        self.assertIsNotNone(page.open_folder_btn)
        
        # Mock de os.startfile et os.path.exists
        with patch("os.startfile") as mock_startfile, \
             patch("os.path.exists", return_value=True):
             
            # Test 1 : Clic sur ouvrir le dossier
            page.open_attestation_folder()
            mock_startfile.assert_called_once()
            
            # Réinitialiser le mock
            mock_startfile.reset_mock()
            
            # Test 2 : Fin de génération avec une seule attestation
            member = Member(
                order_ref="12345", order_date="2026-08-01", status="Validated", 
                tarif_name="Adulte", amount=246.0, user_last_name="Martin", 
                user_first_name="Paul", payer_first_name="Jean", payer_last_name="Martin", 
                payer_email="test@test.com"
            )
            page.last_selected_members = [member.to_dict()]
            page.format_combo.setCurrentIndex(0) # PDF
            
            page.on_finished(generated=1, skipped=0, errors=0)
            mock_startfile.assert_called_once()
            
            # S'assurer que le fichier ciblé est le PDF de Martin Paul
            args, _ = mock_startfile.call_args
            target_path = args[0]
            self.assertTrue(target_path.endswith("Attestation_MARTIN_Paul_12345.pdf"))

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_exports_page_template_folder_btn(self):
        """Vérifie que ExportsPage contient le bouton dossier modèle et qu'il ouvre le bon dossier."""
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication
        from presentation.pages.exports import ExportsPage
        from paths import ROOT_DIR
        
        app = QApplication.instance() or QApplication([])
        page = ExportsPage()
        
        self.assertIsNotNone(page.template_folder_btn)
        self.assertIsNotNone(page.template_name_lbl)
        self.assertEqual(page.template_name_lbl.text(), "Modèle utilisé : <b>Cours - Template-Vide.xlsx</b>")
        
        # Mock de os.startfile et os.path.exists
        with patch("os.startfile") as mock_startfile, \
             patch("os.path.exists", return_value=True) as mock_exists:
             
            page.open_template_folder()
            mock_exists.assert_called_once_with(os.path.join(ROOT_DIR, "liste adhérent"))
            mock_startfile.assert_called_once_with(os.path.join(ROOT_DIR, "liste adhérent"))

if __name__ == "__main__":
    unittest.main()
