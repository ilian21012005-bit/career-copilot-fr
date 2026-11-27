"""Connecteur public Teamtailor (flux RSS `/jobs.rss`) en lecture seule."""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from lxml import etree

import filters
import public_network
import source_common

LOG = logging.getLogger("teamtailor")
MAX_PER_BOARD = 25

DEFAULT_STAGE_SLUGS: tuple[tuple[str, str], ...] = (
    ("advens", "Advens"),
    ("almond", "Almond"),
    ("intrinsec", "Intrinsec"),
    ("synetis", "Synetis"),
    ("i-tracing", "I-Tracing"),
    ("yeswehack", "YesWeHack"),
)

_SAFE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    load_dtd=False,
    huge_tree=False,
)
_KNOWN_FR_CITIES_RE = re.compile(
    r"\b(Paris|Saclay|Orsay|Massy|Palaiseau|Villebon(?:-sur-Yvette)?|Vélizy(?:-Villacoublay)?|"
    r"Les\s+Ulis|Bures-sur-Yvette|Gif-sur-Yvette|Courtab[oeœ]uf|Sèvres|Issy-les-Moulineaux|"
    r"Boulogne-Billancourt|La\s+Défense|Courbevoie|Nanterre|Levallois-Perret|Mantes-la-Jolie|"
    r"Versailles|Saint-Quentin-en-Yvelines|Guyancourt|Pessac|Bordeaux|Mérignac|Talence)\b",
    re.I,
)


def enabled(env: dict[str, str] | None = None) -> bool:
    """Actif par défaut sauf `TEAMTAILOR_ENABLED=0`."""
    values = env if env is not None else os.environ
    flag = str(values.get("TEAMTAILOR_ENABLED", "1") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _slugs(env: dict[str, str] | None, *, campaign: str) -> tuple[tuple[str, str], ...]:
    values = env if env is not None else os.environ
    if campaign == "job":
        raw_job = str(values.get("TEAMTAILOR_JOB_SLUGS") or "").strip()
        return source_common.parse_company_slugs(raw_job, ()) if raw_job else ()
    raw_stage = str(values.get("TEAMTAILOR_SLUGS") or "").strip()
    return source_common.parse_company_slugs(raw_stage, DEFAULT_STAGE_SLUGS)


def _child_text(node: etree._Element, names: tuple[str, ...]) -> str:
    wanted = {name.lower() for name in names}
    for child in node:
        local = str(etree.QName(child.tag).localname or "").lower()
        if local in wanted:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return ""


def _infer_city(item_node: etree._Element, title: str, body: str) -> tuple[str, str]:
    loc = _child_text(item_node, ("location", "city", "locations"))
    if loc and not source_common.is_ambiguous_location(loc):
        return loc, source_common.extract_department(loc)
    inferred_city, inferred_dept = source_common.infer_fr_city(title, body)
    if inferred_city:
        return inferred_city, inferred_dept or source_common.extract_department(loc)
    return loc, source_common.extract_department(loc)


def parse_rss(raw_xml: bytes, company: str, slug: str, *, campaign: str = "stage", geocoder=None) -> list[dict[str, Any]]:
    """Parse un flux RSS Teamtailor (`/jobs.rss`) en rejetant toute entité XML externe."""
    if not raw_xml:
        return []
    head = raw_xml[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise ValueError("Flux RSS Teamtailor rejeté : DOCTYPE/ENTITY interdit")
    root = etree.fromstring(raw_xml, parser=_SAFE_XML_PARSER)
    offers: list[dict[str, Any]] = []
    coord_cache: dict[tuple[str, str], tuple[float | None, float | None]] = {}

    for item in root.xpath(".//item"):
        title = _child_text(item, ("title",))
        link = _child_text(item, ("link",))
        guid = _child_text(item, ("guid",)) or link
        raw_desc = _child_text(item, ("encoded", "description"))
        description = source_common.strip_html(raw_desc, limit=5000)
        if not title or not link:
            continue
        parsed_url = urlparse(link)
        if parsed_url.scheme != "https":
            continue

        if campaign == "stage":
            if not source_common.stage_candidate_ok(title, description, "teamtailor"):
                continue
        else:
            if not filters.job_candidate_ok(title, description):
                continue

        city, dept = _infer_city(item, title, description)
        lat, lon = source_common.resolve_zone_coordinates(
            city,
            dept,
            campaign=campaign,
            geocoder=geocoder,
            cache=coord_cache,
        )
        if not source_common.within_any_zone(lat, lon, campaign):
            continue

        offer = source_common.build_offer(
            offer_id=source_common.stable_id("tt", slug, guid),
            url=link,
            title=title,
            company=company,
            city=city,
            latitude=lat,
            longitude=lon,
            description=description,
            source="teamtailor",
            contract_type="stage" if campaign == "stage" else "",
        )
        offers.append(offer)
        if len(offers) >= MAX_PER_BOARD:
            break
    return offers


def search(
    env: dict[str, str] | None = None,
    *,
    campaign: str = "stage",
    fetcher=None,
    geocoder=None,
) -> list[dict[str, Any]]:
    """Collecte les annonces publiques Teamtailor configurées pour la campagne demandée."""
    if not enabled(env):
        return []
    targets = _slugs(env, campaign=campaign)
    if not targets:
        return []

    http_fetch = fetcher or (
        lambda url: public_network.fetch(
            url,
            headers={
                "User-Agent": source_common.UA,
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
            timeout=15.0,
        )
    )

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for slug, company in targets:
        feed_url = f"https://{slug}.teamtailor.com/jobs.rss"
        try:
            status, body = http_fetch(feed_url)
        except Exception as exc:
            LOG.warning("Teamtailor %s erreur (%s)", slug, type(exc).__name__)
            continue
        if source_common.is_rate_limited(status):
            LOG.warning("Teamtailor arrêté sur HTTP %s (%s)", status, slug)
            break
        if status != 200 or not body:
            continue
        try:
            parsed = parse_rss(body, company, slug, campaign=campaign, geocoder=geocoder)
        except Exception as exc:
            LOG.warning("Teamtailor %s RSS invalide (%s)", slug, type(exc).__name__)
            continue
        for offer in parsed:
            if offer["id"] not in seen_ids:
                seen_ids.add(offer["id"])
                results.append(offer)
    return results
