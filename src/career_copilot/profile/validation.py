"""Strict v1/v2 candidate profile block validation and normalization."""

from __future__ import annotations

import html
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from career_copilot.profile.model import (
    DEFAULT_END_DATE,
    DEFAULT_JOB_RADIUS_KM,
    DEFAULT_START_DATE,
    DEFAULT_WEEKS,
    MAX_CUSTOM_EXCLUDES,
    MAX_CUSTOM_QUERIES,
    MAX_CUSTOM_TITLES,
    MAX_EXTRA_WEIGHTS,
    MAX_FACT_LEN,
    MAX_FACTS,
    MAX_FORM_ANSWERS,
    MAX_FORM_KEY_LEN,
    MAX_FORM_VAL_LEN,
    MAX_OWNED_SKILLS,
    MAX_SKILL_LEN,
    MAX_ZONES,
    SCHEMA_VERSION,
)
from career_copilot.profile.presets_access import get_presets_module
from career_copilot.profile.validators_primitives import (
    is_list_like,
    parse_date_iso,
    require_float,
    require_int,
    require_str,
    validate_contracts,
    validate_https_url,
    validate_string_list,
    validate_string_map,
    validate_zone,
)

_CANDIDATE_STRING_LIMITS: dict[str, int] = {
    "name": 120,
    "first_name": 80,
    "last_name": 80,
    "email": 160,
    "phone": 40,
    "level": 100,
    "school": 160,
    "track": 160,
    "home": 120,
    "mobility": 240,
    "address": 200,
    "postal_code": 20,
}
_CANDIDATE_URL_FIELDS: tuple[str, ...] = ("linkedin_url", "github_url", "portfolio_url")


def is_v1_payload(raw: Mapping[str, Any]) -> bool:
    """Return True when payload follows the legacy v1 schema."""
    version = raw.get("schema_version")
    if version == 1:
        return True
    if version is not None:
        return False
    return any(key in raw for key in ("CANDIDATE", "FACTS", "FORM_ANSWERS"))


