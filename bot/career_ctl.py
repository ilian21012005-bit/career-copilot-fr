"""CLI d'onboarding universel pour l'instance Job-Etudiant.

Sous-commandes :
- ``presets``            : catalogue des filières et des métropoles étudiantes.
- ``init``               : création interactive ou non d'un profil candidat v2.
- ``demo``               : profil + cinq offres de démonstration.
- ``doctor``             : diagnostic hors-ligne de l'environnement.
- ``export-standalone``  : distribution autonome nettoyée de tout secret.

Aucun secret réel, aucune donnée personnelle et aucun fichier ``data/`` n'est
lu ou copié par ce module. Le profil candidat reste la seule donnée locale
manipulée, et il est écrit atomiquement en mode ``0600``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import candidate_config
import presets
from hellowork import store

BOT_DIR = Path(__file__).resolve().parent
JOB_ROOT = BOT_DIR.parent
PROJECT_ROOT = JOB_ROOT.parent

DEFAULT_INIT_PRESET = "software_data"
DEFAULT_CITIES = ("lyon", "paris")
DEFAULT_CONTRACTS = ("stage", "alternance")
DEFAULT_NAME = "Alex Martin"
DEFAULT_EMAIL = "alex.martin@example.org"
DEFAULT_PHONE = "06 00 00 00 00"
DEFAULT_LEVEL = "Bac+3"
DEFAULT_SCHOOL = "Université Exemple"
MIN_PYTHON = (3, 12)

OPTIONAL_ENV_VARS: tuple[str, ...] = (
    "FT_CLIENT_ID",
    "GMAIL_ADDRESS",
    "TELEGRAM_BOT_TOKEN",
    "AI_ENABLED",
    "AUTOPILOT_SEND",
)

EXPORT_DIR_NAME = "Job-Etudiant"
EXPORT_BOT_SUBDIR = "bot"
EXPORT_REQUIRED_FILES: tuple[str, ...] = (
    "Dockerfile",
    "docker-compose.yml",
    "requirements-standalone.txt",
)
EXPORT_ROOT_SUFFIXES: tuple[str, ...] = (".py", ".html")
EXPORT_TREE_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".html",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".cfg",
    ".ini",
    ".css",
    ".js",
)
EXPORT_FORBIDDEN_SUFFIXES: tuple[str, ...] = (
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite3",
    ".sqlite-wal",
    ".sqlite-shm",
    ".pyc",
    ".pdf",
    ".docx",
)
EXPORT_IGNORED_DIRS: tuple[str, ...] = (
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".git",
)

ENV_EXAMPLE_CONTENT = """\
# Distribution autonome Job-Etudiant — aucun secret réel n'est fourni.
# Copier ce fichier vers .env puis compléter localement (ne jamais committer .env).
STANDALONE_CAREER_MODE=1
MISSION_CONTROL_HOST=127.0.0.1
MISSION_CONTROL_PORT=8765

# Sécurité : aucun envoi automatique par défaut.
AUTOPILOT_SEND=0
AI_ENABLED=0

