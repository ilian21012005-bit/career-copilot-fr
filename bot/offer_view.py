"""Offer categorization and display enrichment for Mission Control.

Les zones se basent sur la distance à vol d'oiseau (Haversine) vers les
bassins actifs de `hellowork.basins` — jamais sur le seul numéro de
département. Les heuristiques rapides historiques ne s'appliquent que si
les bassins correspondants sont présents dans `basins.ZONE_NAMES`.
"""

from __future__ import annotations

import re

from hellowork import basins, geo
from hellowork.basins import ZONE_LABELS  # noqa: F401 — dict muté en place par basins
from hellowork.text import fold

_PESSAC_HINTS = (
    "pessac",
    "bordeaux",
    "mérignac",
    "merignac",
    "talence",
    "begles",
    "bègles",
)
_MANTES_HINTS = (
    "mantes-la-jolie",
    "mantes la jolie",
    "limay",
    "porcheville",
    "buchelay",
)
_VILLEBON_HINTS = (
    "villebon",
    "orsay",
    "palaiseau",
    "massy",
    "saclay",
    "velizy",
    "vélizy",
    "gif-sur-yvette",
    "gif sur yvette",
    "les ulis",
    "bures",
    "igny",
    "chilly",
    "longjumeau",
    "antony",
    "clamart",
    "issy",
    "boulogne",
    "meudon",
    "sevres",
    "sèvres",
    "versailles",
    "velizy-villacoublay",
    "trappes",
    "montigny",
    "la défense",
    "la defense",
    "courbevoie",
    "puteaux",
    "nanterre",
    "rueil",
    "suresnes",
    "levallois",
    "neuilly",
    "saint-cloud",
    "saint cloud",
)
_ALTERNANCE_MARKERS = (
    "alternance",
    "apprentissage",
    "contrat pro",
    "professionnalisation",
    "alternant",
    "apprenti",
)


def _classify_zone(city: str | None, km: float | None = None) -> tuple[str, str]:
    """Classement bassin pour l'UI : heuristique dynamique puis cache géo hors-ligne."""
    if not city:
        return ("", "Localisation inconnue")
    s = city.lower()
    folded_city = fold(city)
    active_names = set(basins.ZONE_NAMES)

    if "Pessac" in active_names and any(k in s for k in _PESSAC_HINTS):
        return ("Pessac", basins.label_for("Pessac"))
    if "Mantes-la-Jolie" in active_names and any(k in s for k in _MANTES_HINTS):
        return ("Mantes-la-Jolie", basins.label_for("Mantes-la-Jolie"))
    if "Villebon-sur-Yvette" in active_names and (
        re.search(r"\bparis\b", s) or any(k in s for k in _VILLEBON_HINTS)
    ):
        return ("Villebon-sur-Yvette", basins.label_for("Villebon-sur-Yvette"))

    for zone in basins.ZONES:
        zone_name = str(zone.get("name") or "")
        zone_folded = fold(zone_name)
        if zone_folded and re.search(
            rf"(^|[^a-z0-9]){re.escape(zone_folded)}([^a-z0-9]|$)",
            folded_city,
        ):
            return (zone_name, basins.label_for(zone_name))

    point = geo.geocode(city, "", network=False)
    if not point:
        return ("", f"À vérifier ({city})")
    loc = geo.locate(point[0], point[1])
    z = loc["zone"] if loc["status"] == "in_zone" else ""
    if not z:
        return ("", f"Hors rayon ({city}, {loc['distance_km']} km du plus proche)")
    return (z, basins.label_for(z))


def _zone_payload(lat, lon, city: str | None = None) -> dict:
    loc = (
        geo.locate(lat, lon)
        if lat is not None and lon is not None
        else {
            "zone": "",
            "distance_km": None,
            "status": "unknown",
            "distances": {},
            "basins": [],
        }
    )
    if loc["status"] == "unknown" and city:
        z, zl = _classify_zone(city, None)
        return {
            "zone": z,
            "zone_label": zl,
            "distance_km": None,
            "location_status": "unknown" if not z else "in_zone",
            "distances": {},
            "basins": [z] if z else [],
        }
    label = basins.label_for(loc["zone"])
    if loc["status"] == "out_zone":
        label = f"Hors rayon — plus proche {loc['zone']} ({loc['distance_km']} km)"
    return {
        "zone": loc["zone"] if loc["status"] == "in_zone" else "",
        "zone_nearest": loc["zone"],
        "zone_label": label,
        "distance_km": loc["distance_km"],
        "location_status": loc["status"],
        "distances": loc.get("distances") or {},
        "basins": loc.get("basins") or [],
    }


def _enrich_row(r: dict) -> dict:
    t = fold(str(r.get("type") or ""))
    c = fold(str(r.get("contract") or ""))
    p = fold(str(r.get("title") or ""))
    combined = f"{t} {c} {p}"

    is_alternance = any(marker in combined for marker in _ALTERNANCE_MARKERS)
    is_stage = (not is_alternance) and (
        "stage" in t
        or "stage" in c
        or "stage" in p
        or "intern" in p
        or "stagiaire" in p
    )
    r["is_alternance"] = is_alternance
    r["is_stage"] = is_stage
    if is_alternance:
        r["category"] = "Alternance"
    elif is_stage:
        r["category"] = "Stage"
    else:
        r["category"] = "Job étudiant"

    lat = r.get("latitude")
    lon = r.get("longitude")
    try:
        lat = float(lat) if lat not in (None, "") else None
        lon = float(lon) if lon not in (None, "") else None
    except (TypeError, ValueError):
        lat = lon = None

    payload = _zone_payload(lat, lon, r.get("city"))
    r.update(payload)
    return r