def migrate_v1_raw_to_v2_input(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a legacy v1 payload (`CANDIDATE`, `FACTS`, `FORM_ANSWERS`) into v2 shape."""
    presets_mod = get_presets_module()
    v1_cand = raw.get("CANDIDATE")
    if v1_cand is None:
        v1_cand = {}
    if not isinstance(v1_cand, Mapping):
        raise ValueError("Le bloc v1 « CANDIDATE » doit être un objet JSON.")
    converted: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "preset": raw.get("preset") or presets_mod.DEFAULT_PRESET_ID,
        "contracts": raw.get("contracts") if "contracts" in raw else ["stage", "job"],
        "zone_preset": raw.get("zone_preset") or presets_mod.DEFAULT_ZONE_PRESET_ID,
        "candidate": dict(v1_cand),
        "facts": raw.get("FACTS") if "FACTS" in raw else raw.get("facts", []),
        "form_answers": (
            raw.get("FORM_ANSWERS") if "FORM_ANSWERS" in raw else raw.get("form_answers", {})
        ),
    }
    for opt_key in (
        "zones",
        "job_radius_km",
        "job_form_answers",
        "skills",
        "preferences",
        "experiences",
        "projects",
        "job_profile",
    ):
        if opt_key in raw:
            converted[opt_key] = raw[opt_key]
    return converted


def _validate_candidate_block(raw_cand: Any) -> dict[str, Any]:
    if raw_cand is None:
        raw_cand = {}
    if not isinstance(raw_cand, Mapping):
        raise ValueError("Le champ « candidate » doit être un objet JSON.")

    candidate: dict[str, Any] = {
        key: require_str(raw_cand.get(key, ""), f"candidate.{key}", max_len=max_len)
        for key, max_len in _CANDIDATE_STRING_LIMITS.items()
    }
    if not candidate["name"] and (candidate["first_name"] or candidate["last_name"]):
        candidate["name"] = f"{candidate['first_name']} {candidate['last_name']}".strip()

    email = candidate["email"]
    if email and (
        "@" not in email or any(ch.isspace() for ch in email) or "." not in email.split("@", 1)[1]
    ):
        raise ValueError("L'adresse email du candidat est invalide.")

    for url_field in _CANDIDATE_URL_FIELDS:
        candidate[url_field] = validate_https_url(
            raw_cand.get(url_field, ""), f"candidate.{url_field}"
        )

    candidate["weeks"] = require_int(
        raw_cand.get("weeks", DEFAULT_WEEKS), "candidate.weeks", min_val=1, max_val=156
    )
    start_iso = parse_date_iso(raw_cand.get("start"), "candidate.start", default=DEFAULT_START_DATE)
    start_dt = date.fromisoformat(start_iso)
    raw_end = raw_cand.get("end")
    if raw_end is None or (isinstance(raw_end, str) and not raw_end.strip()):
        computed_end = (
            DEFAULT_END_DATE
            if start_dt == DEFAULT_START_DATE and candidate["weeks"] == DEFAULT_WEEKS
            else (start_dt + timedelta(days=max(7, int(candidate["weeks"]) * 7)))
        )
        end_iso = computed_end.isoformat()
    else:
        end_iso = parse_date_iso(raw_end, "candidate.end", default=DEFAULT_END_DATE)
    if date.fromisoformat(end_iso) < start_dt:
        raise ValueError("La date de fin doit être postérieure ou égale à la date de début.")
    candidate["start"] = start_iso
    candidate["end"] = end_iso
    return candidate


def _validate_skills_block(raw_skills: Any) -> dict[str, Any]:
    if raw_skills is None:
        raw_skills = {}
    if not isinstance(raw_skills, Mapping):
        raise ValueError("Le champ « skills » doit être un objet JSON.")
    owned_raw = raw_skills.get("owned")
    owned: list[str] | None = None
    if owned_raw is not None:
        owned = [
            html.unescape(s).strip().lower()
            for s in validate_string_list(
                owned_raw,
                "skills.owned",
                max_items=MAX_OWNED_SKILLS,
                max_item_len=MAX_SKILL_LEN,
            )
            if html.unescape(s).strip()
        ]

    raw_extra_weights = raw_skills.get("extra_weights")
    extra_weights: dict[str, int] = {}
    if raw_extra_weights is not None:
        if not isinstance(raw_extra_weights, Mapping):
            raise ValueError("Le champ « skills.extra_weights » doit être un objet clé/poids.")
        if len(raw_extra_weights) > MAX_EXTRA_WEIGHTS:
            raise ValueError(
                f"Le champ « skills.extra_weights » dépasse {MAX_EXTRA_WEIGHTS} entrées."
            )
        for skill_name, weight in raw_extra_weights.items():
            key_label = "skills.extra_weights" + ".key"
            clean_skill = require_str(skill_name, key_label, max_len=MAX_SKILL_LEN).lower()
            if clean_skill:
                extra_weights[clean_skill] = require_int(
                    weight, f"skills.extra_weights[{clean_skill}]", min_val=1, max_val=20
                )

    skills_block: dict[str, Any] = {"extra_weights": extra_weights}
    if owned is not None:
        skills_block["owned"] = owned
    return skills_block


def _validate_preferences_block(raw_prefs: Any) -> dict[str, Any]:
    if raw_prefs is None:
        raw_prefs = {}
    if not isinstance(raw_prefs, Mapping):
        raise ValueError("Le champ « preferences » doit être un objet JSON.")

    min_score = require_int(
        raw_prefs.get("min_score", 80), "preferences.min_score", min_val=0, max_val=100
    )
    auto_min = require_int(
        raw_prefs.get("auto_hellowork_min_score", 60),
        "preferences.auto_hellowork_min_score",
        min_val=0,
        max_val=100,
    )
    daily_target = require_int(
        raw_prefs.get("daily_target", 10), "preferences.daily_target", min_val=1, max_val=100
    )
    daily_max = require_int(
        raw_prefs.get("daily_max", 20), "preferences.daily_max", min_val=1, max_val=200
    )
    if daily_max < daily_target:
        raise ValueError(
            "« preferences.daily_max » doit être supérieur ou égal à « daily_target »."
        )
    raw_allow_dev = raw_prefs.get("allow_pure_software_dev")
    if raw_allow_dev is not None and type(raw_allow_dev) is not bool:
        raise ValueError("« preferences.allow_pure_software_dev » doit être un booléen ou nul.")
    return {
        "min_score": min_score,
        "auto_hellowork_min_score": auto_min,
        "daily_target": daily_target,
        "daily_max": daily_max,
        "allow_pure_software_dev": raw_allow_dev,
        "custom_stage_titles": validate_string_list(
            raw_prefs.get("custom_stage_titles"),
            "preferences.custom_stage_titles",
            max_items=MAX_CUSTOM_TITLES,
            max_item_len=120,
        ),
        "custom_stage_queries": validate_string_list(
            raw_prefs.get("custom_stage_queries"),
            "preferences.custom_stage_queries",
            max_items=MAX_CUSTOM_QUERIES,
            max_item_len=160,
        ),
        "custom_exclude_keywords": validate_string_list(
            raw_prefs.get("custom_exclude_keywords"),
            "preferences.custom_exclude_keywords",
            max_items=MAX_CUSTOM_EXCLUDES,
            max_item_len=80,
        ),
    }


def _validate_experiences(raw_exps: Any) -> list[dict[str, Any]]:
    if raw_exps is None:
        return []
    if not is_list_like(raw_exps) or len(raw_exps) > 20:
        raise ValueError("Le champ « experiences » doit être une liste (max 20).")
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_exps):
        if not isinstance(item, Mapping):
            raise ValueError(f"experiences[{idx}] doit être un objet JSON.")
        out.append(
            {
                "company": require_str(
                    item.get("company", ""), f"experiences[{idx}].company", max_len=120
                ),
                "location": require_str(
                    item.get("location", ""), f"experiences[{idx}].location", max_len=120
                ),
                "dates": require_str(
                    item.get("dates", ""), f"experiences[{idx}].dates", max_len=80
                ),
                "role": require_str(item.get("role", ""), f"experiences[{idx}].role", max_len=160),
                "bullets": validate_string_list(
                    item.get("bullets"),
                    f"experiences[{idx}].bullets",
                    max_items=10,
                    max_item_len=350,
                ),
                "tags": validate_string_list(
                    item.get("tags"), f"experiences[{idx}].tags", max_items=15, max_item_len=40
                ),
            }
        )
    return out


def _validate_projects(raw_projs: Any) -> list[dict[str, Any]]:
    if raw_projs is None:
        return []
    if not is_list_like(raw_projs) or len(raw_projs) > 20:
        raise ValueError("Le champ « projects » doit être une liste (max 20).")
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_projs):
        if not isinstance(item, Mapping):
            raise ValueError(f"projects[{idx}] doit être un objet JSON.")
        out.append(
            {
                "name": require_str(item.get("name", ""), f"projects[{idx}].name", max_len=120),
                "summary": require_str(
                    item.get("summary", ""), f"projects[{idx}].summary", max_len=400
                ),
                "url": validate_https_url(item.get("url", ""), f"projects[{idx}].url"),
                "tags": validate_string_list(
                    item.get("tags"), f"projects[{idx}].tags", max_items=15, max_item_len=40
                ),
            }
        )
    return out


def _validate_job_profile(raw_job_profile: Any) -> dict[str, Any]:
    default_jp = {
        "confirmed_tasks": [],
        "retail_context": "en accueil et relation client",
        "summary_sentences": [],
    }
    if raw_job_profile is None:
        return default_jp
    if not isinstance(raw_job_profile, Mapping):
        raise ValueError("Le champ « job_profile » doit être un objet JSON.")
    return {
        "confirmed_tasks": validate_string_list(
            raw_job_profile.get("confirmed_tasks", default_jp["confirmed_tasks"]),
            "job_profile.confirmed_tasks",
            max_items=20,
            max_item_len=80,
        ),
        "retail_context": require_str(
            raw_job_profile.get("retail_context", default_jp["retail_context"]),
            "job_profile.retail_context",
            max_len=140,
        )
        or default_jp["retail_context"],
        "summary_sentences": validate_string_list(
            raw_job_profile.get("summary_sentences", default_jp["summary_sentences"]),
            "job_profile.summary_sentences",
            max_items=6,
            max_item_len=350,
        ),
    }


def validate_and_normalize_profile_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a v1 or v2 profile payload strictly and return normalized schema v2."""
    if not isinstance(raw, Mapping):
        raise ValueError("Le profil candidat doit être un objet JSON.")

    presets_mod = get_presets_module()
    data: Mapping[str, Any] = migrate_v1_raw_to_v2_input(raw) if is_v1_payload(raw) else raw

    version = data.get("schema_version", SCHEMA_VERSION)
    if type(version) is bool or version not in (1, 2):
        raise ValueError("La version du schéma profil doit être 1 ou 2.")

    raw_preset = data.get("preset", presets_mod.DEFAULT_PRESET_ID)
    preset_id = (
        require_str(raw_preset, "preset", max_len=64).lower() or presets_mod.DEFAULT_PRESET_ID
    )
    if preset_id not in presets_mod.CAREER_PRESETS:
        known = ", ".join(presets_mod.CAREER_PRESETS.keys())
        raise ValueError(f"Preset métier inconnu : « {raw_preset} » (disponibles : {known}).")
    preset = presets_mod.CAREER_PRESETS[preset_id]
    contracts = validate_contracts(
        data.get("contracts"), default_contracts=preset.default_contracts
    )

    raw_zone_preset = data.get("zone_preset", presets_mod.DEFAULT_ZONE_PRESET_ID)
    zone_preset = (
        require_str(raw_zone_preset, "zone_preset", max_len=64)
        or presets_mod.DEFAULT_ZONE_PRESET_ID
    )
    if zone_preset not in presets_mod.ZONE_PRESETS:
        known_zp = ", ".join(presets_mod.ZONE_PRESETS.keys())
        raise ValueError(
            f"Preset géographique inconnu : « {raw_zone_preset} » (disponibles : {known_zp})."
        )

    raw_zones = data.get("zones")
    if raw_zones is None:
        zones = [dict(z) for z in presets_mod.ZONE_PRESETS[zone_preset]]
    else:
        if not isinstance(raw_zones, (list, tuple)) or not raw_zones:
            raise ValueError("Le champ « zones » doit contenir au moins une zone géographique.")
        if len(raw_zones) > MAX_ZONES:
            raise ValueError(f"Nombre maximal de zones dépassé ({MAX_ZONES} maximum).")
        zones = [validate_zone(item, idx) for idx, item in enumerate(raw_zones)]

    job_radius_km = require_float(
        data.get("job_radius_km", DEFAULT_JOB_RADIUS_KM),
        "job_radius_km",
        min_val=presets_mod.MIN_RADIUS_KM,
        max_val=presets_mod.MAX_RADIUS_KM,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "preset": preset_id,
        "contracts": contracts,
        "zone_preset": zone_preset,
        "zones": zones,
        "job_radius_km": job_radius_km,
        "candidate": _validate_candidate_block(data.get("candidate")),
        "facts": validate_string_list(
            data.get("facts"), "facts", max_items=MAX_FACTS, max_item_len=MAX_FACT_LEN
        ),
        "form_answers": validate_string_map(
            data.get("form_answers"),
            "form_answers",
            max_items=MAX_FORM_ANSWERS,
            max_key_len=MAX_FORM_KEY_LEN,
            max_val_len=MAX_FORM_VAL_LEN,
        ),
        "job_form_answers": validate_string_map(
            data.get("job_form_answers"),
            "job_form_answers",
            max_items=MAX_FORM_ANSWERS,
            max_key_len=MAX_FORM_KEY_LEN,
            max_val_len=MAX_FORM_VAL_LEN,
        ),
        "skills": _validate_skills_block(data.get("skills")),
        "preferences": _validate_preferences_block(data.get("preferences")),
        "experiences": _validate_experiences(data.get("experiences")),
        "projects": _validate_projects(data.get("projects")),
        "job_profile": _validate_job_profile(data.get("job_profile")),
    }
