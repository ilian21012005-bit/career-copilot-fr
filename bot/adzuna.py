"""Annonces Adzuna avec backoff borné et circuit-breaker 429/503."""

from __future__ import annotations

import http.client
import json
import logging
import re
import time
import urllib.parse

import application_contact
import public_network

LOG = logging.getLogger("adzuna")
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
SKIP_EMAIL = ("noreply", "no-reply", "donotreply", "exemple.com")

_TRANSIENT_STATUSES = {429, 502, 503, 504}
_CIRCUIT_THRESHOLD = 2
_CONSECUTIVE_FAILURES = 0
_CIRCUIT_OPEN = False


def reset_circuit() -> None:
    """Réinitialise le coupe-circuit Adzuna en début de cycle."""
    global _CONSECUTIVE_FAILURES, _CIRCUIT_OPEN
    _CONSECUTIVE_FAILURES = 0
    _CIRCUIT_OPEN = False


def circuit_open() -> bool:
    return _CIRCUIT_OPEN


def enabled(env: dict[str, str]) -> bool:
    import os

    cfg = env or {}
    comm = str(cfg.get("COMMERCIAL_SAFE") or os.getenv("COMMERCIAL_SAFE", "0")).strip().lower()
    edition = str(cfg.get("CAREER_EDITION") or os.getenv("CAREER_EDITION", "")).strip().lower()
    if (comm in {"1", "true", "yes", "on", "oui"} or edition == "commercial") and str(
        cfg.get("ADZUNA_COMMERCIAL_LICENSE") or os.getenv("ADZUNA_COMMERCIAL_LICENSE", "0")
    ).strip().lower() not in {"1", "true", "yes"}:
        return False
    return bool(cfg.get("ADZUNA_APP_ID") and cfg.get("ADZUNA_APP_KEY"))


def search(
    env: dict[str, str],
    what: str,
    where: str,
    max_days_old: int,
    distance: int,
    *,
    sleep=time.sleep,
) -> list[dict]:
    global _CONSECUTIVE_FAILURES, _CIRCUIT_OPEN
    if _CIRCUIT_OPEN:
        return []

    params = {
        "app_id": env["ADZUNA_APP_ID"],
        "app_key": env["ADZUNA_APP_KEY"],
        "what": what,
        "where": where,
        "distance": distance,
        "max_days_old": max_days_old,
        "results_per_page": 20,
        "sort_by": "date",
        "content-type": "application/json",
    }
    url = "https://api.adzuna.com/v1/api/jobs/fr/search/1?" + urllib.parse.urlencode(params)
    payload: dict | None = None
    for attempt in range(2):
        try:
            status, raw = public_network.fetch(
                url,
                headers={"Accept": "application/json"},
                timeout=30,
                max_bytes=4 * 1024 * 1024,
            )
            if status in _TRANSIENT_STATUSES:
                if attempt == 0:
                    sleep(1.0)
                    continue
                _CONSECUTIVE_FAILURES += 1
                if _CONSECUTIVE_FAILURES >= _CIRCUIT_THRESHOLD:
                    _CIRCUIT_OPEN = True
                    LOG.warning("Adzuna circuit ouvert après HTTP %s", status)
                return []
            if status >= 400:
                raise RuntimeError(f"Adzuna HTTP {status}")
            payload = json.loads(raw.decode("utf-8"))
            _CONSECUTIVE_FAILURES = 0
            break
        except (public_network.NetworkPolicyError, http.client.HTTPException, OSError, ValueError):
            if attempt == 0:
                sleep(0.5)
                continue
            _CONSECUTIVE_FAILURES += 1
            if _CONSECUTIVE_FAILURES >= _CIRCUIT_THRESHOLD:
                _CIRCUIT_OPEN = True
                LOG.warning("Adzuna circuit ouvert après erreurs réseau ou réponses invalides")
            return []

    if not isinstance(payload, dict):
        return []
    found = []
    for row in payload.get("results") or []:
        company = (row.get("company") or {}).get("display_name") or "Entreprise"
        description = row.get("description") or ""
        title = row.get("title") or what
        location = (row.get("location") or {}).get("display_name") or where
        email = application_contact.recipient(description)
        redirect = row.get("redirect_url") or ""
        found.append(
            {
                "id": str(row.get("id") or redirect or f"{title}|{company}"),
                "name": company,
                "email": email,
                "url": redirect,
                "phone": "",
                "city": location,
                "text": f"{title} {description} {company} {location}",
                "title": title,
                "contract_type": row.get("contract_type") or "",
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "score": 0,
                "source": "adzuna",
            }
        )
    return found
