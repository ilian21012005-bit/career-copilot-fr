"""Helpers partagés pour les sources publiques read-only (ATS, open data, flux RSS)."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Callable

from config import ZONES
from filters import _fold, _km

UA = "Mozilla/5.0 (compatible; CareerScout/1.0)"
_RATE_LIMIT_STATUSES = {429, 503}


def is_rate_limited(status: int) -> bool:
    return status in _RATE_LIMIT_STATUSES


def strip_html(raw: str, limit: int = 8000) -> str:
    """Nettoie une description HTML externe (donnée non fiable)."""
    if not raw:
        return ""
    text = re.sub(r"(?i)<(?:br\s*/?|/p|/li|/div|/h[1-6])>", "\n", raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.splitlines()]
    cleaned = "\n".join(ln for ln in lines if ln)
    return cleaned[:limit]


def extract_department(location_text: str) -> str:
    """Extrait un département français (2 chiffres, 2A/2B ou 971-976) si présent dans le libellé."""
    raw = str(location_text or "")
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


_LOCATION_NOISE_RE = re.compile(
    r"(?i)\b(?:france|ile-de-france|î?le-de-france|nouvelle-aquitaine|region parisienne|"
    r"région parisienne|grand paris|area|emea|europe|remote|full remote|hybrid|hybride|"
    r"t[eé]l[eé]travail|on-?site|pr[eé]sentiel|multiple locations|\d+\s+locations?)\b"
)

_AMBIGUOUS_LOCATION_TOKENS = frozenset(
    {
        "france",
        "ile de france",
        "region parisienne",
        "grand paris",
        "remote",
        "teletravail",
        "hybride",
        "hybrid",
        "multiple locations",
        "toute la france",
        "national",
        "emea",
        "europe",
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

_KNOWN_FR_CITIES_RE = re.compile(
    r"\b(Paris(?:\s+\d{1,2}(?:e|er|ère|eme|ème)?)?|Saclay|Orsay|Massy|Palaiseau|"
    r"Villebon(?:-sur-Yvette)?|V[eé]lizy(?:-Villacoublay)?|Les\s+Ulis|Bures-sur-Yvette|"
    r"Gif-sur-Yvette|Courtab[oeœ]uf|S[eè]vres|Issy-les-Moulineaux|Boulogne-Billancourt|"
    r"La\s+D[eé]fense|Courbevoie|Puteaux|Nanterre|Levallois-Perret|Mantes-la-Jolie|"
    r"Versailles|Saint-Quentin-en-Yvelines|St-Quentin-en-Yvelines|Guyancourt|"
    r"Montigny-le-Bretonneux|[EÉ]lancourt|[EÉ]vry(?:-Courcouronnes)?|Antony|Montrouge|"
    r"Bagneux|Clamart|Meudon|Pessac|Bordeaux|M[eé]rignac|Talence|"
    r"Lyon(?:\s+\d{1,2}(?:e|er|ème|eme)?)?|Villeurbanne|Toulouse|Blagnac|Lab[eè]ge|"
    r"Lille|Villeneuve-d['’]Ascq|Roubaix|Tourcoing|Nantes|Saint-Herblain|"
    r"Rennes|Cesson-S[eé]vign[eé]|Montpellier|Castelnau-le-Lez|Strasbourg|Illkirch(?:-Graffenstaden)?|"
    r"Grenoble|Meylan|[EÉ]chirolles|Marseille(?:\s+\d{1,2}(?:e|er|ème|eme)?)?|Aix-en-Provence|"
    r"Nice|Sophia[- ]Antipolis|Antibes|Nancy|Vand[oeœ]uvre-l[eè]s-Nancy)\b",
    re.I,
)


def _clean_single_city_chunk(chunk: str) -> str:
    text = str(chunk or "").strip()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = _LOCATION_NOISE_RE.sub(" ", text)
    text = re.sub(r"\b\d{5}\b", " ", text)
    text = re.sub(r"^\s*\d{2,3}\s*[-–]\s*", "", text)
    text = re.sub(r"\s*[-–]\s*\d{2,3}\s*$", "", text)
    text = re.sub(r"(?i)\bcedex(?:\s+[a-z0-9]{1,3})?\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -–_,.")
    if not text:
        return ""
    folded = _fold(text)
    if folded in _AMBIGUOUS_LOCATION_TOKENS:
        return ""
    if re.match(
        r"^paris(?:\s+\d{1,2}(?:e|er|ere|eme)?)?(?:\s+arrondissement)?$", folded
    ):
        return "Paris"
    if re.match(
        r"^\d{1,2}(?:e|er|ere|eme)?\s+arrondissement(?:\s+de\s+paris)?$", folded
    ):
        return "Paris" if "paris" in folded else ""
    folded_key = re.sub(r"[-'’]+", " ", folded).strip()
    if folded_key in _CITY_ALIASES:
        return _CITY_ALIASES[folded_key]
    text = re.sub(r"(?i)\bst[- ]", "Saint-", text)
    text = re.sub(r"(?i)\bste[- ]", "Sainte-", text)
    return re.sub(r"\s+", " ", text).strip(" -")


def city_candidates(raw: str) -> list[str]:
    """Extrait les noms de communes exploitables d'un champ lieu potentiellement composite."""
    text = str(raw or "").strip()
    if not text:
        return []
    parts = re.split(r"(?:[:,;|/]|\s+[-–]\s+|\s+ou\s+|\s+or\s+)", text, flags=re.I)
    candidates: list[str] = []
    seen: set[str] = set()
    for part in parts:
        cleaned = _clean_single_city_chunk(part)
        if not cleaned:
            continue
        key = _fold(cleaned)
        if key and key not in seen:
            seen.add(key)
            candidates.append(cleaned)
    return candidates