# Variables optionnelles (laisser vides si non utilisées).
FT_CLIENT_ID=
FT_CLIENT_SECRET=
GMAIL_ADDRESS=your.address@example.com
GMAIL_APP_PASSWORD=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
"""

# Motifs construits par concaténation pour que ce module ne se détecte pas
# lui-même lors du scan d'une distribution exportée.
_PRIVATE_KEY_RE = re.compile(r"BEGIN " + r"(?:[A-Z0-9]+ )*PRIVATE KEY")
_TOKEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgh" + r"p_[A-Za-z0-9]{4,}"), "jeton GitHub"),
    (re.compile(r"\bsk" + r"-[A-Za-z0-9_-]{4,}"), "clé API privée"),
    (re.compile(r"\bxox" + r"b-[A-Za-z0-9-]{4,}"), "jeton Slack"),
)
_GMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@gma" + r"il\.com", re.IGNORECASE)


class ExportLeakError(RuntimeError):
    """Fuite détectée dans une distribution exportée."""


# --------------------------------------------------------------------------
# Helpers profil / présets
# --------------------------------------------------------------------------


def _csv_values(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


def _resolve_preset(preset_id: str | None) -> presets.CareerPreset:
    requested = (preset_id or DEFAULT_INIT_PRESET).strip().lower()
    try:
        return presets.get_preset(requested)
    except KeyError as exc:
        known = ", ".join(sorted(presets.CAREER_PRESETS))
        raise ValueError(
            f"Filière inconnue « {requested} » (disponibles : {known})."
        ) from exc


def _resolve_cities(raw_cities: Iterable[str] | None) -> list[str]:
    provided = [str(city).strip().lower() for city in (raw_cities or DEFAULT_CITIES)]
    provided = [city for city in provided if city]
    if not provided:
        provided = list(DEFAULT_CITIES)
    unknown = [city for city in provided if city not in presets.FRENCH_STUDENT_CITIES]
    if unknown:
        known = ", ".join(sorted(presets.FRENCH_STUDENT_CITIES))
        raise ValueError(
            f"Ville(s) inconnue(s) : {', '.join(unknown)} (disponibles : {known})."
        )
    return list(dict.fromkeys(provided))


def _resolve_contracts(raw_contracts: Iterable[str] | None) -> list[str]:
    provided = [
        str(contract).strip().lower()
        for contract in (raw_contracts or DEFAULT_CONTRACTS)
    ]
    provided = [contract for contract in provided if contract]
    if not provided:
        provided = list(DEFAULT_CONTRACTS)
    unknown = [
        contract for contract in provided if contract not in presets.VALID_CONTRACTS
    ]
    if unknown:
        known = ", ".join(presets.VALID_CONTRACTS)
        raise ValueError(
            f"Contrat(s) inconnu(s) : {', '.join(unknown)} (disponibles : {known})."
        )
    return list(dict.fromkeys(provided))


def _set_candidate_name(candidate: dict[str, Any], name: str) -> None:
    clean = " ".join(name.split())
    candidate["name"] = clean
    first, _, last = clean.partition(" ")
    candidate["first_name"] = first
    candidate["last_name"] = last


def build_profile_payload(
    *,
    preset_id: str | None = None,
    cities: Iterable[str] | None = None,
    contracts: Iterable[str] | None = None,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    level: str | None = None,
    track: str | None = None,
    school: str | None = None,
    skills: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Construit un payload v2 validé, prêt pour ``save_profile_payload``."""
    preset = _resolve_preset(preset_id)
    city_ids = _resolve_cities(cities)
    contract_ids = _resolve_contracts(contracts)

    payload = candidate_config.build_example_profile_v2(
        preset_id=preset.id,
        cities=city_ids,
        contracts=contract_ids,
    )
    candidate = payload["candidate"]
    _set_candidate_name(candidate, name or DEFAULT_NAME)
    candidate["email"] = (email or DEFAULT_EMAIL).strip()
    candidate["phone"] = (phone or DEFAULT_PHONE).strip()
    candidate["level"] = (level or DEFAULT_LEVEL).strip()
    candidate["track"] = (track or preset.label).strip()
    candidate["school"] = (school or DEFAULT_SCHOOL).strip()

    cleaned_skills = sorted(
        {str(skill).strip().lower() for skill in (skills or ()) if str(skill).strip()}
    )
    if cleaned_skills:
        payload["skills"] = {
            "owned": cleaned_skills,
            "extra_weights": dict(payload.get("skills", {}).get("extra_weights") or {}),
        }
    return payload


def _is_profile_configured(path: Path) -> bool:
    """Vrai si le fichier contient un profil valide avec nom et email."""
    if not path.exists():
        return False
    cfg = candidate_config.load_profile(path)
    if cfg.load_error or not cfg.configured:
        return False
    candidate = cfg.candidate or {}
    return bool(str(candidate.get("name") or "").strip()) and bool(
        str(candidate.get("email") or "").strip()
    )


