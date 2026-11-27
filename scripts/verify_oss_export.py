"""Read-only zero-PII standalone OSS export verifier for `career-copilot-fr`.

Stages a clean temporary export into a TemporaryDirectory, scans every staged
file for personal PII, secrets, forbidden machine paths, and monorepo couplings,
and runs `tests/` against the staged tree. Exits 0 only when 100% clean.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

EXCLUDED_TOP_DIRS: frozenset[str] = frozenset(
    {
        "1-Job-etudiant",
        "2-Stage-SOC",
        "3-Archives",
        ".cursor",
        ".git",
        ".venv",
        "node_modules",
    }
)
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
)
EXCLUDED_BOT_SUBDIRS: frozenset[str] = frozenset({"data", "tests", "static"})
EXCLUDED_FILES: frozenset[str] = frozenset(
    {
        "candidate-profile.json",
        "dashboard_post_commerce.py",
        "bot_" + "units.py",
        "Dockerfile.dockerignore",
        "app.py",
        "candidate_config.py",
        "dashboard_analytics.py",
        "dashboard_data.py",
        "dashboard_get_applications.py",
        "dashboard_get_documents.py",
        "dashboard_get_misc.py",
        "dashboard_get_reports.py",
        "dashboard_http.py",
        "dashboard_incidents.py",
        "dashboard_post.py",
        "dashboard_post_applications.py",
        "dashboard_post_system.py",
        "dashboard_routes.py",
        "dashboard_setup.py",
        "mission_control.html",
        "notifier.py",
        "runtime_hooks.py",
        "uv.lock",
    }
)
FORBIDDEN_SUFFIXES: tuple[str, ...] = (
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite3",
    ".sqlite-wal",
    ".sqlite-shm",
    ".pyc",
    ".pyo",
    ".pdf",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
)

# Built via concatenation so this verifier never self-matches when staged.
_FORBIDDEN_LITERALS: tuple[tuple[str, str], ...] = (
    ("/home/" + "mk", "chemin machine personnel"),
    ("server-" + "bots", "référence monorepo parent"),
    ("Sites-" + "commerces", "couplage sous-projet externe"),
    ("bot_" + "units", "couplage systemd externe"),
    ("Zero" + "Strike", "marqueur personnel"),
    ("Data-" + "Tricks", "marqueur personnel"),
    ("IUT d'" + "Orsay", "marqueur personnel"),
    ("IUT d\u2019" + "Orsay", "marqueur personnel"),
    ("Universit\u00e9 Paris-" + "Saclay", "marqueur personnel"),
)

_PRIVATE_KEY_RE = re.compile(r"BEGIN " + r"(?:[A-Z0-9]+ )*PRIVATE KEY")
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgh" + r"p_[A-Za-z0-9]{4,}"), "jeton GitHub"),
    (re.compile(r"\bsk" + r"-[A-Za-z0-9_-]{8,}"), "clé API privée"),
    (re.compile(r"\bxox" + r"b-[A-Za-z0-9-]{4,}"), "jeton Slack"),
)
_PERSONAL_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@(?:gma"
    + r"il\.com|outlo"
    + r"ok\.(?:com|fr)|hotma"
    + r"il\.(?:com|fr)|yaho"
    + r"o\.(?:com|fr)|proton"
    + r"(?:mail)?\.(?:me|com)|universite-paris-"
    + r"saclay\.fr|u-psud\.fr)\b",
    re.IGNORECASE,
)
_FR_MOBILE_RE = re.compile(r"(?<!\d)(?:(?:\+33|0033)[\s.-]*[67]|0[67])(?:[\s.-]?\d{2}){4}(?!\d)")
_SYNTHETIC_PHONE_DIGITS: frozenset[str] = frozenset(
    {
        "0600000000",
        "0700000000",
        "0612345678",
        "0611223344",
        "0655667788",
        "0655443322",
        "0699887766",
    }
)


def _is_env_secret_name(name: str) -> bool:
    return name != ".env.example" and (name == ".env" or name.startswith(".env."))


def _should_exclude(relative: Path) -> bool:
    parts = relative.parts
    if not parts or parts[0] in EXCLUDED_TOP_DIRS:
        return True
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return True
    if len(parts) >= 2 and parts[0] == "bot" and parts[1] in EXCLUDED_BOT_SUBDIRS:
        return True
    name = relative.name
    if _is_env_secret_name(name) or name.lower().endswith(FORBIDDEN_SUFFIXES):
        return True
    return name in EXCLUDED_FILES and (len(parts) == 1 or parts[0] == "bot")


def stage_export(source_root: Path, dest_root: Path) -> int:
    """Copy a clean standalone OSS export from `source_root` into `dest_root`."""
    copied = 0
    for path in sorted(source_root.rglob("*")):
        relative = path.relative_to(source_root)
        if _should_exclude(relative) or path.is_symlink() or not path.is_file():
            continue
        target = dest_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target, follow_symlinks=False)
        copied += 1
    return copied


def _scan_text_content(relative: Path, text: str) -> list[str]:
    findings: list[str] = []
    lowered = text.lower()
    for literal, label in _FORBIDDEN_LITERALS:
        if literal.lower() in lowered:
            findings.append(f"{label} ({literal}) : {relative}")
    if _PRIVATE_KEY_RE.search(text):
        findings.append(f"clé privée détectée : {relative}")
    for pattern, label in _SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(f"{label} détecté : {relative}")
    for match in _PERSONAL_EMAIL_RE.findall(text):
        findings.append(f"adresse email personnelle ({match}) : {relative}")
    for raw_phone in _FR_MOBILE_RE.findall(text):
        digits = re.sub(r"\D", "", raw_phone)
        if digits.startswith("33") and len(digits) == 11:
            digits = "0" + digits[2:]
        elif digits.startswith("0033") and len(digits) == 13:
            digits = "0" + digits[4:]
        if digits not in _SYNTHETIC_PHONE_DIGITS:
            findings.append(f"numéro de téléphone personnel ({raw_phone}) : {relative}")
    return findings


def scan_tree(root: Path) -> list[str]:
    """Scan a staged OSS tree for PII, secrets, forbidden paths, and disallowed files."""
    findings: list[str] = []
    forbidden_names = {"dashboard_post_commerce.py", "bot_" + "units.py", "candidate-profile.json"}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            findings.append(f"lien symbolique interdit : {relative}")
            continue
        if not path.is_file():
            continue
        name = path.name
        if relative.parts[0] in EXCLUDED_TOP_DIRS:
            findings.append(f"répertoire exclu présent : {relative}")
        if relative.parts[:2] == ("bot", "data"):
            findings.append(f"répertoire runtime bot/data présent : {relative}")
        if _is_env_secret_name(name):
            findings.append(f"fichier d'environnement interdit : {relative}")
        if name.lower().endswith(FORBIDDEN_SUFFIXES):
            findings.append(f"extension interdite : {relative}")
        if name in forbidden_names:
            findings.append(f"fichier interdit présent : {relative}")
        try:
            text = path.read_bytes().decode("utf-8", errors="ignore")
        except OSError as exc:
            findings.append(f"fichier illisible ({type(exc).__name__}) : {relative}")
            continue
        findings.extend(_scan_text_content(relative, text))
    return findings


def run_staged_tests(
    staged_root: Path, *, python_executable: str | None = None
) -> tuple[bool, str]:
    """Run `tests/` against the staged standalone export in an isolated environment."""
    exe = python_executable or sys.executable
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(staged_root),
        "PYTHONPATH": str(staged_root / "src"),
        "DISABLE_AI": "1",
        "AI_ENABLED": "0",
        "AUTOPILOT_SEND": "0",
        "STANDALONE_CAREER_MODE": "1",
    }
    proc = subprocess.run(  # noqa: S603
        [exe, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"],
        cwd=staged_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return proc.returncode == 0, (proc.stdout + "\n" + proc.stderr).strip()


def verify_export(
    source_root: Path | None = None,
    *,
    run_tests: bool = True,
    python_executable: str | None = None,
) -> dict[str, Any]:
    """Stage, scan, and optionally test a temporary standalone OSS export."""
    resolved = Path(source_root).resolve() if source_root else Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="career-copilot-oss-verify-") as tmp:
        staged = Path(tmp) / "career-copilot-fr"
        staged.mkdir(parents=True, exist_ok=True)
        staged_files = stage_export(resolved, staged)
        findings = scan_tree(staged)
        tests_ok, tests_output = (
            run_staged_tests(staged, python_executable=python_executable)
            if run_tests
            else (True, "")
        )
    return {
        "ok": not findings and tests_ok,
        "staged_files": staged_files,
        "findings": findings,
        "tests_ok": tests_ok,
        "tests_output": tests_output,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Vérificateur lecture seule d'export OSS zero-PII pour career-copilot-fr."
    )
    parser.add_argument("--source", type=Path, default=None, help="Racine du projet à exporter.")
    parser.add_argument("--skip-tests", action="store_true", help="Ne pas lancer tests/.")
    parser.add_argument("--json", action="store_true", help="Afficher le rapport en JSON.")
    args = parser.parse_args(argv)
    report = verify_export(source_root=args.source, run_tests=not args.skip_tests)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "CLEAN" if report["ok"] else "FAILED"
        print(
            f"[verify_oss_export] {status} — {report['staged_files']} fichier(s) stagés, "
            f"{len(report['findings'])} anomalie(s), tests={'OK' if report['tests_ok'] else 'FAIL'}."
        )
        for finding in report["findings"]:
            print(f"  - {finding}")
        if not report["tests_ok"] and report["tests_output"]:
            print(report["tests_output"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
