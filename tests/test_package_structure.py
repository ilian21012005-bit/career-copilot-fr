"""Structural invariants for the standalone career_copilot package."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import career_copilot.cli as career_cli

JOB_ROOT = Path(__file__).resolve().parents[1]
SRC_PKG = JOB_ROOT / "src" / "career_copilot"

_FORBIDDEN_CONTEXT_HACK = "sys.modules[" + "__name__]"
_FORBIDDEN_SYSTEMD_MOD = "bot_" + "units"
_FORBIDDEN_SITES = "Sites-" + "commerces"
_FORBIDDEN_BROAD_EXCEPT = "except " + "Exception"
_FORBIDDEN_SYSPATH = "sys.path." + "insert"


class PackageStructureTest(unittest.TestCase):
    def test_all_src_modules_are_modular_and_free_of_legacy_couplings(self) -> None:
        py_files = sorted(SRC_PKG.rglob("*.py"))
        self.assertGreaterEqual(len(py_files), 15)
        for path in py_files:
            content = path.read_text(encoding="utf-8")
            line_count = len(content.splitlines())
            self.assertLess(
                line_count,
                450,
                f"{path.relative_to(JOB_ROOT)} dépasse 450 lignes ({line_count})",
            )
            self.assertNotIn(
                _FORBIDDEN_CONTEXT_HACK,
                content,
                f"Context passing interdit dans {path.relative_to(JOB_ROOT)}",
            )
            self.assertNotIn(
                _FORBIDDEN_SYSTEMD_MOD,
                content,
                f"Couplage systemd interdit dans {path.relative_to(JOB_ROOT)}",
            )
            self.assertNotIn(
                _FORBIDDEN_BROAD_EXCEPT,
                content,
                f"except générique interdit dans {path.relative_to(JOB_ROOT)}",
            )
            self.assertNotIn(
                _FORBIDDEN_SYSPATH,
                content,
                f"Mutation sys.path interdite dans {path.relative_to(JOB_ROOT)}",
            )
            self.assertNotIn(
                _FORBIDDEN_SITES,
                content,
                f"Couplage externe interdit dans {path.relative_to(JOB_ROOT)}",
            )

    def test_decomposed_backend_packages_and_thin_shims(self) -> None:
        for pkg in ("assist", "cv", "sources", "interview"):
            pkg_dir = SRC_PKG / pkg
            self.assertTrue(
                (pkg_dir / "__init__.py").is_file(),
                f"Sous-paquet manquant : {pkg_dir.relative_to(JOB_ROOT)}",
            )
            self.assertGreaterEqual(len(list(pkg_dir.glob("*.py"))), 4)

        shims = (
            JOB_ROOT / "bot" / "hellowork" / "assist_apply.py",
            JOB_ROOT / "bot" / "hellowork" / "cv_personalize.py",
            JOB_ROOT / "bot" / "sources_registry.py",
            JOB_ROOT / "bot" / "interview_prep.py",
        )
        for shim in shims:
            line_count = len(shim.read_text(encoding="utf-8").splitlines())
            self.assertLess(
                line_count,
                350,
                f"Shim trop volumineux : {shim.relative_to(JOB_ROOT)} ({line_count} lignes)",
            )

    def test_cli_daemon_subcommand_invokes_bot_daemon_with_flags(self) -> None:
        recorded: list[tuple[str, list[str]]] = []

        def fake_exec(exe: str, argv: list[str]) -> None:
            recorded.append((exe, argv))

        with mock.patch("career_copilot.cli.os.execv", side_effect=fake_exec):
            rc = career_cli.main(["daemon", "--skip-initial", "--time", "06:30,12:00"])

        self.assertEqual(rc, 0)
        self.assertEqual(len(recorded), 1)
        exe, argv = recorded[0]
        self.assertEqual(exe, sys.executable)
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("/bot/daemon.py"))
        self.assertEqual(argv[2:], ["--time", "06:30,12:00", "--skip-initial"])


if __name__ == "__main__":
    unittest.main()
