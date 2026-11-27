"""Standalone console entrypoint (`career-copilot`) for migrations, health, and setup."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from career_copilot import __version__
from career_copilot.api.app import FASTAPI_AVAILABLE, run_server
from career_copilot.api.service import CareerApiService
from career_copilot.db.migrations import ensure_migrated
from career_copilot.profile import build_example_profile_v2, save_profile_payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="career-copilot",
        description="CLI standalone Career Copilot FR (SQLite WAL, profil v2, API FastAPI).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Répertoire de données local (défaut : CAREER_COPILOT_DATA_DIR ou bot/data).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="Appliquer les migrations SQLite WAL (PRAGMA user_version).")
    health_cmd = sub.add_parser(
        "health", help="Afficher l'état JSON local (WAL, version schéma, profil)."
    )
    health_cmd.add_argument("--json", action="store_true", help="Sortie JSON explicite.")
    quality_cmd = sub.add_parser("quality", help="Afficher l'audit qualité lecture seule (JSON).")
    quality_cmd.add_argument("--json", action="store_true", help="Sortie JSON explicite.")
    init_cmd = sub.add_parser("init-example", help="Créer un profil v2 fictif zero-PII (0600).")
    init_cmd.add_argument("--preset", default=None, help="Identifiant de preset métier.")
    sub.add_parser("serve", help="Démarrer l'API FastAPI/Uvicorn sur 127.0.0.1:8765.")
    daemon_cmd = sub.add_parser(
        "daemon", help="Démarrer le daemon planifié multi-sources et HelloWork."
    )
    daemon_cmd.add_argument(
        "--send",
        action="store_true",
        help="Activer les envois automatiques réels (sinon dry-run).",
    )
    daemon_cmd.add_argument(
        "--time",
        default=None,
        help="Créneau(x) quotidien(s) HH:MM ou HH:MM,HH:MM,...",
    )
    daemon_cmd.add_argument(
        "--skip-initial",
        action="store_true",
        help="Ne pas exécuter de cycle immédiat au démarrage.",
    )
    return parser


def _resolve_daemon_script() -> Path:
    repo_script = Path(__file__).resolve().parents[2] / "bot" / "daemon.py"
    if repo_script.is_file():
        return repo_script
    cwd_script = Path.cwd() / "bot" / "daemon.py"
    if cwd_script.is_file():
        return cwd_script
    raise FileNotFoundError(f"Script daemon introuvable : {repo_script}")


def _run_daemon(
    args: argparse.Namespace,
    *,
    exec_fn: Callable[[str, list[str]], object] | None = None,
) -> int:
    daemon_script = _resolve_daemon_script()
    forward_args: list[str] = []
    if args.send:
        forward_args.append("--send")
    if args.time:
        forward_args.extend(["--time", str(args.time)])
    if args.skip_initial:
        forward_args.append("--skip-initial")
    launcher = os.execv if exec_fn is None else exec_fn
    launcher(sys.executable, [sys.executable, str(daemon_script), *forward_args])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "daemon":
        return _run_daemon(args)

    data_dir = args.data_dir or (Path(__file__).resolve().parents[2] / "bot" / "data")

    if args.command == "migrate":
        version = ensure_migrated(data_dir / "hellowork.db")
        print(json.dumps({"ok": True, "schema_version": version}, ensure_ascii=False))
        return 0

    if args.command == "health":
        service = CareerApiService(data_dir=data_dir)
        health = service.healthz()
        payload = health.model_dump()
        payload["fastapi_available"] = FASTAPI_AVAILABLE
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if health.status == "error" else 0

    if args.command == "quality":
        service = CareerApiService(data_dir=data_dir)
        quality = service.quality_summary()
        print(json.dumps(quality.model_dump(), ensure_ascii=False, indent=2))
        has_critical = any(issue.severity == "critical" for issue in quality.issues)
        return 1 if has_critical else 0

    if args.command == "init-example":
        example = build_example_profile_v2(preset_id=args.preset)
        cfg = save_profile_payload(example, path=data_dir / "candidate-profile.json")
        print(
            json.dumps(
                {
                    "ok": True,
                    "profile_file": str(cfg.profile_file),
                    "preset": cfg.preset_id,
                    "contracts": list(cfg.contracts),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "serve":
        run_server()
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
