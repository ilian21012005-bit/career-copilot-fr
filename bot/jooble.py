"""Annonces Jooble France. Ignoré sans JOOBLE_API_KEY.

Clé gratuite : https://fr.jooble.org/api/about
Le rayon Jooble est arrondi au palier supérieur, puis recoupé aux coordonnées.
"""

from __future__ import annotations

import re
import application_contact
import public_network

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
SKIP_EMAIL = ("noreply", "no-reply", "donotreply", "exemple.com")
_GEOCODE: dict[str, tuple[float, float] | None] = {}
_RADIUS_STEPS = (0, 4, 8, 16, 26, 40, 80)


def enabled(env: dict[str, str]) -> bool:
    return bool(env.get("JOOBLE_API_KEY"))


def search(env: dict[str, str], what: str, where: str, distance_km: int) -> list[dict]:
    status, payload = public_network.post_json(
        f"https://fr.jooble.org/api/{env['JOOBLE_API_KEY']}",
        {
            "keywords": what,
            "location": where,
            "radius": _radius(distance_km),
            "page": "1",
            "ResultOnPage": "20",
            "companysearch": "false",
        },
        timeout=30,
        max_bytes=4 * 1024 * 1024,
    )
    if status >= 400 or not isinstance(payload, dict):
        raise RuntimeError(f"Jooble HTTP {status}")
    found = []
    for row in payload.get("jobs") or []:
        title = row.get("title") or what
        company = row.get("company") or "Entreprise"
        location = row.get("location") or where
        snippet = row.get("snippet") or ""
        link = row.get("link") or ""
        lat, lon = _geocode(location)
        found.append(
            {
                "id": str(row.get("id") or link or f"{title}|{company}"),
                "name": company,
                "email": application_contact.recipient(snippet),
                "url": link,
                "phone": "",
                "city": location,
                "text": f"{title} {snippet} {company} {location}",
                "title": title,
                "contract_type": row.get("type") or "",
                "latitude": lat,
                "longitude": lon,
                "score": 0,
                "source": "jooble",
            }
        )
    return found


def _radius(km: int) -> str:
    for step in _RADIUS_STEPS:
        if step >= km:
            return str(step)
    return "80"


def _geocode(place: str) -> tuple[float | None, float | None]:
    key = place.strip().lower()
    if not key:
        return None, None
    if key in _GEOCODE:
        cached = _GEOCODE[key]
        return (None, None) if cached is None else cached
    from hellowork import geo
    prefix = re.match(r'^\s*(\d{2}|2[AB])\s*[-–]\s*', place, re.I)
    postcode = re.search(r'\b(\d{2})\d{3}\b', place)
    department = prefix.group(1) if prefix else (postcode.group(1) if postcode else '')
    try:
        point = geo.geocode(place, department)
    except Exception:
        return None, None
    if point is None:
        return None, None
    _GEOCODE[key] = point
    return point
