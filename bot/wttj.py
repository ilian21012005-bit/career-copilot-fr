"""Scraper d'annonces Welcome to the Jungle (WTTJ) via l'API Algolia publique."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from filters import _fold
import public_network

logger = logging.getLogger(__name__)

ALGOLIA_INDEX = "wttj_jobs_production_fr"

STAGE_QUERIES = (
    "administration systèmes et réseaux",
    "infrastructure informatique",
    "support informatique",
    "cloud DevOps",
    "qualité et tests",
    "bases de données",
    "gouvernance cybersécurité",
    "cybersécurité",
    "sécurité réseau",
    "SOC",
    "pentest",
    "analyste sécurité",
)


def enabled(env: dict[str, str] | None = None) -> bool:
    """WTTJ n'est actif qu'en mode non-commercial si les identifiants Algolia sont fournis."""
    if env is None:
        try:
            from config import load_env

            values = load_env()
        except Exception:
            values = os.environ
    else:
        values = env
    comm = str(values.get("COMMERCIAL_SAFE") or os.getenv("COMMERCIAL_SAFE", "0")).strip().lower()
    edition = str(values.get("CAREER_EDITION") or os.getenv("CAREER_EDITION", "")).strip().lower()
    if comm in {"1", "true", "yes", "on", "oui"} or edition == "commercial":
        return False
    return bool(values.get("WTTJ_ALGOLIA_APP_ID", "").strip() and values.get("WTTJ_ALGOLIA_API_KEY", "").strip())


def normalize(hit: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise un hit Algolia WTTJ au format standard de l'application."""
    raw_title = (hit.get("name") or "").strip()
    if not raw_title:
        return None

    # Harmoniser le titre avec le préfixe Stage si manquant
    title = raw_title if "stage" in _fold(raw_title) else f"Stage - {raw_title}"

    org = hit.get("organization") or {}
    company = (org.get("name") or "Entreprise").strip()
    org_slug = org.get("slug") or ""
    slug = hit.get("slug") or ""
    ref = hit.get("reference") or hit.get("objectID") or slug

    if org_slug and slug:
        url = f"https://www.welcometothejungle.com/fr/companies/{org_slug}/jobs/{slug}"
    else:
        url = f"https://www.welcometothejungle.com/fr/jobs/{slug}" if slug else ""

    offices = hit.get("offices") or []
    city = ""
    if offices:
        first_office = offices[0]
        city = (
            first_office.get("local_city")
            or first_office.get("city")
            or first_office.get("district")
            or ""
        )
    if not city:
        city = "Île-de-France"

    # Coordonnées géographiques
    geoloc = hit.get("_geoloc") or []
    lat = None
    lon = None
    if geoloc and isinstance(geoloc, list) and len(geoloc) > 0:
        lat = geoloc[0].get("lat")
        lon = geoloc[0].get("lng")

    summary = (hit.get("summary") or "").strip()
    key_missions = hit.get("key_missions") or []
    desc_parts = []
    if summary:
        desc_parts.append(summary)
    if key_missions:
        desc_parts.append("\nMissions clés :")
        desc_parts.extend(f"- {m}" for m in key_missions if m)
    description = "\n".join(desc_parts)

    full_text = f"{title} {summary} {' '.join(key_missions)} {city}"
    published_at = hit.get("published_at") or hit.get("published_at_date") or ""

    return {
        "id": f"wttj_{ref}",
        "url": url,
        "email": "",
        "title": title,
        "name": company,
        "city": city,
        "latitude": float(lat) if lat is not None else None,
        "longitude": float(lon) if lon is not None else None,
        "text": full_text,
        "description": description,
        "source": "wttj",
        "contract_type": "stage",
        "campaign": "stage",
        "published_at": published_at,
        "notes": f"WTTJ - {city} (Réf: {ref})",
    }


def search_query(query: str, zone: dict[str, Any], limit: int = 25) -> list[dict[str, Any]]:
    """Recherche sur WTTJ Algolia pour une requête et une zone géographique données."""
    try:
        from config import load_env

        env = load_env()
    except Exception:
        env = os.environ
    app_id = env.get("WTTJ_ALGOLIA_APP_ID", "").strip()
    api_key = env.get("WTTJ_ALGOLIA_API_KEY", "").strip()
    if not app_id or not api_key:
        logger.info("Recherche WTTJ ignorée : identifiants Algolia absents")
        return []
    lat = zone.get("lat")
    lon = zone.get("lon")
    radius_m = int(zone.get("km", 35)) * 1000

    payload: dict[str, Any] = {
        "query": query,
        "facetFilters": [["contract_type:internship"]],
        "hitsPerPage": limit,
    }
    if lat is not None and lon is not None:
        payload["aroundLatLng"] = f"{lat}, {lon}"
        payload["aroundRadius"] = radius_m

    headers = {
        "x-algolia-api-key": api_key,
        "x-algolia-application-id": app_id,
        "Referer": "https://www.welcometothejungle.com/",
        "Content-Type": "application/json",
        "User-Agent": "Job-Etudiant/1.0",
    }

    try:
        status, data = public_network.post_json(
            f"https://{app_id}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query",
            payload,
            headers=headers,
            timeout=12,
            max_bytes=4 * 1024 * 1024,
        )
        if status >= 400 or not isinstance(data, dict):
            raise RuntimeError(f"HTTP {status}")
    except Exception as exc:
        logger.warning("Erreur API WTTJ (%s)", type(exc).__name__)
        return []

    hits = data.get("hits") or []
    results = []
    for hit in hits:
        normalized = normalize(hit)
        if normalized:
            results.append(normalized)
    return results


def search(zone: dict[str, Any], queries: list[str] | tuple[str, ...] = STAGE_QUERIES) -> list[dict[str, Any]]:
    """Exécute les recherches WTTJ pour l'ensemble des mots-clés sur la zone."""
    seen_ids: set[str] = set()
    all_offers: list[dict[str, Any]] = []

    for q in queries:
        offers = search_query(q, zone)
        for offer in offers:
            oid = offer.get("id") or offer.get("url")
            if oid and oid not in seen_ids:
                seen_ids.add(oid)
                all_offers.append(offer)
        time.sleep(0.05)

    return all_offers
