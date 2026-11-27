"""Catalogue immuable de presets métiers, villes étudiantes et zones géographiques.

Source Unique de Vérité (SSOT) : ``presets_data/presets.json``, chargé une seule
fois à l'import du module et reconstruit en structures Python immuables.
Aucune donnée personnelle dans ce module : tous les libellés, modèles de pistes CV
et groupes d'adéquation sont génériques et réutilisables par tout candidat.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

DEFAULT_RADIUS_KM = 30.0
MIN_RADIUS_KM = 1.0
MAX_RADIUS_KM = 150.0

_PRESETS_JSON_PATH = Path(__file__).resolve().parent / "presets_data" / "presets.json"


@dataclass(frozen=True)
class CVTrackSpec:
    """Définition d'une piste CV pour un preset métier."""

    key: str
    label: str
    profile: str
    targets: str
    keywords: tuple[str, ...]
    skill_order: tuple[str, ...] = ()


@dataclass(frozen=True)
class CareerPreset:
    """Preset métier immuable pilotant recherche, scoring, filtres et CV."""

    id: str
    label: str
    description: str
    default_contracts: tuple[str, ...]
    rome_codes: tuple[str, ...]
    target_domains: tuple[str, ...]
    stage_titles: tuple[str, ...]
    adzuna_stage_queries: tuple[str, ...]
    stage_must: tuple[str, ...]
    target_keywords: tuple[str, ...]
    skills_weights: Mapping[str, int]
    core_skills: tuple[str, ...]
    default_owned: frozenset[str]
    allow_pure_software_dev: bool
    off_target_hard: tuple[str, ...]
    off_target_soft: tuple[str, ...]
    operational_keep: tuple[str, ...]
    cv_tracks: Mapping[str, CVTrackSpec]
    default_cv_track: str
    default_skill_blocks: Mapping[str, tuple[str, str]]
    fit_groups: tuple[tuple[str, tuple[str, ...], str], ...]


def _fold_lookup(value: str) -> str:
    lowered = str(value or "").strip().lower().replace("’", "'")
    normalized = unicodedata.normalize("NFD", lowered)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    cleaned = "".join(ch if ch.isalnum() else " " for ch in stripped)
    return " ".join(cleaned.split())


def _freeze_mapping(data: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(data))


def _as_str_tuple(raw: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in raw)


