"""Géographie : trois centres, 30 km à vol d'oiseau, géocodage officiel (BAN).

Règles :
- la distance est une distance à vol d'oiseau (Haversine), pas une distance
  routière ;
- une offre est retenue si elle est à 30 km ou moins d'au moins un des trois
  centres ;
- quand la ville n'est pas géocodable de façon fiable, l'offre est marquée
  « à vérifier » : on ne lui invente pas de distance.
"""

from __future__ import annotations

import file_lock as fcntl
import json
import math
import os
import re
import threading
import time
import urllib.parse

from config import DATA_DIR
from private_storage import ensure_private_directory, write_private_text
import public_network

from . import basins as basins_mod
from .text import fold as _fold

CACHE_PATH = DATA_DIR / "hellowork" / "geocache.json"
BAN_URL = "https://data.geopf.fr/geocodage/search/"
EARTH_RADIUS_KM = 6371.0088
MIN_BAN_SCORE = 0.7

_cache: dict[str, dict | None] | None = None
_cache_signature: tuple | None = None
_NEGATIVE_TTL = 6 * 60 * 60
_CACHE_SIZE = 4096
_CACHE_LOCK = threading.Lock()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance à vol d'oiseau entre deux points, en kilomètres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def distances_to_zones(lat: float, lon: float) -> dict[str, float]:
    """Distance à vol d'oiseau vers chaque centre de bassin."""
    return {
        zone["name"]: round(haversine_km(lat, lon, zone["lat"], zone["lon"]), 1)
        for zone in basins_mod.ZONES
    }


def _zone_radius_map() -> dict[str, float]:
    return {
        str(zone.get("name") or ""): float(zone.get("km") or basins_mod.RADIUS_KM)
        for zone in basins_mod.ZONES
    }


def nearest_zone(lat: float, lon: float) -> tuple[dict, float]:
    """Centre le plus proche et distance à vol d'oiseau."""
    best = basins_mod.ZONES[0]
    best_km = haversine_km(lat, lon, best["lat"], best["lon"])
    for zone in basins_mod.ZONES[1:]:
        distance = haversine_km(lat, lon, zone["lat"], zone["lon"])
        if distance < best_km:
            best, best_km = zone, distance
    return best, best_km


def locate(lat: float | None, lon: None | float) -> dict:
    """Zone la plus proche, distances vers les bassins, statut.

    `zone` = bassin le plus proche (même hors rayon) pour l'affichage.
    `basins` = bassins réellement dans le rayon individuel de chaque zone.
    `distance_km` = distance vers le bassin le plus proche.
    """
    if lat is None or lon is None:
        return {
            "zone": "",
            "distance_km": None,
            "status": "unknown",
            "distances": {},
            "basins": [],
        }
    lat_f, lon_f = float(lat), float(lon)
    distances = distances_to_zones(lat_f, lon_f)
    zone, distance = nearest_zone(lat_f, lon_f)
    radii = _zone_radius_map()
    basins = [
        name
        for name, km in distances.items()
        if km <= radii.get(name, float(basins_mod.RADIUS_KM))
    ]
    inside = bool(basins)
    return {
        "zone": zone["name"],
        "distance_km": round(distance, 1),
        "status": "in_zone" if inside else "out_zone",
        "distances": distances,
        "basins": basins,
    }


def resolve(offer, geocoder=None) -> object:
    """Remplit latitude/longitude puis zone/distance sur une offre.

    Si l'offre n'a pas de coordonnées et que la ville n'est pas géocodable,
    `location_status` vaut « unknown » : l'offre restera à vérifier.
    """
    latitude = getattr(offer, "latitude", None)
    longitude = getattr(offer, "longitude", None)
    if latitude is None or longitude is None:
        query = geocoder or geocode
        point = query(getattr(offer, "city", ""), getattr(offer, "department", ""))
        if point:
            latitude, longitude = point
    offer.latitude = latitude
    offer.longitude = longitude
    result = locate(latitude, longitude)
    offer.zone = result["zone"]
    offer.distance_km = result["distance_km"]
    offer.location_status = result["status"]
    # attributs optionnels pour API / UI (ignorés si Offer figé)
    try:
        offer.basins = result.get("basins") or []
        offer.distances = result.get("distances") or {}
    except Exception:
        pass
    return offer