def _ask(prompt: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix} : ").strip()
    except EOFError as exc:
        raise ValueError(
            "Entrée interactive indisponible ; utilisez --non-interactive."
        ) from exc
    return answer or default


def _interactive_answers(
    *,
    preset_id: str,
    cities: Sequence[str],
    contracts: Sequence[str],
    name: str,
    email: str,
    phone: str,
    level: str,
    track: str,
    school: str,
    skills: Sequence[str],
) -> dict[str, Any]:
    """Pose les cinq questions d'onboarding et retourne les valeurs saisies."""
    preset_ids = ", ".join(sorted(presets.CAREER_PRESETS))
    city_ids = ", ".join(sorted(presets.FRENCH_STUDENT_CITIES))
    contract_ids = ", ".join(presets.VALID_CONTRACTS)

    print("Onboarding candidat — 5 questions, Entrée pour garder la valeur par défaut.")
    preset_id = _ask(f"1/5 Filière ({preset_ids})", preset_id)
    cities = _csv_values(_ask(f"2/5 Villes cibles ({city_ids})", ",".join(cities)))
    contracts = _csv_values(_ask(f"3/5 Contrats ({contract_ids})", ",".join(contracts)))

    identity_default = f"{name} | {email} | {phone}"
    identity = _ask("4/5 Identité « Nom | email | téléphone »", identity_default)
    identity_parts = [part.strip() for part in identity.split("|")]
    name = identity_parts[0] if identity_parts and identity_parts[0] else name
    if len(identity_parts) > 1 and identity_parts[1]:
        email = identity_parts[1]
    if len(identity_parts) > 2 and identity_parts[2]:
        phone = identity_parts[2]

    training_default = " | ".join((level, track, school, ", ".join(skills)))
    training = _ask(
        "5/5 Formation « niveau | parcours | école | compétences »",
        training_default,
    )
    training_parts = [part.strip() for part in training.split("|")]
    level = training_parts[0] if training_parts and training_parts[0] else level
    if len(training_parts) > 1 and training_parts[1]:
        track = training_parts[1]
    if len(training_parts) > 2 and training_parts[2]:
        school = training_parts[2]
    if len(training_parts) > 3:
        skills = _csv_values(training_parts[3])

    return {
        "preset_id": preset_id,
        "cities": cities,
        "contracts": contracts,
        "name": name,
        "email": email,
        "phone": phone,
        "level": level,
        "track": track,
        "school": school,
        "skills": skills,
    }


# --------------------------------------------------------------------------
# Sous-commandes
# --------------------------------------------------------------------------


