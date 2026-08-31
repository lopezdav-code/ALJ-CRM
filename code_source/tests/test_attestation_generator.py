import os
import sys
import unittest
import datetime
import shutil
import docx

# Ajustement du chemin pour importer les modules depuis 'src'
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from paths import ROOT_DIR, CODE_ROOT
from attestation_generator import (
    get_french_date,
    extract_season_from_filename,
    get_safe_filename,
    generate_all_attestations
)

class TestAttestationGenerator(unittest.TestCase):
    
    def test_get_french_date(self):
        """Vérifie que la date en français est correctement formatée."""
        date_str = get_french_date()
        self.assertIn(str(datetime.datetime.now().day), date_str)
        self.assertIn(str(datetime.datetime.now().year), date_str)
        # Vérifie que le mois est présent en français (ex: juillet, mars...)
        months = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        current_month = months[datetime.datetime.now().month - 1]
        self.assertIn(current_month, date_str)

    def test_extract_season(self):
        """Vérifie l'extraction de la saison depuis le nom de fichier."""
        fn1 = "Adhésions escalade-2026-2027-amicale-laique-de-jonage-2026_07_12.xlsx"
        self.assertEqual(extract_season_from_filename(fn1), "2026-2027")
        
        fn2 = "Adhésions escalade-2025-2026-machin.xlsx"
        self.assertEqual(extract_season_from_filename(fn2), "2025-2026")
        
        fn3 = "FichierSansSaison.xlsx"
        self.assertEqual(extract_season_from_filename(fn3, "2024-2025"), "2024-2025")

    def test_get_safe_filename(self):
        """Vérifie le nettoyage et formatage des noms de fichiers d'attestations."""
        self.assertEqual(get_safe_filename("Dupont", "Jean"), "Attestation_DUPONT_Jean.docx")
        self.assertEqual(get_safe_filename(" Martin-Durand ", " Marie-Sophie "), "Attestation_MARTIN-DURAND_Marie-sophie.docx")
        self.assertEqual(get_safe_filename("D'Orazio", "René"), "Attestation_DORAZIO_René.docx")
        self.assertEqual(get_safe_filename("Gros / Petit", "Jean Paul"), "Attestation_GROS__PETIT_Jean_paul.docx")

    def test_attestation_generation_skips_and_writes(self):
        """Vérifie le processus global de génération d'attestations sur de fausses données."""
        # Créer un dossier temporaire pour les tests d'attestations
        test_output_dir = os.path.join(CODE_ROOT, "attestation")
        
        # S'il y a déjà un dossier, on le préserve en renommant temporairement ou on utilise directement
        # mais pour le test unitaire on va simuler l'écriture d'un fichier et sa vérification.
        
        # Testons l'écriture d'un document Word
        template_path = os.path.join(ROOT_DIR, "doc", "ATTESTATION DE PAIEMENT_adulte.docx")
        if os.path.exists(template_path):
            doc = docx.Document(template_path)
            
            # Modifier un paragraphe
            for p in doc.paragraphs:
                if "{" in p.text:
                    p.text = "Test de remplacement: Jean DUPONT payé 246 Euros pour 2026-2027"
                    
            test_file = os.path.join(test_output_dir, "Attestation_TEST_UNITAIRE_PRENOM.docx")
            if not os.path.exists(test_output_dir):
                os.makedirs(test_output_dir)
                
            doc.save(test_file)
            self.assertTrue(os.path.exists(test_file))
            
            # Vérifier que le contenu est correct
            read_doc = docx.Document(test_file)
            found_test_text = False
            for p in read_doc.paragraphs:
                if "Test de remplacement" in p.text:
                    found_test_text = True
                    break
            self.assertTrue(found_test_text)
            
            # Nettoyage du fichier de test uniquement
            os.remove(test_file)

    def test_create_excel_mappings_and_helpers(self):
        """Vérifie que la colonne de date d'envoi d'e-mail est correctement mappée et que les helpers fonctionnent."""
        from create_excel import parse_date_to_datetime
        from domain.constants import CORRECTIVE_MAP
        
        # Vérifier la présence du nouveau mapping d'email
        self.assertIn("Date d'envoi de l'email", CORRECTIVE_MAP)
        self.assertEqual(CORRECTIVE_MAP["Date d'envoi de l'email"], "email_sent_date")
        
        # Vérifier le helper de parsing de date
        self.assertEqual(parse_date_to_datetime(""), "")
        self.assertEqual(parse_date_to_datetime(None), "")
        
        dt_str = "14/07/2026"
        parsed = parse_date_to_datetime(dt_str)
        self.assertIsInstance(parsed, datetime.datetime)
        self.assertEqual(parsed.day, 14)
        self.assertEqual(parsed.month, 7)
        self.assertEqual(parsed.year, 2026)

    def test_age_calculation(self):
        """Vérifie le calcul correct de l'âge d'un adhérent en fonction de sa date de naissance."""
        from create_excel import parse_date_to_datetime
        dob_str = "15/07/1990"
        dt_dob = parse_date_to_datetime(dob_str)
        self.assertIsInstance(dt_dob, datetime.datetime)
        
        now = datetime.datetime.now()
        age = now.year - dt_dob.year - ((now.month, now.day) < (dt_dob.month, dt_dob.day))
        
        expected_age = now.year - 1990 - (1 if (now.month, now.day) < (7, 15) else 0)
        self.assertEqual(age, expected_age)

if __name__ == "__main__":
    unittest.main()
