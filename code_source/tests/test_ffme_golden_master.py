import os
import sys
import unittest
import hashlib
import shutil
import sqlite3
import tempfile
import pathlib

# Ajustement du chemin pour importer les modules depuis 'src'
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

# Racine du projet (parent de code_source/)
ROOT_PROJET = os.path.dirname(os.path.dirname(_test_dir))
REFERENCE = os.path.join(_test_dir, "fixtures", "import_ffme_reference.csv")


class TestFFMEGoldenMaster(unittest.TestCase):
    """
    Test de non-régression octet à octet : l'export CSV FFME régénéré depuis
    un snapshot figé de database.db doit être STRICTEMENT identique au fichier
    de référence import_ffme_20260830_173135.csv.

    Ce test est le gate de validation de la migration BDD (phases 0 à 6).
    La fixture contient des données personnelles : elle est ignorée par git
    (voir .gitignore) et ne vit que sur le poste local.
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(REFERENCE):
            raise unittest.SkipTest(
                "Fixture de référence absente (tests/fixtures/import_ffme_reference.csv). "
                "Copier exports/ffme/import_ffme_20260830_173135.csv vers ce chemin pour activer le test."
            )

    def test_export_ffme_identique_reference(self):
        from infrastructure.sqlite_repository import SqliteRepository
        from create_excel import generate_ffme_csv

        db_live = os.path.join(ROOT_PROJET, "database.db")
        self.assertTrue(os.path.exists(db_live), "database.db introuvable à la racine du projet")

        tmpdir = tempfile.mkdtemp(prefix="alj_golden_test_")
        try:
            # 1. Snapshot cohérent de la base (API backup : inclut le contenu WAL)
            tmp_db = os.path.join(tmpdir, "database.db")
            uri_source = f"{pathlib.Path(db_live).as_uri()}?mode=ro"
            src = sqlite3.connect(uri_source, uri=True)
            dst = sqlite3.connect(tmp_db)
            src.backup(dst)
            dst.close()
            src.close()

            # 2. Chargement via le chemin applicatif réel, sur la copie uniquement
            ancien_path = SqliteRepository.get_db_path()
            SqliteRepository.set_db_path(tmp_db)
            try:
                raw_data = SqliteRepository.load_direct_data(season_filter="2026-2027")
            finally:
                SqliteRepository.set_db_path(ancien_path)
            self.assertTrue(raw_data, "Aucune donnée chargée depuis la copie de la base")

            # 3. Génération vers un chemin dédié (aucune écriture dans exports/)
            out_csv = os.path.join(tmpdir, "import_ffme_test.csv")
            generate_ffme_csv(raw_data, output_path=out_csv)

            # 4. Comparaison stricte octet à octet
            with open(out_csv, "rb") as f:
                genere = f.read()
            with open(REFERENCE, "rb") as f:
                reference = f.read()

            if genere != reference:
                self.fail(self._diagnostic(genere, reference))
            self.assertEqual(
                hashlib.sha256(genere).hexdigest(),
                hashlib.sha256(reference).hexdigest(),
                "L'export CSV FFME diffère de la référence (SHA-256).",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @staticmethod
    def _diagnostic(genere, reference):
        """Produit un diff lisible ligne/colonne en cas d'échec de la comparaison."""
        lignes_g = genere.decode("utf-8", "replace").splitlines()
        lignes_r = reference.decode("utf-8", "replace").splitlines()
        msg = [f"DIFF : {len(lignes_g)} lignes générées vs {len(lignes_r)} lignes de référence"]
        entetes = lignes_r[0].split(";") if lignes_r else []

        if len(lignes_g) != len(lignes_r):
            n = min(len(lignes_g), len(lignes_r))
            if lignes_g[:n] == lignes_r[:n]:
                sens = "en trop" if len(lignes_g) > len(lignes_r) else "manquantes"
                surplus = lignes_g[n:] if len(lignes_g) > len(lignes_r) else lignes_r[n:]
                msg.append(f"Les {n} premières lignes sont identiques ; "
                           f"{abs(len(lignes_g) - len(lignes_r))} ligne(s) {sens} :")
                for l in surplus[:5]:
                    msg.append(f"  {l[:130]}")
                return "\n".join(msg)

        for i, (a, b) in enumerate(zip(lignes_g, lignes_r)):
            if a != b:
                msg.append(f"Première différence à la ligne {i + 1} :")
                if i == 0:
                    msg.append(f"  entête générée  : {a}")
                    msg.append(f"  entête référence: {b}")
                else:
                    cols_a = a.split(";")
                    cols_b = b.split(";")
                    for j in range(max(len(cols_a), len(cols_b))):
                        va = cols_a[j] if j < len(cols_a) else "<absent>"
                        vb = cols_b[j] if j < len(cols_b) else "<absent>"
                        if va != vb:
                            nom = entetes[j] if j < len(entetes) else f"colonne {j}"
                            msg.append(f"  colonne '{nom}' : '{va}' vs attendu '{vb}'")
                break
        return "\n".join(msg)


if __name__ == "__main__":
    unittest.main()
