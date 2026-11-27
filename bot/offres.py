"""Offres d'emploi France Travail. Une page de 20 annonces par recherche."""

from __future__ import annotations

import json
import re
import time
import urllib.parse

import jooble
import application_contact
import public_network

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"
DETAIL_URL = "https://candidat.francetravail.fr/offres/recherche/detail/{}"

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
SKIP_EMAIL = (
    "noreply",
    "no-reply",
    "donotreply",
    "exemple.com",
    "francetravail.fr",
    "francetravail.io",
    "pole-emploi.fr",
    "pole-emploi.io",
    "poleemploi.fr",
)
_TOKEN = {"value": "", "expires_at": 0.0}


def enabled(env: dict[str, str]) -> bool:
    return bool(env.get("FT_CLIENT_ID") and env.get("FT_CLIENT_SECRET"))


def search(env: dict[str, str], what: str, zone: dict) -> list[dict]:
    insee = str(zone.get("insee") or "").strip()
    city_name = str(zone.get("name") or "").strip()
    query_words = what if insee or not city_name else f"{what} {city_name}".strip()
    params: dict[str, str | int] = {
        "motsCles": query_words,
        "distance": int(zone.get("km") or 10),
        "range": "0-19",
    }
    if insee:
        params["commune"] = insee
    try:
        status, raw_bytes = public_network.fetch(
            SEARCH_URL + "?" + urllib.parse.urlencode(params),
            headers={
                "Authorization": f"Bearer {_token(env)}",
                "Accept": "application/json",
            },
            timeout=30,
            max_bytes=4 * 1024 * 1024,
        )
        if status >= 400:
            raise RuntimeError(f"France Travail HTTP {status}")
        raw = raw_bytes.decode("utf-8")
    finally:
        time.sleep(0.15)
    if not raw:
        return []
    payload = json.loads(raw)
    rows = payload.get("resultats") if isinstance(payload, dict) else []
    found = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        offer = normalize(item)
        with_coordinates(offer, jooble._geocode)
        found.append(offer)
    return found


def place_name(city: str) -> str:
    cleaned = re.sub(r"^\d{2,3}\s*-\s*", "", city or "").strip()
    if "arrondissement" in cleaned.lower() or cleaned.lower().startswith("paris"):
        return "Paris"
    return cleaned.split(",")[0].strip()


def with_coordinates(offer: dict, geocode) -> dict:
    if offer.get("latitude") is not None and offer.get("longitude") is not None:
        return offer
    latitude, longitude = geocode(place_name(str(offer.get("city") or "")))
    offer["latitude"] = latitude
    offer["longitude"] = longitude
    return offer


def normalize(item: dict) -> dict:
    title = str(item.get("intitule") or "").strip()
    description = str(item.get("description") or "")
    company = str((item.get("entreprise") or {}).get("nom") or "Entreprise").strip()
    place = item.get("lieuTravail") or {}
    city = str(place.get("libelle") or "").strip()
    contact = item.get("contact") or {}
    email_text = " ".join(
        str(contact.get(key) or "")
        for key in ("courriel", "coordonnees1", "coordonnees2", "coordonnees3")
    )
    offer_id = str(item.get("id") or "")
    origin = str((item.get("origineOffre") or {}).get("urlOrigine") or "")
    post = str(contact.get("urlPostulation") or "")
    if origin.startswith("http"):
        url = origin
    elif post.startswith("http"):
        url = post
    else:
        url = DETAIL_URL.format(offer_id) if offer_id else ""
    return {
        "id": offer_id or url or f"{title}|{company}",
        "name": company,
        "email": application_contact.recipient(description, contact_email=str(contact.get('courriel') or ''),
                                               contact_text=email_text),
        "url": url,
        "phone": "",
        "city": city,
        "text": f"{title} {description} {company} {city}",
        "title": title,
        "contract_type": _contract(item),
        "latitude": place.get("latitude"),
        "longitude": place.get("longitude"),
        "alternance": bool(item.get("alternance")),
        "score": 0,
        "source": "francetravail",
    }


def _contract(item: dict) -> str:
    duration = str(item.get("dureeTravailLibelleConverti") or "").lower()
    if "temps plein" in duration or "temps complet" in duration:
        return "full_time"
    if "temps partiel" in duration:
        return "part_time"
    return str(item.get("typeContratLibelle") or "")


def _token(env: dict[str, str]) -> str:
    if _TOKEN["value"] and _TOKEN["expires_at"] > time.time() + 30:
        return str(_TOKEN["value"])
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": env["FT_CLIENT_ID"],
            "client_secret": env["FT_CLIENT_SECRET"],
            "scope": SCOPE,
        }
    ).encode()
    status, raw_bytes = public_network.fetch(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=30,
        max_bytes=1 * 1024 * 1024,
        method="POST",
        body=body,
    )
    if status >= 400:
        raise RuntimeError(f"France Travail token HTTP {status}")
    payload = json.loads(raw_bytes.decode("utf-8"))
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("Jeton Offres d'emploi sans access_token.")
    _TOKEN["value"] = token
    _TOKEN["expires_at"] = time.time() + int(payload.get("expires_in") or 1200)
    return token
