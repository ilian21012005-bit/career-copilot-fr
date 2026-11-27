"""Réglages dynamiques des campagnes (pilotés par `candidate_config`). Aucun secret ici."""

from __future__ import annotations

import os
from pathlib import Path

import candidate_config

BOT_DIR = Path(__file__).resolve().parent
ROOT = BOT_DIR.parent
DATA_DIR = BOT_DIR / "data"
TEMPLATES_DIR = BOT_DIR / "templates"
DB_PATH = DATA_DIR / "candidatures.db"


def _existing_document(directory: Path, pattern: str, fallback: str) -> Path:
    matches = sorted(directory.glob(pattern)) if directory.is_dir() else []
    return matches[0] if matches else directory / fallback


def _resolve_document(
    primary_dir: Path,
    pattern: str,
    fallback: str,
    templates_dir: Path,
) -> Path:
    if primary_dir.is_dir():
        return _existing_document(primary_dir, pattern, fallback)
    return _existing_document(templates_dir, pattern, fallback)


def _resolve_letter(primary_path: Path, templates_dir: Path) -> Path:
    if primary_path.is_file() or primary_path.parent.is_dir():
        return primary_path
    return templates_dir / primary_path.name


def _alternance_document(
    search_dirs: tuple[Path, ...],
    pattern: str,
    stage_fallback: Path,
) -> Path:
    for directory in search_dirs:
        if directory.is_dir():
            matches = sorted(directory.glob(pattern))
            if matches:
                return matches[0]
    return stage_fallback


def resolve_document_paths(
    *,
    root: Path = ROOT,
    data_dir: Path = DATA_DIR,
    templates_dir: Path = TEMPLATES_DIR,
) -> tuple[dict[str, Path], dict[str, Path], dict[str, Path]]:
    """Résout les chemins CV HTML/PDF et lettres avec fallback standalone `bot/templates`."""
    job_cv_dir = root / "1-Job-etudiant" / "CV"
    stage_cv_dir = root / "2-Stage-SOC" / "CV"
    job_letter_path = root / "1-Job-etudiant" / "Lettres" / "Lettre-type-candidature.md"
    stage_letter_path = root / "2-Stage-SOC" / "Lettres" / "LM-Stage-SOC-Reseau.md"

    stage_html = _resolve_document(
        stage_cv_dir,
        "CV-*-Stage-SOC-Reseau.html",
        "CV-candidat-Stage-SOC-Reseau.html",
        templates_dir,
    )
    cv_html = {
        "job": _resolve_document(
            job_cv_dir,
            "CV-*-Job-Etudiant.html",
            "CV-candidat-Job-Etudiant.html",
            templates_dir,
        ),
        "stage": stage_html,
        "alternance": _alternance_document(
            (stage_cv_dir, templates_dir),
            "CV-*-Alternance.html",
            stage_html,
        ),
    }

    stage_pdf = _existing_document(
        data_dir, "CV-*-Stage-SOC-Reseau.pdf", "CV-candidat-Stage-SOC-Reseau.pdf"
    )
    cv_pdf = {
        "job": _existing_document(
            data_dir, "CV-*-Job-Etudiant.pdf", "CV-candidat-Job-Etudiant.pdf"
        ),
        "stage": stage_pdf,
        "alternance": _alternance_document(
            (data_dir,),
            "CV-*-Alternance.pdf",
            stage_pdf,
        ),
    }

    stage_letter = _resolve_letter(stage_letter_path, templates_dir)
    letter = {
        "job": _resolve_letter(job_letter_path, templates_dir),
        "stage": stage_letter,
        "alternance": _alternance_document(
            (root / "2-Stage-SOC" / "Lettres", templates_dir),
            "LM-*-Alternance*.md",
            stage_letter,
        ),
    }
    return cv_html, cv_pdf, letter


CV_HTML, CV_PDF, LETTER = resolve_document_paths()


