"""Client API La Bonne Alternance (v3 authentifié + fallback public v1)."""

from __future__ import annotations

import hashlib
import html
import http.client
import json
import logging
import math
import os
import re
import urllib.parse
from collections.abc import Iterable

import application_contact
import public_network

LOG = logging.getLogger("lba")

LBA_V3_SEARCH_URL = "https://api.apprentissage.beta.gouv.fr/api/job/v1/search"
LBA_PUBLIC_JOBS_URL = "https://labonnealternance.apprentissage.beta.gouv.fr/api/v1/jobs"
LBA_RADII: tuple[int, ...] = (10, 30, 60, 100)
MAX_ROMES_PER_CALL = 15
DEFAULT_TIMEOUT = 15
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_CALLER = "student-career-copilot"
DEFAULT_ROMES: tuple[str, ...] = ("M1802", "M1801", "M1805")

ROME_RE = re.compile(r"^[A-N]\d{4}$")
INSEE_RE = re.compile(r"^(?:\d{5}|2[AB]\d{3})$")
_FALSY = frozenset({"0", "false", "no", "non"})
_V1_BUCKETS = ("matchas", "peJobs", "partnerJobs")


def nearest_lba_radius(km: float) -> int:
    """Retourne le palier officiel LBA (10, 30, 60 ou 100 km) le plus proche."""
    if isinstance(km, bool):
        return 30
    try:
        value = float(km)
    except (TypeError, ValueError):
        return 30
    if math.isnan(value):
        return 30
    if value <= LBA_RADII[0]:
        return LBA_RADII[0]
    if value >= LBA_RADII[-1]:
        return LBA_RADII[-1]
    return min(LBA_RADII, key=lambda radius: (abs(radius - value), radius))


def enabled(
    env: dict[str, str],
    contracts: tuple[str, ...] | list[str] | None = None,
) -> bool:
    """Indique si la collecte La Bonne Alternance est active pour cette exécution.

    Conformément à l'Art. 5.2 des CGU LBA (usages non lucratifs uniquement),
    cette source est automatiquement désactivée lorsque `COMMERCIAL_SAFE=1`
    ou `CAREER_EDITION=commercial`.
    """
    cfg = env or {}
    comm_safe = str(
        cfg.get("COMMERCIAL_SAFE") or os.getenv("COMMERCIAL_SAFE", "0")
    ).strip().lower()
    edition = str(
        cfg.get("CAREER_EDITION") or os.getenv("CAREER_EDITION", "")
    ).strip().lower()
    if comm_safe in {"1", "true", "yes", "on", "oui"} or edition == "commercial":
        return False
    if str(cfg.get("LBA_ENABLED", "1")).strip().lower() in _FALSY:
        return False
    if contracts is not None:
        return any(
            str(contract or "").strip().lower() == "alternance"
            for contract in contracts
        )
    enable_alt = str(cfg.get("ENABLE_ALTERNANCE", "0")).strip().lower()
    if enable_alt and enable_alt not in _FALSY:
        return True
    return bool(str(cfg.get("LBA_API_KEY", "")).strip())


def validate_romes(romes: list[str] | tuple[str, ...] | None) -> list[str]:
    """Filtre et déduplique les codes ROME au format officiel `^[A-N]\\d{4}$`."""
    if romes is None:
        raw_items: Iterable[object] = DEFAULT_ROMES
    elif isinstance(romes, str):
        raw_items = romes.split(",")
    else:
        raw_items = romes

    valid: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        code = str(item or "").strip().upper()
        if not code or not ROME_RE.fullmatch(code):
            continue
        if code not in seen:
            seen.add(code)
            valid.append(code)
    return valid


def _parse_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _valid_coords(lat: object, lon: object) -> tuple[float, float] | None:
    parsed_lat = _parse_float(lat)
    parsed_lon = _parse_float(lon)
    if parsed_lat is None or parsed_lon is None:
        return None
    if not (-90.0 <= parsed_lat <= 90.0 and -180.0 <= parsed_lon <= 180.0):
        return None
    return parsed_lat, parsed_lon


