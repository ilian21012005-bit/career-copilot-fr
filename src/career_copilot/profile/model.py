"""Immutable candidate profile model, path resolution, and contract exclusion rules."""

from __future__ import annotations

import copy
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from career_copilot.profile.presets_access import get_presets_module

JOB_ROOT = Path(__file__).resolve().parents[3]
BOT_DIR = JOB_ROOT / "bot"
DEFAULT_PROFILE_PATH = BOT_DIR / "data" / "candidate-profile.json"
PROFILE_PATH_ENV = "CANDIDATE_PROFILE_PATH"
STANDALONE_ENV = "STANDALONE_CAREER_MODE"

SCHEMA_VERSION = 2
MAX_PROFILE_BYTES = 262_144
DEFAULT_JOB_RADIUS_KM = 15.0
DEFAULT_WEEKS = 17
DEFAULT_START_DATE = date(2027, 1, 18)
DEFAULT_END_DATE = date(2027, 5, 14)

MAX_ZONES = 10
MAX_FACTS = 60
MAX_FACT_LEN = 800
MAX_FORM_ANSWERS = 60
MAX_FORM_KEY_LEN = 120
MAX_FORM_VAL_LEN = 600
MAX_OWNED_SKILLS = 150
MAX_EXTRA_WEIGHTS = 100
MAX_SKILL_LEN = 80
MAX_CUSTOM_TITLES = 40
MAX_CUSTOM_QUERIES = 60
MAX_CUSTOM_EXCLUDES = 80
MAX_URL_LEN = 300

_ALTERNANCE_TOKENS: tuple[str, ...] = (
    "alternance",
    "apprentissage",
    "professionnalisation",
    "contrat pro",
)
_PERMANENT_TITLE_TOKENS: tuple[str, ...] = (
    "cdi",
    "cdd",
    "intérim",
    "interim",
    "freelance",
    "indépendant",
    "independant",
)
_JOB_ONLY_EXCLUDE_TITLE_TOKENS: tuple[str, ...] = (
    "freelance",
    "indépendant",
    "independant",
)


def profile_path(
    path: Path | str | None = None,
    *,
    default_path: Path = DEFAULT_PROFILE_PATH,
) -> Path:
    """Resolve candidate profile path (explicit arg > env > default)."""
    if path is not None:
        return Path(path)
    env_value = os.getenv(PROFILE_PATH_ENV, "").strip()
    if env_value:
        return Path(env_value).expanduser()
    return default_path


