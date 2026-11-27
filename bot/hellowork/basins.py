"""Bassins géographiques stage / alternance / job — source unique dynamique.

Tous les modules (geo, score, config, offer_view, dashboard) doivent
importer d'ici. Les zones sont alimentées depuis `candidate_config.get_profile()`
et mises à jour à chaud via `register_reload_listener`.
Rayons = distance à vol d'oiseau (Haversine).
"""

from __future__ import annotations

from typing import TypedDict

import candidate_config


class Zone(TypedDict, total=False):
    name: str
    department: str
    lat: float
    lon: float
    insee: str
    km: float
    label: str


# Stage / alternance : rayon en km (mis à jour dynamiquement depuis le profil).
RADIUS_KM: float = 30.0
# Job étudiant : rayon serré autour des zones actives.
JOB_RADIUS_KM: float = 15.0

ZONES: tuple[Zone, ...] = ()
ZONE_LABELS: dict[str, str] = {}
ZONE_NAMES: tuple[str, ...] = ()


def _sync_from_config(cfg: candidate_config.CandidateProfileConfig) -> None:
    """Synchronise les bassins actifs à partir d'un `CandidateProfileConfig`."""
    global RADIUS_KM, JOB_RADIUS_KM, ZONES, ZONE_NAMES

    built_zones: list[Zone] = []
    labels: dict[str, str] = {}
    for raw_zone in cfg.zones:
        zone: Zone = {
            "name": str(raw_zone["name"]),
            "department": str(raw_zone.get("department") or ""),
            "insee": str(raw_zone.get("insee") or ""),
            "lat": float(raw_zone["lat"]),
            "lon": float(raw_zone["lon"]),
            "km": float(raw_zone.get("km", 30.0)),
        }
        built_zones.append(zone)
        labels[zone["name"]] = str(raw_zone.get("label") or zone["name"])

    ZONES = tuple(built_zones)
    ZONE_LABELS.clear()
    ZONE_LABELS.update(labels)
    ZONE_NAMES = tuple(z["name"] for z in ZONES)
    RADIUS_KM = float(max((float(z.get("km", 30.0)) for z in ZONES), default=30.0))
    JOB_RADIUS_KM = float(cfg.job_radius_km)


_sync_from_config(candidate_config.get_profile())
candidate_config.register_reload_listener(_sync_from_config)


def label_for(name: str) -> str:
    return ZONE_LABELS.get(name, name or "Hors zone")