def clean_city_name(raw: str) -> str:
    """Normalise une chaîne de lieu Workday/CSP/ATS avant géocodage BAN."""
    candidates = city_candidates(raw)
    return candidates[0] if candidates else ""


def is_ambiguous_location(raw: str) -> bool:
    """Vrai si le libellé est uniquement régional/pays/remote sans commune identifiable."""
    text = str(raw or "").strip()
    if not text:
        return True
    if city_candidates(text):
        return False
    folded = re.sub(r"[-'’.,;/()]+", " ", _fold(text)).strip()
    folded = re.sub(r"\s+", " ", folded)
    return bool(folded)


def infer_fr_city(title: str, body: str) -> tuple[str, str]:
    """Extrait une commune française connue depuis le titre ou le début de la description."""
    for source_text in (title or "", (body or "")[:1500]):
        match = _KNOWN_FR_CITIES_RE.search(source_text)
        if match:
            city = match.group(1)
            return city, extract_department(source_text) or extract_department(city)
    return "", ""


def resolve_coordinates(
    city: str,
    department: str = "",
    *,
    geocoder: Callable[[str, str], tuple[float, float] | None] | None = None,
    cache: dict[tuple[str, str], tuple[float | None, float | None]] | None = None,
) -> tuple[float | None, float | None]:
    """Géocode une commune française via BAN (avec cache par exécution)."""
    cleaned = clean_city_name(city)
    if not cleaned:
        return None, None
    dept = department or extract_department(city)
    key = (_fold(cleaned), dept)
    if cache is not None and key in cache:
        return cache[key]

    coords: tuple[float | None, float | None] = (None, None)
    try:
        if geocoder is None:
            from hellowork.geo import geocode as hw_geocode

            point = hw_geocode(cleaned, dept)
        else:
            point = geocoder(cleaned, dept)
        if point and point[0] is not None and point[1] is not None:
            coords = (float(point[0]), float(point[1]))
    except Exception:
        coords = (None, None)

    if cache is not None:
        cache[key] = coords
    return coords