def is_standalone_mode(
    project_root: Path | str | None = None,
    *,
    monorepo_marker: tuple[str, ...] | None = None,
) -> bool:
    """Return True when running standalone (no external monorepo sibling marker)."""
    if os.getenv(STANDALONE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if monorepo_marker is None:
        return True
    root = Path(project_root) if project_root is not None else JOB_ROOT.parent
    return not root.joinpath(*monorepo_marker).exists()


def compute_contract_exclusions(
    contracts: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Derive `(exclude_contracts, exclude_title_words)` dynamically from active contracts."""
    active = tuple(dict.fromkeys(str(c).strip().lower() for c in contracts if str(c).strip()))
    has_stage = "stage" in active
    has_alternance = "alternance" in active
    has_job = "job" in active

    excluded_contracts: list[str] = []
    excluded_titles: list[str] = []

    if not has_alternance:
        excluded_contracts.extend(_ALTERNANCE_TOKENS)
        excluded_titles.extend(_ALTERNANCE_TOKENS)

    if not has_stage:
        excluded_contracts.append("stage")
        excluded_titles.extend(("stage", "stagiaire"))

    if has_job and not has_stage and not has_alternance:
        excluded_titles.extend(_JOB_ONLY_EXCLUDE_TITLE_TOKENS)
    else:
        excluded_titles.extend(_PERMANENT_TITLE_TOKENS)

    return tuple(dict.fromkeys(excluded_contracts)), tuple(dict.fromkeys(excluded_titles))


@dataclass(frozen=True)
class CandidateProfileConfig:
    """Immutable, thread-safe in-memory candidate profile configuration."""

    schema_version: int
    source_version: int
    configured: bool
    profile_file: Path
    load_error: str
    preset_id: str
    preset: Any
    contracts: tuple[str, ...]
    zone_preset: str
    zones: tuple[dict[str, Any], ...]
    job_radius_km: float
    candidate: dict[str, Any]
    facts: tuple[str, ...]
    form_answers: dict[str, str]
    job_form_answers: dict[str, str]
    owned_skills: frozenset[str]
    skills_weights: dict[str, int]
    allow_pure_software_dev: bool
    min_score: int
    auto_hellowork_min_score: int
    daily_target: int
    daily_max: int
    custom_stage_titles: tuple[str, ...]
    custom_stage_queries: tuple[str, ...]
    custom_exclude_keywords: tuple[str, ...]
    experiences: tuple[dict[str, Any], ...] = ()
    projects: tuple[dict[str, Any], ...] = ()
    job_profile: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.job_profile is None:
            object.__setattr__(
                self,
                "job_profile",
                {
                    "confirmed_tasks": [],
                    "retail_context": "en accueil et relation client",
                    "summary_sentences": [],
                },
            )

    @property
    def zone_labels(self) -> dict[str, str]:
        return {str(zone["name"]): str(zone.get("label") or zone["name"]) for zone in self.zones}

    @property
    def zone_names(self) -> tuple[str, ...]:
        return tuple(str(zone["name"]) for zone in self.zones)

    @property
    def target_contract(self) -> str:
        return self.contracts[0] if self.contracts else "stage"

    @property
    def accepts_stage(self) -> bool:
        return "stage" in self.contracts

    @property
    def accepts_alternance(self) -> bool:
        return "alternance" in self.contracts

    @property
    def accepts_job(self) -> bool:
        return "job" in self.contracts

    @property
    def exclude_contracts(self) -> tuple[str, ...]:
        contracts_ex, _ = compute_contract_exclusions(self.contracts)
        return contracts_ex

    @property
    def exclude_title_words(self) -> tuple[str, ...]:
        _, title_ex = compute_contract_exclusions(self.contracts)
        return title_ex

    @property
    def stage_titles(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.preset.stage_titles, *self.custom_stage_titles)))

    @property
    def adzuna_stage_queries(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.preset.adzuna_stage_queries, *self.custom_stage_queries)))

    def to_dict(self) -> dict[str, Any]:
        """Serialize back to a JSON-compatible schema v2 dictionary."""
        cand = dict(self.candidate)
        for key in ("start", "end"):
            value = cand.get(key)
            if isinstance(value, date):
                cand[key] = value.isoformat()
        extra_weights = {
            k: v for k, v in self.skills_weights.items() if self.preset.skills_weights.get(k) != v
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "preset": self.preset_id,
            "contracts": list(self.contracts),
            "zone_preset": self.zone_preset,
            "zones": [dict(z) for z in self.zones],
            "job_radius_km": self.job_radius_km,
            "candidate": cand,
            "facts": list(self.facts),
            "form_answers": dict(self.form_answers),
            "job_form_answers": dict(self.job_form_answers),
            "skills": {
                "owned": sorted(self.owned_skills),
                "extra_weights": extra_weights,
            },
            "preferences": {
                "min_score": self.min_score,
                "auto_hellowork_min_score": self.auto_hellowork_min_score,
                "daily_target": self.daily_target,
                "daily_max": self.daily_max,
                "allow_pure_software_dev": self.allow_pure_software_dev,
                "custom_stage_titles": list(self.custom_stage_titles),
                "custom_stage_queries": list(self.custom_stage_queries),
                "custom_exclude_keywords": list(self.custom_exclude_keywords),
            },
            "experiences": [copy.deepcopy(exp) for exp in self.experiences],
            "projects": [copy.deepcopy(proj) for proj in self.projects],
            "job_profile": copy.deepcopy(self.job_profile),
        }


def build_config_from_normalized(
    normalized: dict[str, Any],
    *,
    path: Path,
    configured: bool,
    source_version: int,
    load_error: str = "",
) -> CandidateProfileConfig:
    """Hydrate a frozen ``CandidateProfileConfig`` from a validated v2 dictionary."""
    presets_mod = get_presets_module()
    preset_id = str(normalized["preset"])
    preset = presets_mod.get_preset(preset_id)

    cand = copy.deepcopy(normalized["candidate"])
    cand["start"] = date.fromisoformat(str(cand["start"]))
    cand["end"] = date.fromisoformat(str(cand["end"]))

    skills_block = normalized.get("skills") or {}
    if "owned" in skills_block and skills_block["owned"] is not None:
        owned_skills = frozenset(skills_block["owned"])
    else:
        owned_skills = preset.default_owned

    skills_weights = dict(preset.skills_weights)
    for skill_key, weight in (skills_block.get("extra_weights") or {}).items():
        skills_weights[skill_key] = int(weight)

    prefs = normalized["preferences"]
    allow_dev = (
        preset.allow_pure_software_dev
        if prefs.get("allow_pure_software_dev") is None
        else bool(prefs["allow_pure_software_dev"])
    )

    return CandidateProfileConfig(
        schema_version=SCHEMA_VERSION,
        source_version=source_version,
        configured=configured,
        profile_file=path,
        load_error=load_error,
        preset_id=preset_id,
        preset=preset,
        contracts=tuple(normalized["contracts"]),
        zone_preset=str(normalized["zone_preset"]),
        zones=tuple(dict(z) for z in normalized["zones"]),
        job_radius_km=float(normalized["job_radius_km"]),
        candidate=cand,
        facts=tuple(normalized["facts"]),
        form_answers=dict(normalized["form_answers"]),
        job_form_answers=dict(normalized["job_form_answers"]),
        owned_skills=owned_skills,
        skills_weights=skills_weights,
        allow_pure_software_dev=allow_dev,
        min_score=int(prefs["min_score"]),
        auto_hellowork_min_score=int(prefs["auto_hellowork_min_score"]),
        daily_target=int(prefs["daily_target"]),
        daily_max=int(prefs["daily_max"]),
        custom_stage_titles=tuple(prefs["custom_stage_titles"]),
        custom_stage_queries=tuple(prefs["custom_stage_queries"]),
        custom_exclude_keywords=tuple(prefs["custom_exclude_keywords"]),
        experiences=tuple(copy.deepcopy(x) for x in (normalized.get("experiences") or ())),
        projects=tuple(copy.deepcopy(x) for x in (normalized.get("projects") or ())),
        job_profile=copy.deepcopy(normalized.get("job_profile")),
    )


def build_example_profile_v2(
    preset_id: str | None = None,
    cities: Iterable[str] = ("paris", "lyon", "bordeaux"),
    contracts: Iterable[str] = ("stage", "alternance", "job"),
) -> dict[str, Any]:
    """Build a 100% synthetic zero-PII v2 example profile (Alex Martin)."""
    from career_copilot.profile.validation import validate_and_normalize_profile_payload

    presets_mod = get_presets_module()
    chosen_preset = preset_id or presets_mod.DEFAULT_PRESET_ID
    try:
        preset = presets_mod.get_preset(chosen_preset)
    except KeyError as exc:
        raise ValueError(f"Preset métier inconnu : « {chosen_preset} ».") from exc

    city_list = tuple(cities)
    if not city_list:
        raise ValueError("Au moins une ville étudiante est requise pour l'exemple.")
    zones = [
        presets_mod.build_zone_from_city(city, km=presets_mod.DEFAULT_RADIUS_KM)
        for city in city_list
    ]
    home_city = str(zones[0]["name"])
    mobility = ", ".join(str(z["name"]) for z in zones)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "preset": preset.id,
        "contracts": list(contracts),
        "zone_preset": "standalone_example",
        "zones": zones,
        "job_radius_km": DEFAULT_JOB_RADIUS_KM,
        "candidate": {
            "name": "Alex Martin",
            "first_name": "Alex",
            "last_name": "Martin",
            "email": "alex.martin@example.org",
            "phone": "06 00 00 00 00",
            "level": "Bac+3",
            "school": "Université Exemple",
            "track": preset.label,
            "home": home_city,
            "mobility": mobility,
            "weeks": 16,
            "start": "2027-01-18",
            "end": "2027-05-14",
            "linkedin_url": "https://www.linkedin.com/in/alex-martin-example",
            "github_url": "https://github.com/alex-martin-example",
            "portfolio_url": "",
            "address": home_city,
            "postal_code": "75000" if home_city == "Paris" else "",
        },
        "facts": [
            f"Étudiant en Bac+3 orienté {preset.label}.",
            f"Mobile sur les bassins {mobility}.",
            "Approche rigoureuse, documentation claire et autonomie opérationnelle.",
        ],
        "form_answers": {
            "Disponibilité": "À partir de janvier 2027 (16 semaines minimum)",
            "Mobilité": mobility,
            "Langues": "Français natif, Anglais B2",
        },
        "job_form_answers": {
            "Disponibilité": "Temps partiel (soirs, week-ends) et vacances scolaires",
            "Mobilité": f"{home_city} et environs (15 km)",
        },
        "skills": {
            "owned": sorted(preset.default_owned),
            "extra_weights": {},
        },
        "preferences": {
            "min_score": 80,
            "auto_hellowork_min_score": 60,
            "daily_target": 10,
            "daily_max": 20,
            "allow_pure_software_dev": None,
            "custom_stage_titles": [],
            "custom_stage_queries": [],
            "custom_exclude_keywords": [],
        },
    }
    return validate_and_normalize_profile_payload(payload)