_FRENCH_CITY_STOPWORDS = frozenset(
    {
        "l",
        "le",
        "la",
        "les",
        "d",
        "de",
        "du",
        "des",
        "en",
        "sur",
        "sous",
        "a",
        "au",
        "aux",
    }
)

_CITY_ALIASES = {
    "velizy": "Vélizy-Villacoublay",
    "courtaboeuf": "Villebon-sur-Yvette",
    "za courtaboeuf": "Villebon-sur-Yvette",
    "parc de courtaboeuf": "Villebon-sur-Yvette",
    "la defense": "Courbevoie",
    "paris la defense": "Courbevoie",
    "saint quentin en yvelines": "Montigny-le-Bretonneux",
    "st quentin en yvelines": "Montigny-le-Bretonneux",
    "paris saclay": "Saclay",
    "plateau de saclay": "Saclay",
}


def geocode_with_status(
    city: str, department: str = "", *, network: bool = True
) -> tuple[tuple[float, float] | None, str]:
    """Géocode une commune via BAN et indique le statut ('ok', 'ambiguous', 'not_found', 'invalid')."""
    name = _clean_city(city)
    if not name:
        return None, "invalid"
    dept = department or _extract_dept_hint(city)
    key = f"{_fold(name)}|{dept}"
    with _CACHE_LOCK:
        cache = _load_cache()
        cached = cache.get(key)
        if isinstance(cached, dict):
            if isinstance(cached.get("lat"), (float, int)) and isinstance(
                cached.get("lon"), (float, int)
            ):
                return (cached["lat"], cached["lon"]), "ok"
            retry_after = cached.get("retry_after")
            if isinstance(retry_after, (float, int)) and retry_after > time.time():
                return None, "ambiguous" if cached.get("ambiguous") else "not_found"
    if not network:
        return None, "not_found"

    point, status = _query_ban_detailed(name, dept)
    if status not in ("ok", "ambiguous", "not_found"):
        return point, status
    entry = (
        {"lat": point[0], "lon": point[1]}
        if point
        else {
            "lat": None,
            "lon": None,
            "ambiguous": status == "ambiguous",
            "retry_after": int(time.time()) + _NEGATIVE_TTL,
        }
    )
    with _CACHE_LOCK:
        _save_cache(key, entry)
    return point, status


def geocode(
    city: str, department: str = "", *, network: bool = True
) -> tuple[float, float] | None:
    """Coordonnées d'une commune via la Base Adresse Nationale (data.geopf.fr/geocodage).

    network=False : lecture cache locale uniquement (dashboard rapide, pas d'appel BAN).
    """
    point, _status = geocode_with_status(city, department, network=network)
    return point


def _query_ban_detailed(
    name: str, department: str
) -> tuple[tuple[float, float] | None, str]:
    params = urllib.parse.urlencode({"q": name, "limit": 5, "type": "municipality"})
    try:
        status, payload = public_network.get_json(
            BAN_URL + "?" + params,
            headers={
                "User-Agent": "Job-Etudiant/1.0 (usage personnel, geocodage de communes)"
            },
            timeout=15,
            max_bytes=1 * 1024 * 1024,
        )
        if status != 200 or not isinstance(payload, dict):
            return None, "unavailable"
    except Exception:
        return None, "unavailable"

    candidates = []
    for feature in payload.get("features") or []:
        properties = feature.get("properties") or {}
        postcode = str(properties.get("postcode") or "")
        if department and not postcode.startswith(department):
            continue
        prop_name = properties.get("name") or ""
        prop_city = properties.get("city") or ""
        if not (
            _same_name(prop_name, name) or (prop_city and _same_name(prop_city, name))
        ):
            continue
        candidates.append(
            {
                "score": float(properties.get("score") or 0.0),
                "postcode": postcode,
                "lat": float(feature["geometry"]["coordinates"][1]),
                "lon": float(feature["geometry"]["coordinates"][0]),
            }
        )
    if not candidates:
        return None, "not_found"
    candidates.sort(key=lambda item: -item["score"])
    best = candidates[0]
    if best["score"] < MIN_BAN_SCORE:
        return None, "not_found"
    if not department:
        close_depts = {
            c["postcode"][:2]
            for c in candidates
            if c["score"] >= MIN_BAN_SCORE
            and (best["score"] - c["score"]) < 0.05
            and len(c["postcode"]) >= 2
        }
        if len(close_depts) > 1:
            return None, "ambiguous"
    return (best["lat"], best["lon"]), "ok"