def resolve_zone_coordinates(
    city: str,
    department: str = "",
    *,
    campaign: str = "stage",
    geocoder: Callable[[str, str], tuple[float, float] | None] | None = None,
    cache: dict[tuple[str, str], tuple[float | None, float | None]] | None = None,
) -> tuple[float | None, float | None]:
    """Résout un lieu multi-villes ou composite en privilégiant le premier site en zone."""
    candidates = city_candidates(city)
    if not candidates:
        return None, None
    fallback: tuple[float | None, float | None] = (None, None)
    for candidate in candidates:
        dept = (
            department
            or extract_department(candidate)
            or (extract_department(city) if len(candidates) == 1 else "")
        )
        lat, lon = resolve_coordinates(candidate, dept, geocoder=geocoder, cache=cache)
        if lat is not None and lon is not None:
            if within_any_zone(lat, lon, campaign):
                return lat, lon
            if fallback == (None, None):
                fallback = (lat, lon)
    return fallback


def within_any_zone(lat: float | None, lon: float | None, campaign: str) -> bool:
    """Vrai si le point est dans le rayon d'au moins un bassin de la campagne."""
    if lat is None or lon is None:
        return False
    zones = ZONES.get(campaign, [])
    return any(_km(zone["lat"], zone["lon"], lat, lon) <= zone["km"] for zone in zones)


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(p or "").strip() for p in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha1(raw).hexdigest()[:14]}"


