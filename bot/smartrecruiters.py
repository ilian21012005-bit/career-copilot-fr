"""Découverte lecture seule d'offres via l'API publique SmartRecruiters."""

from __future__ import annotations

import logging
import re

import public_network
from filters import PURE_DEVELOPMENT_TITLES, _fold
from source_common import (
    UA,
    build_offer,
    is_rate_limited,
    resolve_coordinates,
    stable_id,
    strip_html,
    within_any_zone,
)

LOG = logging.getLogger("smartrecruiters")

API_BASE = "https://api.smartrecruiters.com/v1/companies"

STAGE_COMPANIES = (
    "Devoteam",
    "Alten",
    "Talan",
    "Assystem",
    "BoschGroup",
    "Coface",
    "OECD",
    "Boulanger",
)

JOB_COMPANIES = (
    "Boulanger",
    "GaleriesLafayette",
    "Kiabi",
    "Conforama",
)

_JOB_PRE_HINTS = (
    "polyvalent", "rayon", "caisse", "caissier", "vendeur", "vendeuse",
    "conseiller", "magasin", "accueil", "hote", "preparateur", "commandes",
    "logistique", "inventaire", "manutention", "colis", "trieur", "entrepot",
    "drive", "noel", "saisonnier", "renfort", "interim", "equipier", "libre service",
)
_JOB_PRE_REJECT = ("alternan", "apprent", "caces", "cariste", "boucher", "poissonnier", "charcutier", "patissier", "boulanger", "cuisinier")


def enabled(env: dict[str, str] | None = None) -> bool:
    source = env or {}
    flag = str(source.get("SMARTRECRUITERS_ENABLED", "1")).strip().lower()
    return flag not in {"0", "false", "no", "non"}


def _companies_for(env: dict[str, str], campaign: str) -> list[str]:
    key = f"SMARTRECRUITERS_{campaign.upper()}_COMPANIES"
    raw = str(env.get(key) or env.get("SMARTRECRUITERS_COMPANIES") or "").strip()
    if raw:
        items = [part.strip() for part in raw.split(",") if part.strip()]
        if items:
            return items
    return list(STAGE_COMPANIES if campaign == "stage" else JOB_COMPANIES)


def _posting_coords(loc: dict, cache: dict) -> tuple[float | None, float | None]:
    try:
        lat_raw, lon_raw = loc.get("latitude"), loc.get("longitude")
        if lat_raw not in (None, "") and lon_raw not in (None, ""):
            return float(lat_raw), float(lon_raw)
    except (TypeError, ValueError):
        pass
    city = str(loc.get("city") or "").strip()
    postal = str(loc.get("postalCode") or "").strip()
    dept = postal[:2] if len(postal) >= 2 and postal[:2].isdigit() else ""
    return resolve_coordinates(city, dept, cache=cache)


def _contract_type(posting: dict, campaign: str) -> str:
    if campaign == "stage":
        return "stage"
    emp = posting.get("typeOfEmployment") or {}
    emp_id = _fold(str(emp.get("id") or emp.get("label") or ""))
    customs = posting.get("customField") or []
    custom_text = " ".join(str(c.get("valueLabel") or "") for c in customs if isinstance(c, dict))
    custom_f = _fold(custom_text)
    if "part" in emp_id or "partiel" in emp_id or "partiel" in custom_f:
        return "part_time"
    if "tempor" in emp_id or "cdd" in custom_f or "saison" in custom_f or "interim" in custom_f:
        return "full_time" if "full" in emp_id else "contract"
    if "permanent" in emp_id or "permanent" in custom_f or "cdi" in custom_f:
        return "permanent"
    if "full" in emp_id:
        return "full_time"
    return ""


def _pre_matches_title(title: str, campaign: str) -> bool:
    folded = _fold(title)
    if not folded:
        return False
    if campaign == "stage":
        if not any(tok in folded for tok in ("stage", "stagiaire", "intern")):
            return False
        if "alternan" in folded or "apprent" in folded:
            return False
        if any(_fold(m) in folded for m in PURE_DEVELOPMENT_TITLES):
            return False
        return True
    if any(bad in folded for bad in _JOB_PRE_REJECT):
        return False
    return any(hint in folded for hint in _JOB_PRE_HINTS)