def cmd_presets(args: argparse.Namespace) -> int:
    data = {
        "presets": [
            {
                "id": preset_id,
                "label": preset.label,
                "description": preset.description,
                "default_contracts": list(preset.default_contracts),
            }
            for preset_id, preset in presets.CAREER_PRESETS.items()
        ],
        "cities": [
            {
                "id": city_id,
                "name": city["name"],
                "department": city["department"],
                "label": city["label"],
            }
            for city_id, city in presets.FRENCH_STUDENT_CITIES.items()
        ],
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"Filières ({len(data['presets'])}) :")
    for item in data["presets"]:
        contracts = ", ".join(item["default_contracts"])
        print(f"  - {item['id']} : {item['label']} (contrats : {contracts})")
    print(f"\nMétropoles étudiantes ({len(data['cities'])}) :")
    for city in data["cities"]:
        print(f"  - {city['id']} : {city['label']}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    preset = _resolve_preset(args.preset)
    values: dict[str, Any] = {
        "preset_id": preset.id,
        "cities": _resolve_cities(_csv_values(args.cities)),
        "contracts": _resolve_contracts(_csv_values(args.contracts)),
        "name": (args.name or DEFAULT_NAME).strip(),
        "email": (args.email or DEFAULT_EMAIL).strip(),
        "phone": (args.phone or DEFAULT_PHONE).strip(),
        "level": (args.level or DEFAULT_LEVEL).strip(),
        "track": (args.track or preset.label).strip(),
        "school": (args.school or DEFAULT_SCHOOL).strip(),
        "skills": _csv_values(args.skills),
    }

    if not args.non_interactive:
        values = _interactive_answers(**values)

    target = (
        Path(args.output).expanduser()
        if args.output
        else candidate_config.profile_path()
    )
    if target.exists() and target.is_dir():
        raise ValueError(f"Le chemin de sortie est un répertoire : {target}.")
    if not args.force and _is_profile_configured(target):
        raise ValueError(
            f"Un profil déjà configuré existe ({target}). "
            "Utilisez --force pour l'écraser."
        )

    payload = build_profile_payload(**values)
    candidate_config.save_profile_payload(payload, path=target)

    print(f"Profil candidat v2 créé : {target}")
    print(f"  Filière   : {values['preset_id']}")
    print(f"  Villes    : {', '.join(values['cities'])}")
    print(f"  Contrats  : {', '.join(values['contracts'])}")
    print("  Permissions : 0600 (écriture atomique)")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    import dashboard_setup

    preset = _resolve_preset(args.preset or "software_data")
    profile_path = candidate_config.profile_path()
    candidate_config.reload_profile(profile_path)
    configured = dashboard_setup.is_profile_configured()

    profile_created = False
    if not configured or args.overwrite:
        payload = candidate_config.build_example_profile_v2(
            preset_id=preset.id,
            cities=("lyon", "paris"),
            contracts=("stage", "alternance", "job"),
        )
        candidate = payload["candidate"]
        _set_candidate_name(candidate, "Camille Martin")
        candidate["email"] = "camille.martin.demo@example.org"
        candidate["phone"] = DEFAULT_PHONE
        candidate_config.save_profile_payload(payload, path=profile_path)
        candidate_config.reload_profile(profile_path)
        profile_created = True

    seeded = dashboard_setup._seed_demo_store_offers()
    print(
        f"Démo prête : {seeded} offres injectées dans {store.DB_PATH} "
        f"(profil {'créé' if profile_created else 'conservé'})."
    )
    return 0


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _nearest_existing_parent(path: Path) -> Path | None:
    probe = path
    while True:
        if probe.exists():
            return probe if probe.is_dir() else probe.parent
        if probe == probe.parent:
            return None
        probe = probe.parent


def _check_profile_and_permissions(profile_path: Path) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    if not profile_path.exists():
        checks.append(
            _check(
                "profile",
                "error",
                f"profil absent ({profile_path}) — lancez « career_ctl.py init »",
            )
        )
        return checks

    cfg = candidate_config.load_profile(profile_path)
    candidate = cfg.candidate or {}
    if cfg.load_error:
        checks.append(_check("profile", "error", f"profil invalide : {cfg.load_error}"))
    elif not cfg.configured or not (
        str(candidate.get("name") or "").strip()
        and str(candidate.get("email") or "").strip()
    ):
        checks.append(
            _check(
                "profile",
                "error",
                "profil incomplet (nom et email requis) — relancez init",
            )
        )
    else:
        checks.append(_check("profile", "ok", f"profil valide ({profile_path})"))

    if os.name != "nt":
        mode = stat.S_IMODE(profile_path.stat().st_mode)
        if mode & 0o077:
            checks.append(
                _check(
                    "profile_permissions",
                    "error",
                    f"permissions trop larges ({mode:04o}) — attendu 0600",
                )
            )
        else:
            checks.append(
                _check("profile_permissions", "ok", f"permissions privées ({mode:04o})")
            )
    return checks


def build_doctor_report() -> dict[str, Any]:
    """Construit le diagnostic hors-ligne sans exposer aucune valeur sensible."""
    checks: list[dict[str, str]] = []

    current = sys.version_info[:2]
    if current >= MIN_PYTHON:
        checks.append(
            _check(
                "python",
                "ok",
                f"Python {current[0]}.{current[1]} (minimum {MIN_PYTHON[0]}.{MIN_PYTHON[1]})",
            )
        )
    else:
        checks.append(
            _check(
                "python",
                "error",
                f"Python {current[0]}.{current[1]} trop ancien "
                f"(minimum {MIN_PYTHON[0]}.{MIN_PYTHON[1]})",
            )
        )

    for module_name in ("requests", "bs4", "openpyxl", "lxml"):
        try:
            available = importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        checks.append(
            _check(
                f"module:{module_name}",
                "ok" if available else "error",
                "disponible"
                if available
                else "module introuvable (dépendance requise)",
            )
        )

    checks.extend(_check_profile_and_permissions(candidate_config.profile_path()))

    db_path = Path(store.DB_PATH)
    if db_path.exists():
        writable = os.access(db_path, os.W_OK)
        checks.append(
            _check(
                "sqlite",
                "ok" if writable else "error",
                f"base {'accessible' if writable else 'non accessible'} en écriture ({db_path})",
            )
        )
    else:
        parent = _nearest_existing_parent(db_path.parent)
        ok_parent = parent is not None and os.access(parent, os.W_OK)
        checks.append(
            _check(
                "sqlite",
                "ok" if ok_parent else "error",
                f"base créable dans le dossier accessible ({parent})"
                if ok_parent
                else f"dossier parent non accessible en écriture ({db_path.parent})",
            )
        )

    for env_name in OPTIONAL_ENV_VARS:
        present = bool(os.getenv(env_name, "").strip())
        checks.append(
            _check(
                f"env:{env_name}",
                "ok" if present else "warn",
                "définie" if present else "non définie (optionnel)",
            )
        )

    healthy = all(check["status"] != "error" for check in checks)
    return {
        "ok": healthy,
        "checks": checks,
        "errors": sum(1 for check in checks if check["status"] == "error"),
        "warnings": sum(1 for check in checks if check["status"] == "warn"),
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    report = build_doctor_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for check in report["checks"]:
            print(f"[{check['status'].upper():5}] {check['name']} : {check['detail']}")
        verdict = "sain" if report["ok"] else "erreur bloquante"
        print(
            f"\nDiagnostic : {verdict} "
            f"({report['errors']} erreur(s), {report['warnings']} avertissement(s))."
        )
    return 0 if report["ok"] else 1


# --------------------------------------------------------------------------
# Export autonome + scan de fuites
# --------------------------------------------------------------------------


def _is_forbidden_export_name(name: str) -> bool:
    if name == ".env.example":
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    return name.endswith(EXPORT_FORBIDDEN_SUFFIXES)


def _is_exportable(path: Path, suffixes: Sequence[str]) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    if _is_forbidden_export_name(path.name):
        return False
    return path.suffix.lower() in suffixes


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise ValueError(f"Lien symbolique source refusé : {source}")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(source, destination, follow_symlinks=False)


def _copy_filtered_tree(
    source: Path,
    destination: Path,
    *,
    suffixes: Sequence[str],
) -> int:
    copied = 0
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in EXPORT_IGNORED_DIRS for part in relative.parts):
            continue
        if not _is_exportable(path, suffixes):
            continue
        target = destination / relative
        _copy_file(path, target)
        copied += 1
    return copied


def _prepare_destination(destination: Path, *, force: bool) -> None:
    if destination.is_symlink():
        raise ValueError("Le dossier d'export ne doit pas être un lien symbolique.")
    resolved = destination.resolve()
    broad_system_dirs = {
        Path(resolved.anchor),
        Path.home().resolve(),
        *(
            Path(p).resolve()
            for p in ("/tmp", "/var/tmp", "/var", "/etc", "/usr", "/opt")
            if Path(p).exists()
        ),
    }
    if resolved in broad_system_dirs:
        raise ValueError(
            "Dossier d'export refusé : chemin système ou racine trop large."
        )
    if BOT_DIR.is_relative_to(resolved) or resolved.is_relative_to(JOB_ROOT):
        raise ValueError(
            "Dossier d'export refusé : il ne doit pas contenir ni être dans le dépôt."
        )
    if resolved == Path.cwd().resolve():
        raise ValueError("Dossier d'export refusé : répertoire courant.")

    if destination.exists():
        if not destination.is_dir():
            raise ValueError(
                f"Le chemin d'export existe et n'est pas un dossier : {destination}."
            )
        entries = list(destination.iterdir())
        if entries and not force:
            raise ValueError(
                f"Le dossier d'export n'est pas vide ({destination}). Utilisez --force."
            )
        if force:
            shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)


