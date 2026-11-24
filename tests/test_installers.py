import importlib.util
import json
import re
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("macos_setup", ROOT / "install/macos_setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class MacSetupTests(unittest.TestCase):
    def profile(self, root, name="Profiles/a.default"):
        profile = root / name
        (profile / "extensions").mkdir(parents=True)
        (profile / "prefs.js").write_text('user_pref("unrelated.option", true);\nuser_pref("extensions.zotero.hjfySplitReaderCN.aiBaseURL", "https://example.invalid/v1");\n', "utf-8")
        (profile / "extensions" / (setup.ADDON_ID + ".xpi")).write_bytes(b"fixture")
        return profile

    def test_default_and_absolute_profiles(self):
        with tempfile.TemporaryDirectory(dir=None) as folder:
            root = Path(folder)
            first = self.profile(root)
            second = self.profile(root, "Profiles/b.default")
            (root / "profiles.ini").write_text('[Profile0]\nPath=Profiles/a.default\nIsRelative=1\nDefault=1\n[Profile1]\nPath=Profiles/b.default\nIsRelative=1\n', "utf-8")
            self.assertEqual(setup.choose_profile(root), first.resolve())
            self.assertEqual(setup.choose_profile(root, str(second)), second.resolve())

    def test_configure_preserves_provider_and_only_changes_own_addon(self):
        with tempfile.TemporaryDirectory(dir=None) as folder:
            root = Path(folder)
            profile = self.profile(root)
            config = {"addons":[{"id": setup.ADDON_ID, "applyBackgroundUpdates":1}, {"id":"other-plugin", "applyBackgroundUpdates":1}]}
            (profile / "extensions.json").write_text(json.dumps(config), "utf-8")
            application = root / "Library/Application Support/HJFY AI Reader 空格"
            backup = setup.configure_profile(profile, application, "synthetic-local-token")
            prefs = (profile / "prefs.js").read_text("utf-8")
            self.assertIn('user_pref("unrelated.option", true);', prefs)
            self.assertIn('"https://example.invalid/v1"', prefs)
            self.assertIn("synthetic-local-token", prefs)
            match = re.search(r'user_pref\("extensions.zotero.hjfySplitReaderCN.aiPythonPath", (.*)\);', prefs)
            self.assertEqual(json.loads(match.group(1)), str(application / ".venv/bin/python3"))
            self.assertTrue((backup / "prefs.js").exists())
            changed = json.loads((profile / "extensions.json").read_text("utf-8"))
            self.assertEqual(changed["addons"][0]["applyBackgroundUpdates"], 0)
            self.assertEqual(changed["addons"][1], config["addons"][1])

    def test_missing_plugin_refused_before_profile_write(self):
        with tempfile.TemporaryDirectory(dir=None) as folder:
            root = Path(folder)
            (root / "prefs.js").write_text("original", "utf-8")
            with self.assertRaises(RuntimeError):
                setup.configure_profile(root, root / "application", "fixture")
            self.assertEqual((root / "prefs.js").read_text("utf-8"), "original")

    def test_python_version_bounds(self):
        self.assertFalse(setup.supported_python((3,9)))
        self.assertTrue(setup.supported_python((3,10)))
        self.assertTrue(setup.supported_python((3,13)))
        self.assertFalse(setup.supported_python((3,14)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