def _detail_description(detail: dict | None) -> tuple[str, str]:
    if not isinstance(detail, dict):
        return "", ""
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    parts: list[str] = []
    for key in ("jobDescription", "qualifications", "additionalInformation", "companyDescription"):
        sec = sections.get(key)
        if isinstance(sec, dict) and sec.get("text"):
            cleaned = strip_html(str(sec["text"]))
            if cleaned:
                parts.append(cleaned)
    posting_url = str(detail.get("postingUrl") or "").strip()
    return "\n\n".join(parts)[:8000], posting_url


def normalize_posting(
    company_id: str,
    posting: dict,
    *,
    campaign: str,
    detail: dict | None = None,
    coord_cache: dict | None = None,
) -> dict | None:
    """Convertit un posting JSON SmartRecruiters en offre normalisée."""
    if not isinstance(posting, dict):
        return None
    title = str(posting.get("name") or "").strip()
    pid = str(posting.get("id") or "").strip()
    if not title or not pid:
        return None
    loc = posting.get("location") or {}
    country = str(loc.get("country") or "").strip().lower()
    if country and country != "fr":
        return None

    lat, lon = _posting_coords(loc, coord_cache if coord_cache is not None else {})
    if not within_any_zone(lat, lon, campaign):
        return None

    desc, detail_url = _detail_description(detail)
    slug = re.sub(r"[^a-z0-9]+", "-", _fold(title)).strip("-")
    fallback_url = f"https://jobs.smartrecruiters.com/{company_id}/{pid}-{slug}" if slug else f"https://jobs.smartrecruiters.com/{company_id}/{pid}"
    url = detail_url or fallback_url
    comp_name = str((posting.get("company") or {}).get("name") or company_id).strip()
    city = str(loc.get("city") or "").strip()
    postal = str(loc.get("postalCode") or "").strip()
    city_label = f"{city} ({postal[:2]})" if city and len(postal) >= 2 and postal[:2].isdigit() else city

    return build_offer(
        offer_id=stable_id("sr", company_id, pid),
        url=url,
        title=title,
        company=comp_name,
        city=city_label,
        latitude=lat,
        longitude=lon,
        description=desc or f"{title} — {comp_name} ({city_label})",
        source="smartrecruiters",
        contract_type=_contract_type(posting, campaign),
    )


def search(
    env: dict[str, str] | None = None,
    *,
    campaign: str = "stage",
    max_pages: int = 3,
    max_details: int = 25,
) -> list[dict]:
    """Récupère les offres SmartRecruiters France dans les bassins de la campagne."""
    env = env or {}
    if not enabled(env):
        return []
    companies = _companies_for(env, campaign)
    results: list[dict] = []
    seen_ids: set[str] = set()
    coord_cache: dict = {}
    details_fetched = 0

    for cid in companies:
        for page in range(max_pages):
            offset = page * 100
            url = f"{API_BASE}/{cid}/postings?limit=100&offset={offset}&country=fr"
            try:
                status, data = public_network.get_json(url, headers={"User-Agent": UA}, timeout=10)
            except Exception as exc:
                LOG.info("SmartRecruiters %s erreur: %s", cid, type(exc).__name__)
                break
            if is_rate_limited(status):
                LOG.warning("SmartRecruiters rate-limited (%s), arrêt.", status)
                return results
            if status != 200 or not isinstance(data, dict):
                break
            content = data.get("content") or []
            if not content:
                break
            for posting in content:
                if not isinstance(posting, dict):
                    continue
                pid = str(posting.get("id") or "").strip()
                title = str(posting.get("name") or "").strip()
                if not pid or not _pre_matches_title(title, campaign):
                    continue
                loc = posting.get("location") or {}
                lat, lon = _posting_coords(loc, coord_cache)
                if not within_any_zone(lat, lon, campaign):
                    continue
                detail = None
                if details_fetched < max_details:
                    try:
                        d_status, d_data = public_network.get_json(f"{API_BASE}/{cid}/postings/{pid}", headers={"User-Agent": UA}, timeout=10)
                        details_fetched += 1
                        if is_rate_limited(d_status):
                            LOG.warning("SmartRecruiters detail rate-limited (%s)", d_status)
                            return results
                        if d_status == 200 and isinstance(d_data, dict):
                            detail = d_data
                    except Exception:
                        pass
                item = normalize_posting(cid, posting, campaign=campaign, detail=detail, coord_cache=coord_cache)
                if item and item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    results.append(item)
            total_found = int(data.get("totalFound") or 0)
            if offset + len(content) >= total_found:
                break
    return results
