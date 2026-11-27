"""Découverte lecture seule via Choisir le Service Public (flux RSS officiels + CSV Open Data)."""

from __future__ import annotations

import csv
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import public_network
from filters import _fold
from source_common import (
    UA,
    build_offer,
    extract_department,
    is_rate_limited,
    resolve_coordinates,
    stable_id,
    strip_html,
    within_any_zone,
)

LOG = logging.getLogger("csp_offres")

TS_RSS_BASE = "https://place-ep-recrute.talent-soft.com/handlers/offerRss.ashx"

# Identifiants officiels TalentSoft Choisir le Service Public (famille Numérique = 3522).
ZONE_DEPARTMENTS: tuple[tuple[str, str], ...] = (
    ("91", "282"),  # Essonne
    ("78", "289"),  # Yvelines
    ("92", "283"),  # Hauts-de-Seine
    ("75", "284"),  # Paris
    ("94", "287"),  # Val-de-Marne
    ("93", "286"),  # Seine-Saint-Denis
    ("95", "288"),  # Val-d'Oise
    ("77", "285"),  # Seine-et-Marne
    ("33", "239"),  # Gironde
)
NUMERIQUE_FAMILY_ID = "3522"


def default_rss_feeds() -> list[tuple[str, str]]:
    return [
        (dept_code, f"{TS_RSS_BASE}?LCID=1036&Rss_JobFamily={NUMERIQUE_FAMILY_ID}&Rss_JobDepartment={ts_id}")
        for dept_code, ts_id in ZONE_DEPARTMENTS
    ]


def enabled(env: dict[str, str] | None = None) -> bool:
    source = env or {}
    flag = str(source.get("CSP_ENABLED", "1")).strip().lower()
    return flag not in {"0", "false", "no", "non"}


def _clean_csp_url(raw: str) -> str:
    url = str(raw or "").strip()
    if not url:
        return ""
    return re.sub(r"\?tracking=1&idOrigine=\d+$", "", url)


def _split_rss_title(raw_title: str) -> tuple[str, str]:
    title = str(raw_title or "").strip()
    if " - " in title:
        prefix, rest = title.split(" - ", 1)
        if re.match(r"^[A-Z0-9_/-]{4,}$", prefix.strip()):
            return prefix.strip(), rest.strip()
    return "", title


def _is_stage_text(*parts: str, allow_alternance: bool = False) -> bool:
    folded = _fold(" ".join(p for p in parts if p))
    if not folded:
        return False
    is_alt = "alternan" in folded or "apprent" in folded
    if is_alt:
        return allow_alternance
    return bool(re.search(r"(?<![a-z0-9])(stage|stagiaire|intern|internship)(?![a-z0-9])", folded))


def parse_rss_items(raw_xml: bytes, *, dept_hint: str = "", stage_only: bool = True, allow_alternance: bool = False) -> list[dict]:
    """Parse un flux RSS TalentSoft Choisir le Service Public (XXE bloqué)."""
    if not raw_xml:
        return []
    upper = raw_xml[:4096].upper()
    if b"<!ENTITY" in upper or b"<!DOCTYPE" in upper:
        raise ValueError("Déclaration XML interdite dans le flux RSS")
    root = ET.fromstring(raw_xml)
    parsed: list[dict] = []
    for item in root.findall(".//item"):
        raw_title = (item.findtext("title") or "").strip()
        ref, title = _split_rss_title(raw_title)
        link = _clean_csp_url(item.findtext("link") or "")
        categories = [re.sub(r"\s+", " ", (c.text or "")).strip() for c in item.findall("category") if (c.text or "").strip()]
        desc_raw = item.findtext("description") or ""
        desc = strip_html(desc_raw)
        nature = categories[1] if len(categories) >= 2 else ""
        location = categories[-1] if categories else ""
        if stage_only and not _is_stage_text(title, nature, desc, allow_alternance=allow_alternance):
            continue
        parsed.append({
            "ref": ref,
            "title": title,
            "url": link,
            "company": "Fonction publique / CSP",
            "location": location,
            "department": extract_department(location) or dept_hint,
            "description": f"{title}\n{desc}".strip(),
        })
    return parsed