def _read_catalog_json(path: Path = _PRESETS_JSON_PATH) -> dict[str, Any]:
    """Lit et valide le catalogue déclaratif `presets_data/presets.json`."""
    if not path.is_file():
        raise FileNotFoundError(f"Catalogue presets introuvable : {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"Catalogue presets invalide (objet JSON attendu) : {path}")
    if "presets" not in data:
        raise ValueError(f"Catalogue presets incomplet ('presets' manquant) : {path}")
    if not isinstance(data["presets"], dict):
        raise TypeError(f"Catalogue presets invalide ('presets' doit être un objet) : {path}")
    return data


def _build_cities(
    raw_cities: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Mapping[str, Any]]:
    frozen: dict[str, Mapping[str, Any]] = {}
    for cid, entry in raw_cities.items():
        city_id = str(cid)
        frozen[city_id] = MappingProxyType(
            {
                "id": str(entry.get("id", city_id)),
                "name": str(entry["name"]),
                "department": str(entry["department"]),
                "insee": str(entry["insee"]),
                "lat": float(entry["lat"]),
                "lon": float(entry["lon"]),
                "label": str(entry["label"]),
            }
        )
    return MappingProxyType(frozen)


def _build_city_lookup(cities: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for cid, city in cities.items():
        lookup[_fold_lookup(cid)] = cid
        lookup[_fold_lookup(city["name"])] = cid
        lookup[_fold_lookup(city["label"])] = cid
    for alias, target in (
        ("saclay", "orsay_saclay"),
        ("plateau de saclay", "orsay_saclay"),
        ("aix", "aix_en_provence"),
    ):
        if target in cities:
            lookup[alias] = target
    return lookup


def _build_zone_presets(
    raw_zones: Mapping[str, Any],
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    frozen: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for zid, zones in raw_zones.items():
        frozen[str(zid)] = tuple(
            MappingProxyType(
                {
                    "name": str(zone["name"]),
                    "department": str(zone["department"]),
                    "insee": str(zone["insee"]),
                    "lat": float(zone["lat"]),
                    "lon": float(zone["lon"]),
                    "km": float(zone["km"]),
                    "label": str(zone["label"]),
                }
            )
            for zone in zones
        )
    return MappingProxyType(frozen)


def _build_cv_track(key: str, raw: Mapping[str, Any]) -> CVTrackSpec:
    return CVTrackSpec(
        key=str(raw.get("key", key)),
        label=str(raw["label"]),
        profile=str(raw["profile"]),
        targets=str(raw["targets"]),
        keywords=_as_str_tuple(raw["keywords"]),
        skill_order=_as_str_tuple(raw.get("skill_order", ())),
    )


def _build_career_preset(preset_id: str, raw: Mapping[str, Any]) -> CareerPreset:
    return CareerPreset(
        id=str(raw.get("id", preset_id)),
        label=str(raw["label"]),
        description=str(raw["description"]),
        default_contracts=_as_str_tuple(raw["default_contracts"]),
        rome_codes=_as_str_tuple(raw["rome_codes"]),
        target_domains=_as_str_tuple(raw["target_domains"]),
        stage_titles=_as_str_tuple(raw["stage_titles"]),
        adzuna_stage_queries=_as_str_tuple(raw["adzuna_stage_queries"]),
        stage_must=_as_str_tuple(raw["stage_must"]),
        target_keywords=_as_str_tuple(raw["target_keywords"]),
        skills_weights=MappingProxyType(
            {str(k): int(v) for k, v in raw["skills_weights"].items()}
        ),
        core_skills=_as_str_tuple(raw["core_skills"]),
        default_owned=frozenset(str(item) for item in raw["default_owned"]),
        allow_pure_software_dev=bool(raw["allow_pure_software_dev"]),
        off_target_hard=_as_str_tuple(raw["off_target_hard"]),
        off_target_soft=_as_str_tuple(raw["off_target_soft"]),
        operational_keep=_as_str_tuple(raw["operational_keep"]),
        cv_tracks=MappingProxyType(
            {
                str(tk): _build_cv_track(str(tk), tv)
                for tk, tv in raw["cv_tracks"].items()
            }
        ),
        default_cv_track=str(raw["default_cv_track"]),
        default_skill_blocks=MappingProxyType(
            {
                str(bk): (str(pair[0]), str(pair[1]))
                for bk, pair in raw["default_skill_blocks"].items()
            }
        ),
        fit_groups=tuple(
            (
                str(group["key"]),
                _as_str_tuple(group["keywords"]),
                str(group["label"]),
            )
            for group in raw["fit_groups"]
        ),
    )


def _build_career_presets(
    raw_presets: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, CareerPreset]:
    return MappingProxyType(
        {
            str(pid): _build_career_preset(str(pid), payload)
            for pid, payload in raw_presets.items()
        }
    )


def _load_catalog_state() -> tuple[
    tuple[str, ...],
    str,
    str,
    Mapping[str, Mapping[str, Any]],
    dict[str, str],
    Mapping[str, tuple[Mapping[str, Any], ...]],
    Mapping[str, CareerPreset],
]:
    raw = _read_catalog_json(_PRESETS_JSON_PATH)
    cities = _build_cities(raw["cities"])
    return (
        _as_str_tuple(raw["valid_contracts"]),
        str(raw["default_preset"]),
        str(raw["default_zone_preset"]),
        cities,
        _build_city_lookup(cities),
        _build_zone_presets(raw["zone_presets"]),
        _build_career_presets(raw["presets"]),
    )


(
    VALID_CONTRACTS,
    DEFAULT_PRESET_ID,
    DEFAULT_ZONE_PRESET_ID,
    FRENCH_STUDENT_CITIES,
    _CITY_LOOKUP,
    ZONE_PRESETS,
    CAREER_PRESETS,
) = _load_catalog_state()


def get_city(city_id_or_name: str) -> dict[str, Any]:
    """Retourne une copie d'une ville étudiante par identifiant ou nom."""
    if not isinstance(city_id_or_name, str) or not city_id_or_name.strip():
        raise KeyError(f"Ville inconnue : {city_id_or_name!r}")
    key = _fold_lookup(city_id_or_name)
    city_id = _CITY_LOOKUP.get(key)
    if city_id is None:
        raise KeyError(f"Ville inconnue : {city_id_or_name!r}")
    return dict(FRENCH_STUDENT_CITIES[city_id])


def build_zone_from_city(
    city_id_or_name: str, km: float = DEFAULT_RADIUS_KM
) -> dict[str, Any]:
    """Construit un dictionnaire Zone prêt pour la recherche géographique."""
    if type(km) is bool:
        raise ValueError("Le rayon géographique doit être un nombre.")
    try:
        radius = float(km)
    except (TypeError, ValueError) as exc:
        raise ValueError("Le rayon géographique doit être un nombre.") from exc
    if not math.isfinite(radius) or radius < MIN_RADIUS_KM or radius > MAX_RADIUS_KM:
        raise ValueError(
            f"Le rayon géographique doit être compris entre {MIN_RADIUS_KM:g} et {MAX_RADIUS_KM:g} km."
        )
    city = get_city(city_id_or_name)
    return {
        "name": city["name"],
        "department": city["department"],
        "insee": city["insee"],
        "lat": float(city["lat"]),
        "lon": float(city["lon"]),
        "km": radius,
        "label": city["label"],
    }


def get_preset(preset_id: str) -> CareerPreset:
    """Retourne le CareerPreset correspondant à l'identifiant demandé."""
    if not isinstance(preset_id, str):
        raise KeyError(f"Preset métier inconnu : {preset_id!r}")
    normalized = preset_id.strip().lower()
    preset = CAREER_PRESETS.get(normalized)
    if preset is None:
        raise KeyError(f"Preset métier inconnu : {preset_id!r}")
    return preset


def _serialize_track(track: CVTrackSpec) -> dict[str, Any]:
    return {
        "key": track.key,
        "label": track.label,
        "profile": track.profile,
        "targets": track.targets,
        "keywords": list(track.keywords),
        "skill_order": list(track.skill_order),
    }


def _serialize_preset(preset: CareerPreset) -> dict[str, Any]:
    return {
        "id": preset.id,
        "label": preset.label,
        "description": preset.description,
        "default_contracts": list(preset.default_contracts),
        "rome_codes": list(preset.rome_codes),
        "target_domains": list(preset.target_domains),
        "stage_titles": list(preset.stage_titles),
        "adzuna_stage_queries": list(preset.adzuna_stage_queries),
        "stage_must": list(preset.stage_must),
        "target_keywords": list(preset.target_keywords),
        "skills_weights": dict(preset.skills_weights),
        "core_skills": list(preset.core_skills),
        "default_owned": sorted(preset.default_owned),
        "allow_pure_software_dev": preset.allow_pure_software_dev,
        "off_target_hard": list(preset.off_target_hard),
        "off_target_soft": list(preset.off_target_soft),
        "operational_keep": list(preset.operational_keep),
        "cv_tracks": {
            key: _serialize_track(spec) for key, spec in preset.cv_tracks.items()
        },
        "default_cv_track": preset.default_cv_track,
        "default_skill_blocks": {
            key: [heading, items]
            for key, (heading, items) in preset.default_skill_blocks.items()
        },
        "fit_groups": [
            {"key": key, "keywords": list(keywords), "label": label}
            for key, keywords, label in preset.fit_groups
        ],
    }


def serialize_presets_catalog() -> dict[str, Any]:
    """Sérialise l'ensemble du catalogue en structure 100 % compatible JSON."""
    return {
        "valid_contracts": list(VALID_CONTRACTS),
        "default_preset": DEFAULT_PRESET_ID,
        "default_zone_preset": DEFAULT_ZONE_PRESET_ID,
        "cities": {cid: dict(city) for cid, city in FRENCH_STUDENT_CITIES.items()},
        "zone_presets": {
            zid: [dict(zone) for zone in zones] for zid, zones in ZONE_PRESETS.items()
        },
        "presets": {
            pid: _serialize_preset(preset) for pid, preset in CAREER_PRESETS.items()
        },
    }


def load_presets_catalog_json() -> dict[str, Any]:
    """Charge le catalogue JSON déclaratif depuis `presets_data/presets.json`."""
    return _read_catalog_json(_PRESETS_JSON_PATH)
