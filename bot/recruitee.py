"""Connecteur public Recruitee (`/api/offers/`) en lecture seule."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import filters
import public_network
import source_common

LOG = logging.getLogger("recruitee")
MAX_PER_BOARD = 25

DEFAULT_STAGE_SLUGS: tuple[tuple[str, str], ...] = (
    ("sekoia", "SEKOIA.IO"),
    ("gatewatcher", "Gatewatcher"),
    ("harfanglab", "HarfangLab"),
    ("cybelangel", "CybelAngel"),
    ("glimps", "GLIMPS"),
)


def enabled(env: dict[str, str] | None = None) -> bool:
    """Actif par défaut sauf `RECRUITEE_ENABLED=0`."""
    values = env if env is not None else os.environ
    flag = str(values.get("RECRUITEE_ENABLED", "1") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _slugs(env: dict[str, str] | None, *, campaign: str) -> tuple[tuple[str, str], ...]:
    values = env if env is not None else os.environ
    if campaign == "job":
        raw_job = str(values.get("RECRUITEE_JOB_SLUGS") or "").strip()
        return source_common.parse_company_slugs(raw_job, ()) if raw_job else ()
    raw_stage = str(values.get("RECRUITEE_SLUGS") or "").strip()
    return source_common.parse_company_slugs(raw_stage, DEFAULT_STAGE_SLUGS)


def _is_france_offer(row: dict[str, Any]) -> bool:
    code = str(row.get("country_code") or "").strip().upper()
    if code:
        return code == "FR"
    country = filters._fold(str(row.get("country") or ""))
    if country:
        return "france" in country
    return True


def parse_offers(
    payload: dict[str, Any],
    company: str,
    slug: str,
    *,
    campaign: str = "stage",
    geocoder=None,
) -> list[dict[str, Any]]:
    """Normalise la réponse JSON `/api/offers/` d'un portail Recruitee."""
    rows = payload.get("offers") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    offers: list[dict[str, Any]] = []
    coord_cache: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        status_txt = str(row.get("status") or "").strip().lower()
        if status_txt and status_txt != "published":
            continue
        if not _is_france_offer(row):
            continue

        title = str(row.get("title") or "").strip()
        url = str(row.get("careers_url") or row.get("url") or "").strip()
        parsed_url = urlparse(url)
        if not title or parsed_url.scheme != "https":
            continue

        desc_html = f"{row.get('description') or ''}\n{row.get('requirements') or ''}"
        description = source_common.strip_html(desc_html, limit=5000)
        emp_type = filters._fold(str(row.get("employment_type_code") or ""))

        if campaign == "stage":
            if not source_common.stage_candidate_ok(title, f"{emp_type} {description}", "recruitee"):
                continue
        else:
            if not filters.job_candidate_ok(title, f"{emp_type} {description}", emp_type):
                continue

        city = str(row.get("city") or row.get("location") or "").strip()
        postal = str(row.get("postal_code") or "").strip()
        dept = postal[:2] if len(postal) >= 2 and postal[:2].isdigit() else source_common.extract_department(city)
        if source_common.is_ambiguous_location(city):
            inferred_city, inferred_dept = source_common.infer_fr_city(title, description)
            if inferred_city:
                city = inferred_city
                dept = dept or inferred_dept
        lat, lon = source_common.resolve_zone_coordinates(
            city,
            dept,
            campaign=campaign,
            geocoder=geocoder,
            cache=coord_cache,
        )
        if not source_common.within_any_zone(lat, lon, campaign):
            continue

        oid = str(row.get("id") or row.get("slug") or url)
        offers.append(
            source_common.build_offer(
                offer_id=source_common.stable_id("rc", slug, oid),
                url=url,
                title=title,
                company=str(row.get("company_name") or company).strip() or company,
                city=city,
                latitude=lat,
                longitude=lon,
                description=description,
                source="recruitee",
                contract_type="stage" if campaign == "stage" else "",
            )
        )
        if len(offers) >= MAX_PER_BOARD:
            break
    return offers


def search(
    env: dict[str, str] | None = None,
    *,
    campaign: str = "stage",
    get_json_fn=None,
    geocoder=None,
) -> list[dict[str, Any]]:
    """Collecte les offres publiées sur les portails Recruitee configurés."""
    if not enabled(env):
        return []
    targets = _slugs(env, campaign=campaign)
    if not targets:
        return []

    fetcher = get_json_fn or (
        lambda url: public_network.get_json(
            url,
            headers={"User-Agent": source_common.UA, "Accept": "application/json"},
            timeout=15.0,
        )
    )

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for slug, company in targets:
        api_url = f"https://{slug}.recruitee.com/api/offers/"
        try:
            status, payload = fetcher(api_url)
        except Exception as exc:
            LOG.warning("Recruitee %s erreur (%s)", slug, type(exc).__name__)
            continue
        if source_common.is_rate_limited(status):
            LOG.warning("Recruitee arrêté sur HTTP %s (%s)", status, slug)
            break
        if status != 200 or not isinstance(payload, dict):
            continue
        for offer in parse_offers(payload, company, slug, campaign=campaign, geocoder=geocoder):
            if offer["id"] not in seen_ids:
                seen_ids.add(offer["id"])
                results.append(offer)
    return results
