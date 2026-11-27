"""Découverte lecture seule d'offres via API JSON publiques (Greenhouse, Lever, Ashby)."""

from __future__ import annotations

import json
import logging
from typing import Callable

import config
import filters
import public_network
from filters import OPERATIONAL_FOCUS_MARKERS, PURE_DEVELOPMENT_TITLES, _fold
from source_common import (
    UA,
    build_offer,
    extract_department,
    infer_fr_city,
    is_ambiguous_location,
    is_rate_limited,
    parse_company_slugs,
    resolve_zone_coordinates,
    stable_id,
    stage_candidate_ok,
    strip_html,
    within_any_zone,
)

LOG = logging.getLogger("ats_public")

GREENHOUSE_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("datadog", "Datadog"),
    ("algolia", "Algolia"),
    ("contentsquare", "Contentsquare"),
    ("doctolib", "Doctolib"),
    ("scaleway", "Scaleway"),
    ("mirakl", "Mirakl"),
    ("ledger", "Ledger"),
)

LEVER_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("mistralai", "Mistral AI"),
    ("payfit", "PayFit"),
    ("qonto", "Qonto"),
    ("alan", "Alan"),
    ("swile", "Swile"),
)

ASHBY_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("gitguardian", "GitGuardian"),
    ("dust", "Dust"),
    ("lakera", "Lakera"),
)


def _fetch_json(url: str, *, timeout: float = 12.0) -> object | None:
    status, raw = public_network.fetch(
        url,
        headers={"User-Agent": UA, "Accept": "application/json"},
        timeout=timeout,
    )
    if is_rate_limited(status):
        LOG.warning("ATS public rate limited (%s) sur %s", status, url)
        return None
    if status != 200 or not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None