def _validate_insee(raw: object) -> str:
    code = str(raw or "").strip().upper()
    if not code:
        return ""
    if INSEE_RE.fullmatch(code):
        return code
    LOG.warning("LBA : code INSEE invalide ignoré")
    return ""


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _strip_html(raw: str, limit: int = 8000) -> str:
    if not raw:
        return ""
    text = re.sub(r"(?i)<(?:br\s*/?|/p|/li|/div|/h[1-6])>", "\n", raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.splitlines()]
    cleaned = "\n".join(ln for ln in lines if ln)
    return cleaned[:limit]


def _safe_https_url(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    candidate = raw.strip()
    if not candidate:
        return ""
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme.lower() != "https":
        return ""
    try:
        public_network.target(candidate)
    except public_network.NetworkPolicyError:
        return ""
    return candidate


def _stable_id(*parts: str) -> str:
    raw = "|".join(str(p or "").strip() for p in parts).encode("utf-8")
    return f"lba-{hashlib.sha1(raw).hexdigest()[:14]}"


def _redact_secret(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _first_non_empty(*values: object) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _extract_coords(item: dict) -> tuple[float | None, float | None]:
    workplace = _as_dict(item.get("workplace"))
    wp_loc = _as_dict(workplace.get("location"))
    geopoint = _as_dict(wp_loc.get("geopoint"))
    geo_coords = geopoint.get("coordinates")
    if isinstance(geo_coords, (list, tuple)) and len(geo_coords) >= 2:
        # GeoJSON [longitude, latitude]
        valid = _valid_coords(geo_coords[1], geo_coords[0])
        if valid is not None:
            return valid

    place = _as_dict(item.get("place"))
    location = _as_dict(item.get("location"))
    company_place = _as_dict(_as_dict(item.get("company")).get("place"))

    candidates = (
        (geopoint.get("latitude"), geopoint.get("longitude")),
        (geopoint.get("lat"), geopoint.get("lon")),
        (wp_loc.get("latitude"), wp_loc.get("longitude")),
        (wp_loc.get("lat"), wp_loc.get("lon")),
        (place.get("latitude"), place.get("longitude")),
        (place.get("lat"), place.get("lon")),
        (location.get("latitude"), location.get("longitude")),
        (location.get("lat"), location.get("lon")),
        (company_place.get("latitude"), company_place.get("longitude")),
        (item.get("latitude"), item.get("longitude")),
        (item.get("lat"), item.get("lon")),
    )
    for lat, lon in candidates:
        valid = _valid_coords(lat, lon)
        if valid is not None:
            return valid
    return None, None


def _extract_url(item: dict) -> str:
    apply_block = _as_dict(item.get("apply"))
    job_block = _as_dict(item.get("job"))
    contact_block = _as_dict(item.get("contact"))
    offer_block = _as_dict(item.get("offer"))

    candidates = (
        apply_block.get("url"),
        item.get("url"),
        item.get("apply_url"),
        item.get("applyUrl"),
        job_block.get("url"),
        contact_block.get("url"),
        offer_block.get("url"),
        item.get("redirect_url"),
    )
    for candidate in candidates:
        safe = _safe_https_url(candidate)
        if safe:
            return safe
    return ""


def _extract_raw_id(item: dict) -> str:
    identifier = _as_dict(item.get("identifier"))
    job_block = _as_dict(item.get("job"))
    offer_block = _as_dict(item.get("offer"))
    for candidate in (
        identifier.get("id"),
        identifier.get("partner_job_id"),
        item.get("id"),
        job_block.get("id"),
        offer_block.get("id"),
    ):
        if candidate is not None and not isinstance(candidate, (dict, list, bool)):
            text = str(candidate).strip()
            if text:
                return text
    return ""


def _extract_company_and_city(item: dict) -> tuple[str, str]:
    workplace = _as_dict(item.get("workplace"))
    wp_loc = _as_dict(workplace.get("location"))
    place = _as_dict(item.get("place"))
    location_raw = item.get("location")
    location = _as_dict(location_raw)
    company_raw = item.get("company")
    company_dict = _as_dict(company_raw)
    company_place = _as_dict(company_dict.get("place"))
    entreprise_block = _as_dict(item.get("entreprise"))

    company = (
        _first_non_empty(
            workplace.get("name"),
            workplace.get("brand"),
            workplace.get("legal_name"),
            workplace.get("enseigne"),
            company_raw if isinstance(company_raw, str) else "",
            company_dict.get("name"),
            company_dict.get("enseigne"),
            company_dict.get("raisonSociale"),
            item.get("name"),
            item.get("company_name"),
            item.get("companyName"),
            entreprise_block.get("nom"),
        )
        or "Entreprise"
    )
    city = _first_non_empty(
        wp_loc.get("city"),
        wp_loc.get("commune"),
        wp_loc.get("label"),
        place.get("city"),
        place.get("libelle"),
        location.get("city"),
        location.get("commune"),
        location.get("display_name"),
        location.get("label"),
        location_raw if isinstance(location_raw, str) else "",
        company_place.get("city"),
        item.get("city"),
        wp_loc.get("address"),
        place.get("fullAddress"),
        location.get("address"),
    )
    return company, city


def _extract_contact(item: dict, description: str) -> tuple[str, str]:
    apply_block = _as_dict(item.get("apply"))
    contact_block = _as_dict(item.get("contact"))

    direct_email = _first_non_empty(
        apply_block.get("email"),
        contact_block.get("email"),
        contact_block.get("courriel"),
        item.get("email"),
    )
    contact_text = " ".join(
        part
        for part in (
            _clean_text(contact_block.get("info")),
            _clean_text(apply_block.get("info")),
        )
        if part
    )
    email = application_contact.recipient(
        description,
        contact_email=direct_email,
        contact_text=contact_text,
    )
    phone = _first_non_empty(
        apply_block.get("phone"),
        contact_block.get("phone"),
        item.get("phone"),
    )
    return email, phone


def _normalize_item(item: dict) -> tuple[dict | None, str, str]:
    offer_block = _as_dict(item.get("offer"))
    job_block = _as_dict(item.get("job"))

    title = _first_non_empty(
        offer_block.get("title"),
        item.get("title"),
        job_block.get("title"),
        item.get("intitule"),
    )
    if not title:
        return None, "", ""

    company, city = _extract_company_and_city(item)
    raw_description = _first_non_empty(
        offer_block.get("description"),
        job_block.get("description"),
        item.get("description"),
        job_block.get("employeurDescription"),
        _as_dict(job_block.get("romeDetails")).get("definition"),
    )
    description = _strip_html(raw_description)
    email, phone = _extract_contact(item, description)
    url = _extract_url(item)
    lat, lon = _extract_coords(item)
    raw_id = _extract_raw_id(item)
    offer_id = raw_id or _stable_id(url, title, company, city)
    text = " ".join(part for part in (title, company, city, description) if part)

    normalized = {
        "id": offer_id,
        "title": title,
        "company": company,
        "name": company,
        "city": city,
        "email": email,
        "phone": phone,
        "url": url,
        "description": description,
        "text": text,
        "source": "lba",
        "campaign": "alternance",
        "contract": "alternance",
        "contract_type": "alternance",
        "alternance": True,
        "lat": lat,
        "lon": lon,
        "latitude": lat,
        "longitude": lon,
    }
    return normalized, raw_id, url


def _extract_raw_rows(payload: object) -> list[dict]:
    rows: list[dict] = []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return rows

    jobs = payload.get("jobs")
    if isinstance(jobs, list):
        rows.extend(row for row in jobs if isinstance(row, dict))
    elif isinstance(jobs, dict) and isinstance(jobs.get("results"), list):
        rows.extend(row for row in jobs["results"] if isinstance(row, dict))

    results = payload.get("results")
    if isinstance(results, list):
        rows.extend(row for row in results if isinstance(row, dict))

    for bucket in _V1_BUCKETS:
        section = payload.get(bucket)
        if isinstance(section, dict) and isinstance(section.get("results"), list):
            rows.extend(row for row in section["results"] if isinstance(row, dict))
        elif isinstance(section, list):
            rows.extend(row for row in section if isinstance(row, dict))
    return rows


def _append_unique_offers(
    payload: object,
    found: list[dict],
    seen_urls: set[str],
    seen_ids: set[str],
) -> None:
    for row in _extract_raw_rows(payload):
        offer, raw_id, offer_url = _normalize_item(row)
        if offer is None:
            continue
        url_key = offer_url.lower() if offer_url else ""
        id_key = (raw_id or offer["id"]).lower()
        if (url_key and url_key in seen_urls) or (id_key and id_key in seen_ids):
            continue
        if url_key:
            seen_urls.add(url_key)
        if id_key:
            seen_ids.add(id_key)
        found.append(offer)


def parse_offers(payload: object) -> list[dict]:
    """Normalise et déduplique les offres issues d'une réponse LBA v3 ou v1."""
    found: list[dict] = []
    _append_unique_offers(payload, found, set(), set())
    return found


def _fetch_batch(
    url: str,
    headers: dict[str, str],
    *,
    mode: str,
    secret: str,
) -> tuple[bool, object | None]:
    try:
        status, raw_bytes = public_network.fetch(
            url,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
            max_bytes=MAX_RESPONSE_BYTES,
        )
    except public_network.NetworkPolicyError as exc:
        LOG.warning(
            "LBA (%s) bloqué par la politique réseau : %s",
            mode,
            _redact_secret(str(exc), secret),
        )
        return False, None
    except (http.client.HTTPException, OSError, ValueError) as exc:
        LOG.warning("LBA (%s) erreur réseau (%s)", mode, type(exc).__name__)
        return False, None

    if status >= 400:
        LOG.warning("LBA (%s) indisponible : HTTP %s", mode, status)
        return False, None

    if not raw_bytes or not raw_bytes.strip():
        return True, {}

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        LOG.warning("LBA (%s) réponse JSON invalide", mode)
        return False, None

    if not isinstance(payload, (dict, list)):
        LOG.warning("LBA (%s) format de réponse inattendu", mode)
        return False, None

    return True, payload


def search(
    env: dict[str, str],
    zone: dict,
    romes: list[str] | tuple[str, ...] | None = None,
) -> list[dict]:
    """Recherche des offres d'alternance via La Bonne Alternance (v3 avec clé ou v1 public)."""
    cfg = env or {}
    if not isinstance(zone, dict):
        LOG.warning("LBA : zone invalide")
        return []

    raw_lat = zone.get("lat") if zone.get("lat") is not None else zone.get("latitude")
    raw_lon = zone.get("lon") if zone.get("lon") is not None else zone.get("longitude")
    coords = _valid_coords(raw_lat, raw_lon)
    if coords is None:
        LOG.warning("LBA : coordonnées de zone invalides")
        return []
    lat, lon = coords

    raw_km = zone.get("km") if zone.get("km") is not None else zone.get("radius", 30)
    radius = nearest_lba_radius(raw_km)
    insee = _validate_insee(zone.get("insee"))

    valid_romes = validate_romes(romes)
    if not valid_romes:
        LOG.warning("LBA : aucun code ROME valide")
        return []

    api_key = str(cfg.get("LBA_API_KEY", "")).strip()
    if "\r" in api_key or "\n" in api_key:
        LOG.warning("LBA : clé API invalide")
        return []

    caller = str(cfg.get("LBA_CALLER", "")).strip() or DEFAULT_CALLER
    use_v3 = bool(api_key)
    mode = "v3" if use_v3 else "v1"

    found: list[dict] = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()

    for start in range(0, len(valid_romes), MAX_ROMES_PER_CALL):
        batch = valid_romes[start : start + MAX_ROMES_PER_CALL]
        if use_v3:
            params: dict[str, object] = {
                "latitude": lat,
                "longitude": lon,
                "radius": radius,
                "romes": ",".join(batch),
            }
            url = f"{LBA_V3_SEARCH_URL}?{urllib.parse.urlencode(params)}"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            }
        else:
            params = {
                "caller": caller,
                "romes": ",".join(batch),
                "latitude": lat,
                "longitude": lon,
                "radius": radius,
            }
            if insee:
                params["insee"] = insee
            url = f"{LBA_PUBLIC_JOBS_URL}?{urllib.parse.urlencode(params)}"
            headers = {"Accept": "application/json"}

        ok, payload = _fetch_batch(url, headers, mode=mode, secret=api_key)
        if not ok:
            return found

        _append_unique_offers(payload, found, seen_urls, seen_ids)

    return found
