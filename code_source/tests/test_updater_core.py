import os
import sys
import zipfile
import unittest
from unittest.mock import patch

# Ajustement du chemin pour importer launcher/ et src/
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
_launcher_dir = os.path.join(os.path.dirname(_test_dir), "launcher")
for _p in (_src_dir, _launcher_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import updater_core as uc


def make_zip(zip_path, files, top_dir=None):
    """Crée un zip de test ; top_dir=... encapsule dans un dossier racine unique."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in files.items():
            zf.writestr(f"{top_dir}/{name}" if top_dir else name, content)


class TestVersions(unittest.TestCase):

    def test_parse_version(self):
        self.assertEqual(uc.parse_version("v2.0.10"), (2, 0, 10))
        self.assertEqual(uc.parse_version("2.0.9"), (2, 0, 9))
        self.assertEqual(uc.parse_version("2.0"), (2, 0))
        self.assertIsNone(uc.parse_version("deux"))
        self.assertIsNone(uc.parse_version(""))
        self.assertIsNone(uc.parse_version(None))

    def test_is_newer(self):
        self.assertTrue(uc.is_newer("2.0.10", "2.0.9"))
        self.assertTrue(uc.is_newer("v2.1.0", "2.0.99"))
        self.assertFalse(uc.is_newer("2.0.9", "2.0.9"))
        self.assertFalse(uc.is_newer("2.0.8", "2.0.9"))
        self.assertFalse(uc.is_newer("inconnu", "2.0.9"))
        self.assertFalse(uc.is_newer("2.0.10", "inconnu"))


class TestReleaseAssets(unittest.TestCase):

    RELEASE = {
        "tag_name": "v2.0.9",
        "assets": [
            {"name": "ALJ_Portable_v2.0.9.zip", "browser_download_url": "http://x/portable.zip"},
            {"name": "alj_source_v2.0.9.zip", "browser_download_url": "http://x/src.zip", "size": 1024},
            {"name": "SHA256SUMS.txt", "browser_download_url": "http://x/sums.txt"},
        ],
    }

    def test_release_version(self):
        self.assertEqual(uc.release_version(self.RELEASE), "2.0.9")
        self.assertEqual(uc.release_version({}), "")

    def test_pick_source_asset_exact(self):
        asset = uc.pick_source_asset(self.RELEASE, "2.0.9")
        self.assertEqual(asset["name"], "alj_source_v2.0.9.zip")

    def test_pick_source_asset_none(self):
        release = {"tag_name": "v1.0.0", "assets": [{"name": "autre.txt"}]}
        self.assertIsNone(uc.pick_source_asset(release, "1.0.0"))

    def test_fetch_latest_release(self):
        release_payload = self.RELEASE

        class FakeResponse:
            status_code = 200
            def json(self):
                return release_payload
        with patch("updater_core.requests.get", return_value=FakeResponse()) as mock_get:
            release = uc.fetch_latest_release("owner/repo")
        self.assertEqual(release["tag_name"], "v2.0.9")
        self.assertIn("repos/owner/repo/releases/latest", mock_get.call_args[0][0])


class TestChecksums(unittest.TestCase):

    def test_parse_sha256sums(self):
        text = "# commentaire\nabc123  *paquet.zip\ndef456  autre.zip\n"
        sums = uc.parse_sha256sums(text)
        self.assertEqual(sums, {"paquet.zip": "abc123", "autre.zip": "def456"})

    def test_verify_download(self):
        import hashlib
        tmpdir = os.path.join(_test_dir, "tmp_updater_checksum")
        os.makedirs(tmpdir, exist_ok=True)
        try:
            zip_path = os.path.join(tmpdir, "alj_source_v1.0.0.zip")
            with open(zip_path, "wb") as f:
                f.write(b"contenu de test")
            digest = hashlib.sha256(b"contenu de test").hexdigest()

            self.assertTrue(uc.verify_download(zip_path, f"{digest}  alj_source_v1.0.0.zip"))
            self.assertFalse(uc.verify_download(zip_path, f"{'0' * 64}  alj_source_v1.0.0.zip"))
            # Pas de sommes disponibles -> on ne bloque pas
            self.assertTrue(uc.verify_download(zip_path, ""))
        finally:
            for name in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, name))
            os.rmdir(tmpdir)


class TestExtractionAndSwap(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp(prefix="alj_updater_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_extract_zip_flat_with_root_folder(self):
        zip_path = os.path.join(self.root, "src.zip")
        make_zip(zip_path, {"VERSION": "2.0.9", "src/app.py": "print('ok')"}, top_dir="code_source")
        dest = os.path.join(self.root, "app_new")
        uc.extract_zip_flat(zip_path, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, "VERSION")))
        self.assertTrue(os.path.isfile(os.path.join(dest, "src", "app.py")))

    def test_extract_zip_flat_without_root_folder(self):
        zip_path = os.path.join(self.root, "src.zip")
        make_zip(zip_path, {"VERSION": "2.0.9", "requirements.txt": "requests"})
        dest = os.path.join(self.root, "app_new")
        uc.extract_zip_flat(zip_path, dest)
        self.assertTrue(os.path.isfile(os.path.join(dest, "requirements.txt")))

    def test_swap_keeps_previous_version(self):
        app_dir = os.path.join(self.root, "app")
        new_dir = os.path.join(self.root, "app_new")
        os.makedirs(app_dir)
        os.makedirs(new_dir)
        with open(os.path.join(app_dir, "ancien.txt"), "w") as f:
            f.write("old")
        with open(os.path.join(new_dir, "nouveau.txt"), "w") as f:
            f.write("new")

        uc.swap_app_folders(self.root)

        self.assertTrue(os.path.isfile(os.path.join(app_dir, "nouveau.txt")))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "app_old", "ancien.txt")))
        self.assertFalse(os.path.exists(new_dir))

    def test_swap_rolls_back_on_failure(self):
        app_dir = os.path.join(self.root, "app")
        new_dir = os.path.join(self.root, "app_new")
        os.makedirs(app_dir)
        os.makedirs(new_dir)
        with open(os.path.join(app_dir, "ancien.txt"), "w") as f:
            f.write("old")
        with open(os.path.join(new_dir, "nouveau.txt"), "w") as f:
            f.write("new")

        # Le 2e os.rename (app_new -> app) échoue, le 3e (rollback old -> app) réussit
        with patch("updater_core.os.rename", side_effect=[None, OSError("verrou"), None]):
            with self.assertRaises(OSError):
                uc.swap_app_folders(self.root)

        self.assertTrue(os.path.isfile(os.path.join(app_dir, "ancien.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "app_old")))

    def test_rollback_to_previous(self):
        app_dir = os.path.join(self.root, "app")
        old_dir = os.path.join(self.root, "app_old")
        os.makedirs(app_dir)
        os.makedirs(old_dir)
        with open(os.path.join(app_dir, "cassé.txt"), "w") as f:
            f.write("broken")
        with open(os.path.join(old_dir, "bonne.txt"), "w") as f:
            f.write("good")

        uc.rollback_to_previous(self.root)

        self.assertTrue(os.path.isfile(os.path.join(app_dir, "bonne.txt")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, "app_broken")))

    def test_sanity_check_app(self):
        app_dir = os.path.join(self.root, "app_new")
        src_dir = os.path.join(app_dir, "src")
        os.makedirs(src_dir)
        with open(os.path.join(app_dir, "VERSION"), "w") as f:
            f.write("2.0.9")
        with open(os.path.join(src_dir, "bon.py"), "w") as f:
            f.write("x = 1\n")
        uc.sanity_check_app(app_dir)  # Ne doit pas lever

        with open(os.path.join(src_dir, "cassé.py"), "w") as f:
            f.write("def (:(\n")
        with self.assertRaises(RuntimeError):
            uc.sanity_check_app(app_dir)


class TestStateAndPip(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp(prefix="alj_updater_state_")
        self.app_dir = os.path.join(self.root, "app")
        os.makedirs(self.app_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_read_app_version(self):
        with open(os.path.join(self.app_dir, "VERSION"), "w") as f:
            f.write("2.0.8\n")
        self.assertEqual(uc.read_app_version(self.app_dir), "2.0.8")
        self.assertEqual(uc.read_app_version(os.path.join(self.root, "inexistant")), "0.0.0")

    def test_pip_sync_skips_when_requirements_unchanged(self):
        with open(os.path.join(self.app_dir, "requirements.txt"), "w") as f:
            f.write("requests==2.34.2\n")
        uc.save_state(self.root, {"requirements_sha256": uc.requirements_sha256(self.app_dir)})
        # runtime_python inexistant : ne doit PAS être appelé car rien n'a changé
        self.assertTrue(uc.pip_sync("INEXISTANT/python.exe", self.app_dir, self.root))

    def test_pip_sync_detects_change_and_fails_soft(self):
        with open(os.path.join(self.app_dir, "requirements.txt"), "w") as f:
            f.write("requests==2.34.2\n")
        uc.save_state(self.root, {"requirements_sha256": "ancien"})
        # runtime inexistant -> subprocess échoue -> False mais sans lever
        self.assertFalse(uc.pip_sync("INEXISTANT/python.exe", self.app_dir, self.root))

    def test_load_config_defaults(self):
        config = uc.load_config(self.root)
        self.assertEqual(config["repo"], uc.DEFAULT_CONFIG["repo"])
        import json
        with open(os.path.join(self.root, "updater.json"), "w", encoding="utf-8") as f:
            json.dump({"repo": "autre/repo"}, f)
        self.assertEqual(uc.load_config(self.root)["repo"], "autre/repo")


if __name__ == "__main__":
    unittest.main()