def _parse_greenhouse(slug: str, payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    out: list[dict] = []
    for item in payload.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        loc = item.get("location")
        city = str(loc.get("name") or "") if isinstance(loc, dict) else str(loc or "")
        out.append(
            {
                "raw_id": str(item.get("id") or ""),
                "title": str(item.get("title") or "").strip(),
                "city": city.strip(),
                "url": str(item.get("absolute_url") or "").strip(),
                "description": strip_html(str(item.get("content") or "")),
            }
        )
    return out


def _parse_lever(slug: str, payload: object) -> list[dict]:
    if not isinstance(payload, list):
        return []
    out: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        cats = item.get("categories")
        city = str(cats.get("location") or "") if isinstance(cats, dict) else ""
        desc = str(item.get("descriptionPlain") or "") or strip_html(str(item.get("description") or ""))
        out.append(
            {
                "raw_id": str(item.get("id") or ""),
                "title": str(item.get("text") or "").strip(),
                "city": city.strip(),
                "url": str(item.get("hostedUrl") or "").strip(),
                "description": desc,
            }
        )
    return out


def _parse_ashby(slug: str, payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    out: list[dict] = []
    for item in payload.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        desc = str(item.get("descriptionPlain") or "") or strip_html(str(item.get("descriptionHtml") or ""))
        out.append(
            {
                "raw_id": str(item.get("id") or ""),
                "title": str(item.get("title") or "").strip(),
                "city": str(item.get("location") or "").strip(),
                "url": str(item.get("jobUrl") or "").strip(),
                "description": desc,
            }
        )
    return out


_PROVIDERS: tuple[tuple[str, str, str, tuple[tuple[str, str], ...], Callable[[str, object], list[dict]]], ...] = (
    (
        "greenhouse",
        "GREENHOUSE_COMPANIES",
        "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
        GREENHOUSE_DEFAULTS,
        _parse_greenhouse,
    ),
    (
        "lever",
        "LEVER_COMPANIES",
        "https://api.lever.co/v0/postings/{slug}?mode=json",
        LEVER_DEFAULTS,
        _parse_lever,
    ),
    (
        "ashby",
        "ASHBY_COMPANIES",
        "https://api.ashbyhq.com/posting-api/job-board/{slug}?listedOnly=true",
        ASHBY_DEFAULTS,
        _parse_ashby,
    ),
)


def enabled(env: dict[str, str] | None = None) -> bool:
    source = env or {}
    flag = str(source.get("ATS_PUBLIC_ENABLED", "1")).strip().lower()
    return flag not in {"0", "false", "no", "non"}


_STAGE_TOKENS = ("stage", "stagiaire", "intern", "internship")
_ALTERNANCE_TOKENS = ("alternance", "alternant", "apprentissage", "apprenti", "contrat pro")


def _matches_campaign(title: str, body: str, campaign: str) -> bool:
    folded_title = _fold(title)
    if any(marker in folded_title for marker in PURE_DEVELOPMENT_TITLES) and not any(
        marker in folded_title for marker in OPERATIONAL_FOCUS_MARKERS
    ):
        return False
    if campaign == "alternance":
        if not any(tok in folded_title for tok in _ALTERNANCE_TOKENS):
            return False
        blob = f"{title} {body}".strip()
        if not blob or filters.excluded(blob) or filters.too_senior(title):
            return False
        return filters.stage_relevant(blob, "ats_public")
    if campaign == "stage":
        if not any(tok in folded_title for tok in _STAGE_TOKENS):
            return False
        return stage_candidate_ok(title, body, "ats_public")
    return False


def _is_stage_or_intern(title: str, body: str) -> bool:
    return _matches_campaign(title, body, "stage")


def search(
    env: dict[str, str] | None = None,
    *,
    campaign: str = "stage",
    fetcher: Callable[[str], object | None] | None = None,
    geocoder: Callable[[str, str], tuple[float, float] | None] | None = None,
) -> list[dict]:
    """Récupère les offres de stage ou d'alternance IT (Greenhouse, Lever, Ashby) dans nos bassins."""
    if campaign not in ("stage", "alternance"):
        return []
    cfg = env or {}
    if not enabled(cfg):
        return []

    fetch = fetcher or _fetch_json
    geo_cache: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    offers: list[dict] = []
    seen_ids: set[str] = set()

    for provider_name, env_key, url_tmpl, defaults, parser in _PROVIDERS:
        companies = parse_company_slugs(str(cfg.get(env_key) or ""), defaults)
        for slug, company_label in companies:
            try:
                payload = fetch(url_tmpl.format(slug=slug))
            except Exception as exc:
                LOG.info("%s/%s indisponible : %s", provider_name, slug, type(exc).__name__)
                continue
            for item in parser(slug, payload):
                title = item["title"]
                desc = item["description"]
                url = item["url"]
                if not title or not url or not _matches_campaign(title, desc, campaign):
                    continue
                city = item["city"]
                dept = extract_department(city)
                if is_ambiguous_location(city):
                    folded_city = _fold(city)
                    hints_france = any(tok in folded_city for tok in ("france", "ile de france", "parisienne", "grand paris"))
                    inferred_city, inferred_dept = infer_fr_city(title, desc if hints_france else "")
                    if inferred_city:
                        city = inferred_city
                        dept = dept or inferred_dept
                zone_campaign = campaign if config.ZONES.get(campaign) else "stage"
                lat, lon = resolve_zone_coordinates(
                    city,
                    dept,
                    campaign=zone_campaign,
                    geocoder=geocoder,
                    cache=geo_cache,
                )
                in_zone = within_any_zone(lat, lon, campaign)
                if not in_zone and campaign == "alternance" and not config.ZONES.get("alternance"):
                    in_zone = within_any_zone(lat, lon, "stage")
                if not in_zone:
                    continue
                offer_id = stable_id(provider_name[:2], slug, item["raw_id"] or url)
                if offer_id in seen_ids:
                    continue
                seen_ids.add(offer_id)
                offers.append(
                    build_offer(
                        offer_id=offer_id,
                        url=url,
                        title=title,
                        company=company_label,
                        city=city,
                        latitude=lat,
                        longitude=lon,
                        description=desc,
                        source=provider_name,
                        contract_type=campaign,
                        notes=f"[{provider_name}] board={slug}",
                    )
                )
    return offers
