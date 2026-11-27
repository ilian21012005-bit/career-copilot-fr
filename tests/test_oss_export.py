"""Unit tests for the read-only zero-PII standalone OSS export verifier."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

JOB_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = JOB_ROOT / "scripts" / "verify_oss_export.py"


def _load_verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_oss_export", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VerifyOssExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.verifier = _load_verifier()

    def test_script_is_concise_under_300_lines(self) -> None:
        line_count = len(SCRIPT_PATH.read_text(encoding="utf-8").splitlines())
        self.assertLess(line_count, 300)

    def test_stage_export_excludes_private_and_monorepo_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src_repo"
            dest = Path(tmp) / "staged"
            (src / "src" / "career_copilot").mkdir(parents=True)
            (src / "src" / "career_copilot" / "__init__.py").write_text(
                '__version__ = "3.0.0"\n', encoding="utf-8"
            )
            (src / "tests").mkdir()
            (src / "tests" / "test_ok.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n",
                encoding="utf-8",
            )
            (src / "1-Job-etudiant").mkdir()
            (src / "1-Job-etudiant" / "cv.txt").write_text("private", encoding="utf-8")
            (src / "2-Stage-SOC").mkdir()
            (src / "2-Stage-SOC" / "notes.md").write_text("private", encoding="utf-8")
            (src / "3-Archives").mkdir()
            (src / "3-Archives" / "old.txt").write_text("private", encoding="utf-8")
            (src / "bot" / "data").mkdir(parents=True)
            (src / "bot" / "data" / "hellowork.db").write_bytes(b"sqlite")
            (src / "bot" / ".env").write_text("SECRET=1\n", encoding="utf-8")
            (src / "bot" / ".env.example").write_text("AI_ENABLED=0\n", encoding="utf-8")
            (src / "bot" / "dashboard_post_commerce.py").write_text("x = 1\n", encoding="utf-8")
            (src / "bot" / ("bot_" + "units.py")).write_text("x = 1\n", encoding="utf-8")
            (src / "bot" / "presets.py").write_text("PRESETS = {}\n", encoding="utf-8")

            count = self.verifier.stage_export(src, dest)
            self.assertGreaterEqual(count, 4)
            self.assertTrue((dest / "src" / "career_copilot" / "__init__.py").is_file())
            self.assertTrue((dest / "bot" / ".env.example").is_file())
            self.assertTrue((dest / "bot" / "presets.py").is_file())
            self.assertFalse((dest / "1-Job-etudiant").exists())
            self.assertFalse((dest / "2-Stage-SOC").exists())
            self.assertFalse((dest / "3-Archives").exists())
            self.assertFalse((dest / "bot" / "data").exists())
            self.assertFalse((dest / "bot" / ".env").exists())
            self.assertFalse((dest / "bot" / "dashboard_post_commerce.py").exists())
            self.assertFalse((dest / "bot" / ("bot_" + "units.py")).exists())
            self.assertEqual(self.verifier.scan_tree(dest), [])

    def test_scan_tree_flags_pii_paths_secrets_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dirty"
            root.mkdir()
            (root / "leak_path.py").write_text(
                'PATH = "/home/' + "mk/Projets/server-" + 'bots"\n', encoding="utf-8"
            )
            (root / "leak_coupling.py").write_text(
                'MOD = "Sites-' + 'commerces"\n', encoding="utf-8"
            )
            (root / "leak_pii.txt").write_text(
                "Contact: real.person@" + "gma" + "il.com / 06 23 " + "45 67 89\n",
                encoding="utf-8",
            )
            (root / "leak_key.txt").write_text(
                "-----BEGIN " + "RSA PRIVATE KEY-----\n", encoding="utf-8"
            )
            (root / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
            (root / "link.txt").symlink_to(root / "leak_pii.txt")

            findings = self.verifier.scan_tree(root)
            joined = "\n".join(findings)
            self.assertIn("chemin machine personnel", joined)
            self.assertIn("référence monorepo parent", joined)
            self.assertIn("couplage sous-projet externe", joined)
            self.assertIn("adresse email personnelle", joined)
            self.assertIn("numéro de téléphone personnel", joined)
            self.assertIn("clé privée détectée", joined)
            self.assertIn("fichier d'environnement interdit", joined)
            self.assertIn("lien symbolique interdit", joined)

    def test_scan_tree_allows_synthetic_examples_and_mail_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "clean"
            root.mkdir()
            (root / "example.py").write_text(
                'EMAIL = "alex.martin@example.org"\n'
                'PHONE = "06 00 00 00 00"\n'
                'IMAP_HOST = "imap.gmail.com"\n',
                encoding="utf-8",
            )
            self.assertEqual(self.verifier.scan_tree(root), [])

    def test_verify_export_runs_tests_on_synthetic_clean_and_dirty_trees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clean_repo = Path(tmp) / "clean_repo"
            (clean_repo / "src" / "demo_pkg").mkdir(parents=True)
            (clean_repo / "src" / "demo_pkg" / "__init__.py").write_text(
                "VALUE = 42\n", encoding="utf-8"
            )
            (clean_repo / "tests").mkdir()
            (clean_repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (clean_repo / "tests" / "test_demo.py").write_text(
                "import unittest\nimport demo_pkg\n"
                "class DemoTest(unittest.TestCase):\n"
                "    def test_val(self): self.assertEqual(demo_pkg.VALUE, 42)\n",
                encoding="utf-8",
            )
            ok_report = self.verifier.verify_export(source_root=clean_repo, run_tests=True)
            self.assertTrue(ok_report["ok"])
            self.assertEqual(ok_report["findings"], [])
            self.assertTrue(ok_report["tests_ok"])

            (clean_repo / "src" / "demo_pkg" / "bad.py").write_text(
                'LEAK = "/home/' + 'mk/secret"\n', encoding="utf-8"
            )
            bad_report = self.verifier.verify_export(source_root=clean_repo, run_tests=False)
            self.assertFalse(bad_report["ok"])
            self.assertTrue(bad_report["findings"])


if __name__ == "__main__":
    unittest.main()