def _postcode_to_dept(postcode: str, citycode: str = "") -> str:
    code = str(citycode or "").strip().upper()
    if re.match(r"^(?:2[AB]|97[1-6]|\d{2})", code):
        if code.startswith("97") and len(code) >= 3:
            return code[:3]
        return code[:2]
    pc = str(postcode or "").strip()
    if pc.startswith("97") and len(pc) >= 3:
        return pc[:3]
    if pc.startswith("20") and len(pc) == 5:
        return "2A" if pc[:3] in ("200", "201") else "2B"
    return pc[:2] if len(pc) >= 2 else ""


def _extract_dept_hint(city: str) -> str:
    raw = str(city or "")
    m = re.search(r"\b(97[1-6]\d{2})\b", raw)
    if m:
        return m.group(1)[:3]
    m = re.search(r"\b(20\d{3})\b", raw)
    if m:
        return "2A" if m.group(1)[:3] in ("200", "201") else "2B"
    m = re.search(r"\b(\d{5})\b", raw)
    if m:
        return m.group(1)[:2]
    m = re.search(r"\((2[AB]|97[1-6]|\d{2})\)", raw, re.I)
    if m:
        return m.group(1).upper()
    m = re.match(r"^\s*(2[AB]|97[1-6]|\d{2})\s*[-–]\s*", raw, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\s*[-–]\s*(2[AB]|97[1-6]|\d{2})\s*$", raw, re.I)
    if m:
        return m.group(1).upper()
    if re.search(r"\bparis\s+\d{1,2}(?:e|er|ere|eme)?\b", _fold(raw)):
        return "75"
    return ""


_FALLBACK_COMMUNES: dict[str, dict[str, object]] = {
    "angers": {"name": "Angers", "department": "49", "insee": "49007", "lat": 47.4784, "lon": -0.5632},
    "dijon": {"name": "Dijon", "department": "21", "insee": "21231", "lat": 47.3220, "lon": 5.0415},
    "clermont ferrand": {"name": "Clermont-Ferrand", "department": "63", "insee": "63113", "lat": 45.7772, "lon": 3.0870},
    "tours": {"name": "Tours", "department": "37", "insee": "37261", "lat": 47.3941, "lon": 0.6848},
    "rouen": {"name": "Rouen", "department": "76", "insee": "76540", "lat": 49.4432, "lon": 1.0999},
    "caen": {"name": "Caen", "department": "14", "insee": "14118", "lat": 49.1829, "lon": -0.3707},
    "reims": {"name": "Reims", "department": "51", "insee": "51454", "lat": 49.2583, "lon": 4.0317},
    "metz": {"name": "Metz", "department": "57", "insee": "57463", "lat": 49.1193, "lon": 6.1757},
    "orleans": {"name": "Orléans", "department": "45", "insee": "45234", "lat": 47.9029, "lon": 1.9093},
    "amiens": {"name": "Amiens", "department": "80", "insee": "80021", "lat": 49.8941, "lon": 2.2958},
    "brest": {"name": "Brest", "department": "29", "insee": "29019", "lat": 48.3904, "lon": -4.4861},
    "limoges": {"name": "Limoges", "department": "87", "insee": "87085", "lat": 45.8336, "lon": 1.2611},
    "besancon": {"name": "Besançon", "department": "25", "insee": "25056", "lat": 47.2378, "lon": 6.0241},
    "perpignan": {"name": "Perpignan", "department": "66", "insee": "66136", "lat": 42.6887, "lon": 2.8948},
    "pau": {"name": "Pau", "department": "64", "insee": "64445", "lat": 43.2951, "lon": -0.3708},
    "la rochelle": {"name": "La Rochelle", "department": "17", "insee": "17300", "lat": 46.1603, "lon": -1.1511},
    "poitiers": {"name": "Poitiers", "department": "86", "insee": "86194", "lat": 46.5802, "lon": 0.3404},
    "ajaccio": {"name": "Ajaccio", "department": "2A", "insee": "2A004", "lat": 41.9192, "lon": 8.7386},
    "bastia": {"name": "Bastia", "department": "2B", "insee": "2B033", "lat": 42.6973, "lon": 9.4509},
    "saint denis": {"name": "Saint-Denis", "department": "974", "insee": "97411", "lat": -20.8823, "lon": 55.4504},
    "fort de france": {"name": "Fort-de-France", "department": "972", "insee": "97209", "lat": 14.6161, "lon": -61.0588},
    "pointe a pitre": {"name": "Pointe-à-Pitre", "department": "971", "insee": "97120", "lat": 16.2412, "lon": -61.5361},
    "cayenne": {"name": "Cayenne", "department": "973", "insee": "97302", "lat": 4.9372, "lon": -52.3260},
    "mamoudzou": {"name": "Mamoudzou", "department": "976", "insee": "97611", "lat": -12.7806, "lon": 45.2278},
}


def geocode_municipality(
    query: str,
    *,
    km: float = 30.0,
    network: bool = True,
) -> dict[str, object] | None:
    """Résout n'importe quelle commune française (35 000 communes) avec code INSEE, département et coordonnées."""
    raw = str(query or "").strip()
    if not raw:
        return None
    radius = max(1.0, min(150.0, float(km or 30.0)))
    try:
        import presets

        key_cand = re.sub(r"[^a-z0-9]+", "_", _fold(raw)).strip("_")
        if key_cand in presets.FRENCH_STUDENT_CITIES:
            z = presets.build_zone_from_city(key_cand, km=radius)
            return dict(z)
        cleaned_fold = _fold(_clean_city(raw))
        for cid, entry in presets.FRENCH_STUDENT_CITIES.items():
            if _fold(str(entry.get("name") or "")) == cleaned_fold:
                return dict(presets.build_zone_from_city(cid, km=radius))
    except Exception:
        pass

    dept = _extract_dept_hint(raw)
    name = _clean_city(raw) or raw
    folded_name = re.sub(r"[-'’]+", " ", _fold(name)).strip()
    if folded_name in _FALLBACK_COMMUNES:
        base = dict(_FALLBACK_COMMUNES[folded_name])
        if not dept or str(base["department"]).upper() == dept.upper():
            base["km"] = radius
            base["label"] = f"{base['name']} ({base['department']})"
            return base

    if not network:
        return None

    params = urllib.parse.urlencode({"q": raw, "limit": 5, "type": "municipality"})
    try:
        status, payload = public_network.get_json(
            BAN_URL + "?" + params,
            headers={"User-Agent": "CareerCopilot/2.0 (geocodage de communes)"},
            timeout=10,
            max_bytes=1 * 1024 * 1024,
        )
        if status == 200 and isinstance(payload, dict):
            for feature in payload.get("features") or []:
                props = feature.get("properties") or {}
                geom = feature.get("geometry") or {}
                coords = geom.get("coordinates") or []
                if len(coords) < 2:
                    continue
                city_name = str(props.get("city") or props.get("name") or name).strip()
                citycode = str(props.get("citycode") or "").strip().upper()
                postcode = str(props.get("postcode") or "").strip()
                f_dept = _postcode_to_dept(postcode, citycode) or dept
                if dept and f_dept and f_dept.upper() != dept.upper():
                    continue
                return {
                    "name": city_name,
                    "department": f_dept or "00",
                    "insee": citycode or (postcode if len(postcode) == 5 else ""),
                    "lat": round(float(coords[1]), 4),
                    "lon": round(float(coords[0]), 4),
                    "km": radius,
                    "label": f"{city_name} ({f_dept})" if f_dept else city_name,
                }
    except Exception:
        pass
    return None


def _strip_arrondissement_and_cedex(folded: str) -> str:
    text = re.sub(r"\bcedex(?:\s+[a-z0-9]{1,3})?\b", " ", folded)
    text = re.sub(
        r"\b(paris|lyon|marseille)\s+\d{1,2}(?:e|er|ere|eme)?(?:\s+arrondissement)?\b",
        r"\1",
        text,
    )
    text = re.sub(
        r"\b\d{1,2}(?:e|er|ere|eme)?\s+arrondissement(?:\s+de\s+(paris|lyon|marseille))?\b",
        r" \1 ",
        text,
    )
    return text


def _normalize_city_tokens(value: str) -> tuple[list[str], list[str]]:
    folded = _fold(value)
    if not folded:
        return [], []
    folded = re.sub(r"['’\-_/.,;()]+", " ", folded)
    folded = _strip_arrondissement_and_cedex(folded)
    folded = re.sub(r"\b\d{5}\b", " ", folded)
    folded = re.sub(r"\bst\b", "saint", folded)
    folded = re.sub(r"\bste\b", "sainte", folded)
    tokens = [tok for tok in folded.split() if tok]
    if len(tokens) > 1 and tokens[-1].isdigit() and len(tokens[-1]) in (2, 3):
        tokens = tokens[:-1]
    if len(tokens) > 1 and tokens[0].isdigit() and len(tokens[0]) in (2, 3):
        tokens = tokens[1:]
    core = [tok for tok in tokens if tok not in _FRENCH_CITY_STOPWORDS]
    return tokens, core


def _same_name(candidate: str, wanted: str) -> bool:
    tokens_c, core_c = _normalize_city_tokens(candidate)
    tokens_w, core_w = _normalize_city_tokens(wanted)
    if not tokens_c or not tokens_w:
        return False
    if tokens_c == tokens_w:
        return True
    if core_c and core_w and core_c == core_w:
        return True
    return False


def _clean_city(city: str) -> str:
    text = re.sub(r"^\d{5}\s*[-–]?\s*", "", (city or "").strip())
    text = re.sub(r"^\d{2,3}\s*[-–]\s*", "", text)
    text = re.sub(r"\s*[-–]\s*\d{2,3}\s*$", "", text)  # « Massy - 91 »
    text = re.sub(r"\s*\(\d{2,3}\)\s*$", "", text)
    text = text.split(",")[0].strip()
    text = re.sub(r"\s+\d{5}$", "", text).strip()
    text = re.sub(r"(?i)\bcedex(?:\s+[a-z0-9]{1,3})?\b", "", text).strip(" -")
    folded = _fold(text)
    if re.match(r"^paris(?:\b|\s*\d)", folded):
        return "Paris"
    if re.match(r"^\d{1,2}(?:e|er|ere|eme)?\s+arrondissement\b", folded):
        return "Paris" if "paris" in folded else ""
    folded_key = re.sub(r"[-'’]+", " ", folded).strip()
    if folded_key in _CITY_ALIASES:
        return _CITY_ALIASES[folded_key]
    text = re.sub(r"(?i)\bst[- ]", "Saint-", text)
    text = re.sub(r"(?i)\bste[- ]", "Sainte-", text)
    return text.strip()


def _load_cache(*, refresh: bool = False) -> dict:
    global _cache, _cache_signature
    try:
        if CACHE_PATH.is_symlink():
            return {}
        info = CACHE_PATH.stat()
        signature = (
            CACHE_PATH,
            info.st_dev,
            info.st_ino,
            info.st_mtime_ns,
            info.st_size,
        )
    except OSError:
        if not refresh and _cache is not None and _cache_signature is None:
            return _cache
        _cache_signature = None
        return {}
    if not refresh and _cache is not None and signature == _cache_signature:
        return _cache
    try:
        loaded = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        _cache = loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        _cache = {}
    _cache_signature = signature
    return _cache


def _save_cache(key: str, entry: dict) -> None:
    global _cache, _cache_signature
    try:
        ensure_private_directory(CACHE_PATH.parent)
        fd = os.open(
            CACHE_PATH.with_suffix(".lock"),
            os.O_NOFOLLOW | os.O_CREAT | os.O_RDWR,
            0o600,
        )
        with os.fdopen(fd, "rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            cache = _load_cache(refresh=True)
            existing = cache.get(key)
            if (
                entry["lat"] is None
                and isinstance(existing, dict)
                and existing.get("lat") is not None
            ):
                return  # A concurrent successful lookup takes precedence.
            cache.pop(key, None)
            cache[key] = entry
            trimmed = dict(list(cache.items())[-_CACHE_SIZE:])
            write_private_text(
                CACHE_PATH,
                json.dumps(trimmed, ensure_ascii=False),
            )
            _cache = trimmed
            _cache_signature = None
            _load_cache(refresh=True)
    except (OSError, ValueError):
        return