def parse_csv_rows(lines: Iterable[str], *, allowed_depts: set[str] | None = None, stage_only: bool = True, allow_alternance: bool = False) -> list[dict]:
    """Parse le CSV Open Data data.gouv.fr (séparateur ;) de Choisir le Service Public."""
    allowed = allowed_depts
    reader = csv.DictReader(lines, delimiter=";")
    parsed: list[dict] = []
    for row in reader:
        ref = str(row.get("Référence") or "").strip()
        title = str(row.get("Intitulé du poste") or "").strip()
        if not title:
            continue
        metier = str(row.get("Métier") or "").strip()
        nature = str(row.get("Nature de l'emploi") or "").strip()
        contrat = str(row.get("Nature de contrat") or "").strip()
        loc_poste = str(row.get("Localisation du poste") or "").strip()
        lieu_aff = str(row.get("Lieu d'affectation") or row.get("Lieu d'affectation (sans géolocalisation)") or "").strip()
        dept = extract_department(lieu_aff) or extract_department(loc_poste)
        if allowed and dept and dept not in allowed:
            continue
        if stage_only and not _is_stage_text(title, nature, contrat, allow_alternance=allow_alternance):
            continue
        employeur = str(row.get("Employeur") or row.get("Organisme de rattachement") or "Service public").strip()
        slug = re.sub(r"[^a-z0-9-]+", "-", _fold(f"{title}-reference-{ref}" if ref else title)).strip("-")
        url = f"https://choisirleservicepublic.gouv.fr/offre-emploi/{slug}/" if slug else ""
        parsed.append({
            "ref": ref,
            "title": title,
            "url": url,
            "company": employeur,
            "location": lieu_aff or loc_poste,
            "department": dept,
            "description": " — ".join(p for p in (metier, nature, contrat, lieu_aff) if p),
        })
    return parsed


def _normalize_entries(entries: list[dict], *, campaign: str, coord_cache: dict, seen_urls: set[str]) -> list[dict]:
    out: list[dict] = []
    for entry in entries:
        url = str(entry.get("url") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not url or not title or url in seen_urls:
            continue
        loc = str(entry.get("location") or "").strip()
        dept = str(entry.get("department") or "").strip() or extract_department(loc)
        lat, lon = resolve_coordinates(loc, dept, cache=coord_cache)
        if not within_any_zone(lat, lon, campaign):
            continue
        seen_urls.add(url)
        city_label = f"{loc} ({dept})" if loc and dept and f"({dept})" not in loc else (loc or dept)
        out.append(
            build_offer(
                offer_id=stable_id("csp", entry.get("ref") or "", url),
                url=url,
                title=title,
                company=str(entry.get("company") or "Service public").strip(),
                city=city_label,
                latitude=lat,
                longitude=lon,
                description=str(entry.get("description") or title),
                source="csp",
                contract_type="stage" if campaign == "stage" else "",
            )
        )
    return out


def search(env: dict[str, str] | None = None, *, campaign: str = "stage") -> list[dict]:
    """Récupère les stages IT Choisir le Service Public dans les départements cibles."""
    if campaign != "stage":
        return []
    env = env or {}
    if not enabled(env):
        return []
    coord_cache: dict = {}
    seen_urls: set[str] = set()
    results: list[dict] = []

    csv_path = str(env.get("CSP_CSV_PATH") or "").strip()
    if csv_path:
        path = Path(csv_path)
        if path.is_file():
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    entries = parse_csv_rows(fh, stage_only=True)
                results.extend(_normalize_entries(entries, campaign=campaign, coord_cache=coord_cache, seen_urls=seen_urls))
            except Exception as exc:
                LOG.info("CSP CSV local erreur: %s", type(exc).__name__)

    custom_urls = [u.strip() for u in str(env.get("CSP_RSS_URLS") or "").split(",") if u.strip()]
    feeds = [(extract_department(u), u) for u in custom_urls] if custom_urls else default_rss_feeds()
    for dept_hint, feed_url in feeds:
        try:
            status, body = public_network.fetch(feed_url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, */*"}, timeout=10)
        except Exception as exc:
            LOG.info("CSP RSS erreur (%s): %s", dept_hint, type(exc).__name__)
            continue
        if is_rate_limited(status):
            LOG.warning("CSP RSS rate-limited (%s)", status)
            break
        if status != 200 or not body:
            continue
        try:
            entries = parse_rss_items(body, dept_hint=dept_hint, stage_only=True)
        except Exception as exc:
            LOG.info("CSP XML invalide (%s): %s", dept_hint, type(exc).__name__)
            continue
        results.extend(_normalize_entries(entries, campaign=campaign, coord_cache=coord_cache, seen_urls=seen_urls))
    return results