def export_standalone(destination: Path | str, *, force: bool = False) -> Path:
    """Crée une distribution autonome propre puis vérifie l'absence de fuite."""
    target_root = Path(destination).expanduser()
    _prepare_destination(target_root, force=force)

    bot_target = target_root / EXPORT_DIR_NAME / EXPORT_BOT_SUBDIR
    bot_target.mkdir(parents=True, exist_ok=True, mode=0o700)

    for path in sorted(BOT_DIR.iterdir()):
        if not _is_exportable(path, EXPORT_ROOT_SUFFIXES):
            continue
        _copy_file(path, bot_target / path.name)

    example_profile = BOT_DIR / "candidate-profile.example.json"
    if example_profile.is_file():
        _copy_file(example_profile, bot_target / example_profile.name)

    _copy_filtered_tree(
        BOT_DIR / "hellowork",
        bot_target / "hellowork",
        suffixes=EXPORT_TREE_SUFFIXES,
    )
    _copy_filtered_tree(
        BOT_DIR / "tests",
        bot_target / "tests",
        suffixes=EXPORT_TREE_SUFFIXES,
    )
    for optional_subdir in ("presets_data", "static"):
        sub_src = BOT_DIR / optional_subdir
        if sub_src.is_dir():
            _copy_filtered_tree(
                sub_src,
                bot_target / optional_subdir,
                suffixes=EXPORT_TREE_SUFFIXES,
            )

    src_dir = JOB_ROOT / "src"
    if src_dir.is_dir():
        _copy_filtered_tree(
            src_dir,
            target_root / EXPORT_DIR_NAME / "src",
            suffixes=EXPORT_TREE_SUFFIXES,
        )

    shared_source = PROJECT_ROOT / "shared"
    shared_target = target_root / "shared"
    shared_target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for filename in ("__init__.py", "paths.py"):
        source = shared_source / filename
        if source.is_file():
            _copy_file(source, shared_target / filename)

    for filename in (*EXPORT_REQUIRED_FILES, "pyproject.toml"):
        source = JOB_ROOT / filename
        if source.is_file():
            _copy_file(source, target_root / filename)

    compose_exported = target_root / "docker-compose.yml"
    if compose_exported.is_file():
        compose_text = compose_exported.read_text(encoding="utf-8")
        compose_text = compose_text.replace("context: ..", "context: .").replace(
            "dockerfile: Job-Etudiant/Dockerfile", "dockerfile: Dockerfile"
        )
        compose_exported.write_text(compose_text, encoding="utf-8")
    dockerfile_exported = target_root / "Dockerfile"
    if dockerfile_exported.is_file():
        df_text = dockerfile_exported.read_text(encoding="utf-8")
        df_text = df_text.replace(
            "ARG REQUIREMENTS_FILE=Job-Etudiant/requirements-standalone.txt",
            "ARG REQUIREMENTS_FILE=requirements-standalone.txt",
        )
        dockerfile_exported.write_text(df_text, encoding="utf-8")

    env_example = target_root / ".env.example"
    env_example.write_text(ENV_EXAMPLE_CONTENT, encoding="utf-8")
    if os.name != "nt":
        env_example.chmod(0o644)

    leaks = scan_export_for_leaks(target_root)
    if leaks:
        details = "\n".join(f"  - {leak}" for leak in leaks)
        raise ExportLeakError(
            "Fuite détectée dans la distribution exportée :\n" + details
        )
    return target_root