def parse_company_slugs(
    raw_value: str,
    defaults: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """Parse une liste CSV `slug` ou `slug=Nom` depuis une variable d'environnement."""
    text = (raw_value or "").strip()
    if not text:
        return defaults
    parsed: list[tuple[str, str]] = []
    for token in text.split(","):
        item = token.strip()
        if not item:
            continue
        if "=" in item:
            slug, label = item.split("=", 1)
            slug = slug.strip().lower()
            label = label.strip() or slug.replace("-", " ").title()
        else:
            slug = item.lower()
            label = item.replace("-", " ").title()
        if re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
            parsed.append((slug, label))
    return tuple(parsed) or defaults


def stage_candidate_ok(title: str, body: str, source: str) -> bool:
    """Filtre déterministe pré-géocodage pour les stages et alternances selon le profil actif."""
    import candidate_config
    import filters

    blob = f"{title} {body}".strip()
    if not blob:
        return False
    folded_title = _fold(title)
    try:
        contracts = candidate_config.get_profile().contracts
    except Exception:
        contracts = ("stage", "job")
    is_alt = "alternance" in folded_title or "apprentissage" in folded_title
    if is_alt and "alternance" not in contracts:
        return False
    if filters.excluded(blob) or filters.too_senior(title):
        return False
    return filters.stage_relevant(blob, source)


def build_offer(
    *,
    offer_id: str,
    url: str,
    title: str,
    company: str,
    city: str,
    latitude: float | None,
    longitude: float | None,
    description: str,
    source: str,
    contract_type: str = "",
    notes: str = "",
) -> dict:
    """Construit une offre normalisée au schéma commun de main.py."""
    compact_text = " ".join(
        part for part in (title, company, city, description) if part
    )
    folded_contract = _fold(f"{contract_type} {title}")
    is_alt = any(
        tok in folded_contract
        for tok in ("alternance", "apprentissage", "contrat pro", "professionnalisation")
    )
    return {
        "id": offer_id,
        "url": url,
        "email": "",  # Traitement manuel sur portail ATS/public : jamais d'envoi auto
        "title": title.strip(),
        "name": company.strip() or "Entreprise",
        "city": city.strip(),
        "latitude": latitude,
        "longitude": longitude,
        "text": compact_text,
        "description": description.strip(),
        "source": source,
        "contract_type": "alternance" if is_alt and not contract_type else contract_type,
        "notes": notes.strip(),
        "alternance": is_alt,
    }


def _best_matching_zone(raw: dict, campaign: str = "stage") -> dict | None:
    lat = raw.get("latitude")
    lon = raw.get("longitude")
    if lat is None or lon is None:
        return None
    best = None
    best_dist = float("inf")
    zone_key = "stage" if campaign in ("stage", "alternance") else "job"
    zones = ZONES.get(campaign) or ZONES.get(zone_key, [])
    for zone in zones:
        dist = _km(zone["lat"], zone["lon"], lat, lon)
        if dist <= zone["km"] and dist < best_dist:
            best = zone
            best_dist = dist
    return best


def _resolve_offer_contract_label(raw: dict, campaign: str) -> str:
    ct = _fold(str(raw.get("contract_type") or raw.get("contract") or ""))
    title_f = _fold(str(raw.get("title") or ""))
    if (
        campaign == "alternance"
        or raw.get("alternance") is True
        or any(
            k in ct or k in title_f
            for k in ("alternance", "apprentissage", "contrat pro", "professionnalisation")
        )
    ):
        return "Alternance"
    if campaign == "job" or ct in ("job_etudiant", "job", "student_job"):
        return "job_etudiant"
    return "Stage"


def _ingest_offers_to_store(raw_offers: list[dict], *, campaign: str) -> int:
    """Enregistre les offres publiques éligibles (stage, alternance, job) dans le store unifié."""
    import filters
    from hellowork import geo, offer as hw_offers, partner_deep, score as scoring, store

    if not raw_offers:
        return 0
    store.init()
    added = 0
    for raw in raw_offers:
        eff_campaign = (
            "alternance"
            if (raw.get("alternance") is True or raw.get("campaign") == "alternance")
            else (str(raw.get("campaign") or campaign))
        )
        zone = _best_matching_zone(raw, eff_campaign)
        if zone is None and raw.get("origin_lat") is not None and raw.get("origin_lon") is not None:
            zone = {"lat": raw["origin_lat"], "lon": raw["origin_lon"], "km": 30}
        if zone is None:
            continue
        candidate = dict(raw)
        candidate["origin_lat"] = zone["lat"]
        candidate["origin_lon"] = zone["lon"]
        filter_kind = "stage" if eff_campaign in ("stage", "alternance") else "job"
        if not filters.keep(candidate, filter_kind):
            continue
        oid = str(raw.get("id") or "")
        if not oid:
            continue
        existing = store.get(oid)
        if existing and existing["status"] not in ("new", "shortlist", "prepared"):
            continue
        offer = hw_offers.Offer(
            id=oid,
            url=str(raw.get("url") or ""),
            title=str(raw.get("title") or ""),
            company=str(raw.get("name") or raw.get("company") or ""),
            city=str(raw.get("city") or ""),
            department=extract_department(str(raw.get("city") or "")),
            contract=_resolve_offer_contract_label(raw, eff_campaign),
            description=str(raw.get("description") or raw.get("text") or ""),
            apply_mode="manual",
            latitude=raw.get("latitude"),
            longitude=raw.get("longitude"),
        )
        geo.resolve(offer)
        if offer.location_status != "in_zone":
            continue
        result = scoring.evaluate(offer)
        if result.rejected:
            continue
        store.save_offer(offer, result)
        capability = (
            str(raw.get("apply_capability") or "").strip()
            or partner_deep.apply_capability_for("unknown", offer.url)
        )
        if capability:
            if hasattr(store, "set_apply_capability"):
                store.set_apply_capability(offer.id, capability, only_if_empty=True)
            else:
                with store._db() as conn:  # type: ignore[attr-defined]
                    conn.execute(
                        """
                        UPDATE offers
                           SET apply_capability = ?
                         WHERE id = ?
                           AND (apply_capability IS NULL OR apply_capability = '')
                        """,
                        (capability, offer.id),
                    )
        if existing is None:
            added += 1
    return added


def ingest_stage_offers_to_store(raw_offers: list[dict]) -> int:
    """Enregistre les offres de stage/alternance éligibles dans le store unifié."""
    return _ingest_offers_to_store(raw_offers, campaign="stage")


def ingest_alternance_offers_to_store(raw_offers: list[dict]) -> int:
    """Enregistre les offres d'alternance éligibles dans le store unifié."""
    return _ingest_offers_to_store(raw_offers, campaign="alternance")


def ingest_job_offers_to_store(raw_offers: list[dict]) -> int:
    """Enregistre les jobs étudiants éligibles (manuels) dans le store HelloWork."""
    return _ingest_offers_to_store(raw_offers, campaign="job")
