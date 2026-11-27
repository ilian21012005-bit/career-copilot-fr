"""Profil du candidat et critères de sélection — pilotés par `candidate_config`.

Les données personnelles résident dans `data/candidate-profile.json` (mode `0600`,
ignoré par Git). Les conteneurs mutables (`CANDIDATE`, `FORM_ANSWERS`,
`JOB_FORM_ANSWERS`, `SKILLS`, `OWNED`) sont mis à jour en place à chaque
rechargement de profil pour préserver les imports `from hellowork.profile import ...`.
"""

from __future__ import annotations

import os
from typing import Any

import candidate_config
import config
import presets

from . import basins as basins_mod
from .basins import ZONE_LABELS  # noqa: F401 — dict muté en place par basins

# --------------------------------------------------------------------------
# État synchronisé en place depuis candidate_config
# --------------------------------------------------------------------------

CANDIDATE: dict[str, Any] = {}
FORM_ANSWERS: dict[str, str] = {}
JOB_FORM_ANSWERS: dict[str, str] = {}
FACTS: tuple[str, ...] = ()

TARGET_CONTRACT: str = "stage"
TARGET_CONTRACTS: tuple[str, ...] = ("stage", "job")
ACTIVE_PRESET_ID: str = presets.DEFAULT_PRESET_ID
TARGET_DOMAINS: tuple[str, ...] = ()

SKILLS: dict[str, int] = {}
CORE_SKILLS: tuple[str, ...] = ()
OWNED: set[str] = set()

EXCLUDE_CONTRACTS: tuple[str, ...] = ()
EXCLUDE_TITLE_WORDS: tuple[str, ...] = ()

MIN_SCORE: int = 80
AUTO_HELLOWORK_MIN_SCORE: int = 60
DAILY_TARGET: int = 10
DAILY_MAX: int = 20

# Ré-exports de zones (synchronisés à chaud avec `hellowork.basins`)
RADIUS_KM: float = basins_mod.RADIUS_KM
ZONES: tuple[basins_mod.Zone, ...] = basins_mod.ZONES
ZONE_NAMES: tuple[str, ...] = basins_mod.ZONE_NAMES

# Un stage marqué Bac+5 / expérience exigée est pénalisé si Bac+3 non mentionné.
LEVEL_PENALTIES: tuple[tuple[str, int, str], ...] = (
    ("bac+5", 35, "Bac+5 demandé"),
    ("bac +5", 35, "Bac+5 demandé"),
    ("bac+4/5", 30, "Bac+4/5 demandé"),
    ("master 2", 30, "Master 2 demandé"),
    ("master", 15, "Master demandé"),
    ("école d'ingénieur", 10, "École d'ingénieur demandée"),
    ("ecole d'ingenieur", 10, "École d'ingénieur demandée"),
    ("doctorat", 40, "Doctorat demandé"),
    ("3 ans d'expérience", 30, "3 ans d'expérience exigés"),
    ("5 ans d'expérience", 40, "5 ans d'expérience exigés"),
    ("expérience exigée", 20, "Expérience exigée"),
    ("expérience significative", 15, "Expérience significative demandée"),
)

_ACTIVE_CONFIG: candidate_config.CandidateProfileConfig | None = None
_LAST_ENV_PATH: str = ""


def _build_job_form_answers(
    cfg: candidate_config.CandidateProfileConfig,
) -> dict[str, str]:
    """Construit des réponses job étudiant neutres, surchargées par le profil."""
    raw_home = str(cfg.candidate.get("home") or "").split("(")[0].strip()
    primary_city = raw_home or (str(cfg.zones[0]["name"]).strip() if cfg.zones else "")
    radius_km = f"{float(cfg.job_radius_km):.0f} km"
    mobility = (
        f"{primary_city} et environs ({radius_km})"
        if primary_city
        else f"Rayon {radius_km}"
    )
    level = str(cfg.candidate.get("level") or "Étudiant").strip() or "Étudiant"

    default_avail = (
        f"Disponible immédiatement environ {config.JOB_WEEKLY_HOURS}h/semaine (en semaine et week-ends) et vacances scolaires"
        if config.JOB_WEEKDAY_PART_TIME
        else "Disponible à temps partiel (soirs, week-ends) et vacances scolaires"
    )
    answers: dict[str, str] = {
        "disponibilite": default_avail,
        "disponibilité": default_avail,
        "mobilite": mobility,
        "mobilité": mobility,
        "type de contrat": "Job étudiant / CDD / Intérim / Temps partiel",
        "niveau": level,
    }
    for lang_key in ("langues", "Langues"):
        if cfg.form_answers.get(lang_key):
            answers["langues"] = str(cfg.form_answers[lang_key])
            break
    for key, value in cfg.job_form_answers.items():
        answers[key] = value
        lowered = key.strip().lower()
        if lowered in ("disponibilite", "disponibilité"):
            answers["disponibilite"] = value
            answers["disponibilité"] = value
        elif lowered in ("mobilite", "mobilité"):
            answers["mobilite"] = value
            answers["mobilité"] = value
    return answers