def scan_export_for_leaks(destination: Path | str) -> list[str]:
    """Retourne la liste des fuites détectées dans ``destination``."""
    root = Path(destination)
    if not root.is_dir():
        raise ValueError(f"Dossier d'export introuvable : {root}")

    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            findings.append(f"lien symbolique interdit : {path.relative_to(root)}")
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        name = path.name

        if name != ".env.example" and (name == ".env" or name.startswith(".env.")):
            findings.append(f"fichier d'environnement interdit : {relative}")
        if name.endswith(EXPORT_FORBIDDEN_SUFFIXES):
            findings.append(f"fichier de données interdit : {relative}")
        if any(part in EXPORT_IGNORED_DIRS for part in relative.parts):
            findings.append(f"dossier de cache interdit : {relative}")

        try:
            raw = path.read_bytes()
        except OSError as exc:
            findings.append(
                f"fichier illisible ({exc.__class__.__name__}) : {relative}"
            )
            continue
        text = raw.decode("utf-8", errors="ignore")

        if _PRIVATE_KEY_RE.search(text):
            findings.append(f"clé privée détectée : {relative}")
        for pattern, label in _TOKEN_PATTERNS:
            if pattern.search(text):
                findings.append(f"{label} détecté : {relative}")
        if _GMAIL_RE.search(text):
            findings.append(f"adresse email personnelle détectée : {relative}")

    return findings