def _configured_gmail_address() -> str:
    configured = os.getenv("GMAIL_ADDRESS", "").strip()
    if configured:
        return configured
    env_path = BOT_DIR / ".env"
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("GMAIL_ADDRESS="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return ""


GMAIL_ADDRESS = _configured_gmail_address()
SENDER_NAME = os.getenv("SENDER_NAME", "Candidat").strip() or "Candidat"

JOB_CAP = 8
STAGE_CAP = 10
GLOBAL_CAP = 20
JOB_DISTANCE_KM: int | float = 15
STAGE_DISTANCE_KM: int | float = 30
JOB_ALLOW_FULL_TIME = os.getenv("JOB_ALLOW_FULL_TIME", "0").strip().lower() not in {
    "0",
    "false",
    "no",
    "non",
}
# Politique étudiante : temps plein ordinaire ferme par defaut pendant les cours,
# tout en autorisant un contrat saisonnier / vacances explicite (Noel, fetes, vacances scolaires).
JOB_ALLOW_SEASONAL_FULL_TIME = os.getenv(
    "JOB_ALLOW_SEASONAL_FULL_TIME", "1"
).strip().lower() not in {
    "0",
    "false",
    "no",
    "non",
}
# Mode blocus / disponible en semaine (~24h/semaine hors temps plein 35h+).
JOB_WEEKDAY_PART_TIME = os.getenv("JOB_WEEKDAY_PART_TIME", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "non",
}
JOB_WEEKLY_HOURS = int(os.getenv("JOB_WEEKLY_HOURS", "24") or "24")

ACTIVE_CONTRACTS: tuple[str, ...] = ("stage", "job")
ZONES: dict[str, list[dict]] = {"job": [], "stage": []}

STAGE_TITLES: list[str] = []

# Si ROMEO ne répond pas, ces codes ROME restent valables.
STAGE_ROME_FALLBACK: list[str] = []

ADZUNA_JOB_QUERIES = [
    "employé polyvalent",
    "mise en rayon",
    "caissier",
    "équipier polyvalent",
    "vendeur",
    "hôte de caisse",
    "préparateur de commandes",
    "saisonnier noël",
    "logistique entrepôt",
    "inventaire",
    "renfort vente",
    "intérim manutention",
    "agent de tri colis",
    "amazon",
]
JOOBLE_JOB_QUERIES = [
    "équipier polyvalent",
    "caissier",
    "vendeur",
    "préparateur de commandes",
    "saisonnier noël",
    "mise en rayon",
    "logistique",
    "inventaire",
    "intérim commandes",
    "renfort vente",
]
ADZUNA_STAGE_QUERIES: list[str] = []

BASE_EXCLUSIONS: tuple[str, ...] = (
    "babysitting",
    "baby-sitting",
    "baby sitting",
    "babysitter",
    "garde d'enfant",
    "garde d’enfant",
    "garde d'enfants",
    "garde d’enfants",
    "garde enfant",
    "soutien scolaire",
    "aide aux devoirs",
    "aux devoirs",
    "nounou",
    "nourrice",
    "au pair",
    "au-pair",
)
EXCLUSIONS: tuple[str, ...] = BASE_EXCLUSIONS

STAGE_MUST: tuple[str, ...] = ()

# Soft Bac+5 : ne plus tout écarter. Seulement les formulations exclusives / senior.
SENIOR_MARKERS = (
    "bac+5 exigé",
    "bac +5 exigé",
    "bac+5 obligatoire",
    "bac +5 obligatoire",
    "master 2 exigé",
    "master 2 obligatoire",
    "master exigé",
    "uniquement bac+5",
    "uniquement bac +5",
    "école d'ingénieur obligatoire",
    "ecole d'ingenieur obligatoire",
    "3 ans d'expérience",
    "3 ans d’expérience",
    "5 ans d'expérience",
    "5 ans d’expérience",
    "expérience exigée de 3",
    "minimum 3 ans",
)


def _clean_km(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


def _build_zones(cfg: candidate_config.CandidateProfileConfig) -> dict[str, list[dict]]:
    stage_km = _clean_km(
        max((float(z.get("km", 30.0)) for z in cfg.zones), default=30.0)
    )
    job_km = _clean_km(float(cfg.job_radius_km))
    stage_zones = [
        {
            "name": str(z["name"]),
            "insee": str(z.get("insee", "")),
            "department": str(z.get("department", "")),
            "lat": float(z["lat"]),
            "lon": float(z["lon"]),
            "km": _clean_km(float(z.get("km", stage_km))),
        }
        for z in cfg.zones
    ]
    if stage_zones:
        job_zones = [
            {
                "name": z["name"],
                "insee": z["insee"],
                "department": z["department"],
                "lat": z["lat"],
                "lon": z["lon"],
                "km": job_km,
            }
            for z in stage_zones
        ]
    else:
        job_zones = []
    zones: dict[str, list[dict]] = {
        "job": job_zones,
        "stage": stage_zones,
    }
    if "alternance" in cfg.contracts:
        zones["alternance"] = [dict(z) for z in stage_zones]
    return zones


def sync_from_profile(
    cfg: candidate_config.CandidateProfileConfig | None = None,
) -> candidate_config.CandidateProfileConfig:
    """Met à jour en place les réglages du module depuis le profil candidat actif."""
    global ACTIVE_CONTRACTS, STAGE_MUST, STAGE_DISTANCE_KM, JOB_DISTANCE_KM, EXCLUSIONS

    profile = cfg if cfg is not None else candidate_config.get_profile()
    ACTIVE_CONTRACTS = tuple(profile.contracts)
    JOB_DISTANCE_KM = _clean_km(float(profile.job_radius_km))
    STAGE_DISTANCE_KM = _clean_km(
        max((float(z.get("km", 30.0)) for z in profile.zones), default=30.0)
    )

    ZONES.clear()
    ZONES.update(_build_zones(profile))

    STAGE_TITLES[:] = list(profile.stage_titles)
    ADZUNA_STAGE_QUERIES[:] = list(profile.adzuna_stage_queries)
    STAGE_ROME_FALLBACK[:] = list(profile.preset.rome_codes)
    STAGE_MUST = tuple(profile.preset.stage_must)
    EXCLUSIONS = tuple(
        dict.fromkeys(
            (*BASE_EXCLUSIONS, *(kw for kw in profile.custom_exclude_keywords if kw))
        )
    )
    return profile


sync_from_profile()
candidate_config.register_reload_listener(sync_from_profile)


def load_env() -> dict[str, str]:
    path = BOT_DIR / ".env"
    values: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in os.environ.items():
        if (
            key.startswith(("FT_", "GMAIL_", "ADZUNA_", "JOOBLE_", "WTTJ_", "LBA_"))
            or key
            in (
                "ENABLE_ALTERNANCE",
                "COMMERCIAL_SAFE",
                "CAREER_EDITION",
                "ENABLE_EXPERIMENTAL_SCRAPERS",
                "APEC_ENABLED",
            )
        ) and value:
            values[key] = value
    if "GMAIL_APP_PASSWORD" in values:
        values["GMAIL_APP_PASSWORD"] = values["GMAIL_APP_PASSWORD"].replace(" ", "")
    values.setdefault("GMAIL_ADDRESS", GMAIL_ADDRESS)
    return values


def is_commercial_safe(env: dict[str, str] | None = None) -> bool:
    """Indique si l'instance tourne en mode commercial strict (désactive LBA et scrapers hors-CGU)."""
    cfg = env if env is not None else os.environ
    comm = str(
        cfg.get("COMMERCIAL_SAFE") or os.getenv("COMMERCIAL_SAFE", "0")
    ).strip().lower()
    edition = str(
        cfg.get("CAREER_EDITION") or os.getenv("CAREER_EDITION", "")
    ).strip().lower()
    return comm in {"1", "true", "yes", "on", "oui"} or edition == "commercial"