def _sync_from_config(cfg: candidate_config.CandidateProfileConfig) -> None:
    """Synchronise en place toutes les structures exposées depuis `cfg`."""
    global FACTS, TARGET_CONTRACT, TARGET_CONTRACTS, ACTIVE_PRESET_ID
    global TARGET_DOMAINS, CORE_SKILLS, EXCLUDE_CONTRACTS, EXCLUDE_TITLE_WORDS
    global MIN_SCORE, AUTO_HELLOWORK_MIN_SCORE, DAILY_TARGET, DAILY_MAX
    global RADIUS_KM, ZONES, ZONE_NAMES, _ACTIVE_CONFIG, _LAST_ENV_PATH

    _ACTIVE_CONFIG = cfg
    _LAST_ENV_PATH = os.getenv(candidate_config.PROFILE_PATH_ENV, "").strip()

    CANDIDATE.clear()
    CANDIDATE.update(cfg.candidate)

    FACTS = tuple(cfg.facts)

    FORM_ANSWERS.clear()
    FORM_ANSWERS.update(cfg.form_answers)

    JOB_FORM_ANSWERS.clear()
    JOB_FORM_ANSWERS.update(_build_job_form_answers(cfg))

    TARGET_CONTRACTS = tuple(cfg.contracts)
    TARGET_CONTRACT = cfg.target_contract
    ACTIVE_PRESET_ID = cfg.preset_id
    TARGET_DOMAINS = tuple(cfg.preset.target_domains)

    SKILLS.clear()
    SKILLS.update(cfg.skills_weights)

    CORE_SKILLS = tuple(cfg.preset.core_skills)

    OWNED.clear()
    OWNED.update(cfg.owned_skills)

    EXCLUDE_CONTRACTS = tuple(cfg.exclude_contracts)
    EXCLUDE_TITLE_WORDS = tuple(cfg.exclude_title_words)

    MIN_SCORE = int(cfg.min_score)
    AUTO_HELLOWORK_MIN_SCORE = int(cfg.auto_hellowork_min_score)
    DAILY_TARGET = int(cfg.daily_target)
    DAILY_MAX = int(cfg.daily_max)

    # S'assurer que basins est aligné puis refléter les ré-exports.
    basins_mod._sync_from_config(cfg)
    ZONES = basins_mod.ZONES
    ZONE_NAMES = basins_mod.ZONE_NAMES
    RADIUS_KM = basins_mod.RADIUS_KM


def active_config() -> candidate_config.CandidateProfileConfig:
    """Retourne la configuration active en détectant un changement d'env `CANDIDATE_PROFILE_PATH`."""
    env_path = os.getenv(candidate_config.PROFILE_PATH_ENV, "").strip()
    if _ACTIVE_CONFIG is None or env_path != _LAST_ENV_PATH:
        return candidate_config.reload_profile()
    return _ACTIVE_CONFIG


def active_preset() -> presets.CareerPreset:
    """Retourne le `CareerPreset` actif."""
    return active_config().preset


_sync_from_config(candidate_config.get_profile())
candidate_config.register_reload_listener(_sync_from_config)


def ai_profile() -> str:
    return "\n".join(f"- {line}" for line in FACTS)


def candidate_cv_prefix() -> str:
    """Return the legacy-compatible CV filename prefix from the private profile."""
    first_name = str(
        CANDIDATE.get("first_name") or str(CANDIDATE.get("name") or "").split(" ", 1)[0]
    ).strip()
    safe = "".join(char for char in first_name if char.isalnum() or char in "-_")
    return f"CV-{safe or 'candidat'}"


def form_answers_for(campaign: str = "stage") -> dict[str, str]:
    """Retourne les réponses de formulaire adaptées à la campagne."""
    base = dict(FORM_ANSWERS)
    first_zone = basins_mod.ZONES[0] if basins_mod.ZONES else {}
    fallback_city = str(first_zone.get("name") or "").strip()
    city = (
        str(CANDIDATE.get("home") or fallback_city).split("(")[0].strip()
        or fallback_city
    )
    postal = str(
        CANDIDATE.get("postal_code") or first_zone.get("department") or ""
    ).strip()
    address = str(CANDIDATE.get("address") or city).strip()
    for key, val in (
        ("Ville", city),
        ("Code postal", postal),
        ("Adresse", address),
        ("Pays", "France"),
    ):
        base.setdefault(key, val)
    if campaign == "job":
        base.update(JOB_FORM_ANSWERS)
    return base