def cmd_export_standalone(args: argparse.Namespace) -> int:
    destination = export_standalone(args.dest_dir, force=args.force)
    print(f"Distribution autonome créée : {destination}")
    print("  Scan de fuites : aucun secret, .env, base ou email personnel détecté.")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="career_ctl.py",
        description="Onboarding, diagnostic et export autonome Job-Etudiant.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    presets_parser = subparsers.add_parser(
        "presets", help="Lister les filières et métropoles disponibles."
    )
    presets_parser.add_argument("--json", action="store_true", help="Sortie JSON.")
    presets_parser.set_defaults(handler=cmd_presets)

    init_parser = subparsers.add_parser("init", help="Créer un profil candidat v2.")
    init_parser.add_argument(
        "--non-interactive", action="store_true", help="Aucune question interactive."
    )
    init_parser.add_argument(
        "--preset",
        default=DEFAULT_INIT_PRESET,
        help="Filière (défaut : software_data).",
    )
    init_parser.add_argument(
        "--cities", help="Villes séparées par virgule (lyon,paris)."
    )
    init_parser.add_argument(
        "--contracts", help="Contrats séparés par virgule (stage,alternance)."
    )
    init_parser.add_argument("--name", help="Nom complet du candidat.")
    init_parser.add_argument("--email", help="Email du candidat.")
    init_parser.add_argument("--phone", help="Téléphone du candidat.")
    init_parser.add_argument("--level", help="Niveau d'études (ex. Bac+3).")
    init_parser.add_argument("--track", help="Parcours / spécialité.")
    init_parser.add_argument("--school", help="Établissement.")
    init_parser.add_argument(
        "--skills", help="Compétences séparées par virgule (python,sql,docker)."
    )
    init_parser.add_argument("--output", help="Chemin du profil à écrire.")
    init_parser.add_argument(
        "--force", action="store_true", help="Écraser un profil déjà configuré."
    )
    init_parser.set_defaults(handler=cmd_init)

    demo_parser = subparsers.add_parser(
        "demo", help="Créer un profil démo et injecter cinq offres."
    )
    demo_parser.add_argument(
        "--preset", default="software_data", help="Filière du profil démo."
    )
    demo_parser.add_argument(
        "--overwrite", action="store_true", help="Remplacer le profil existant."
    )
    demo_parser.set_defaults(handler=cmd_demo)

    doctor_parser = subparsers.add_parser(
        "doctor", help="Diagnostic hors-ligne de l'environnement."
    )
    doctor_parser.add_argument("--json", action="store_true", help="Sortie JSON.")
    doctor_parser.set_defaults(handler=cmd_doctor)

    export_parser = subparsers.add_parser(
        "export-standalone", help="Exporter une distribution autonome propre."
    )
    export_parser.add_argument("dest_dir", help="Dossier de destination.")
    export_parser.add_argument(
        "--force",
        action="store_true",
        help="Vider et recréer le dossier de destination.",
    )
    export_parser.set_defaults(handler=cmd_export_standalone)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ExportLeakError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
