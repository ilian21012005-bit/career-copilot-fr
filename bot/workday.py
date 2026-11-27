"""Découverte lecture seule via l'API publique Workday CXS (sans envoi auto)."""

from __future__ import annotations

import logging

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

LOG = logging.getLogger("workday")

STAGE_PORTALS: tuple[tuple[str, str, str, str], ...] = (
    ("ag", "wd3", "Airbus", "Airbus"),
    ("alliancewd", "wd3", "renault-group-careers", "Renault Group"),
    ("sanofi", "wd3", "SanofiCareers", "Sanofi"),
)

JOB_PORTALS: tuple[tuple[str, str, str, str], ...] = ()

STAGE_QUERIES: tuple[str, ...] = (
    "stage informatique",
    "stage reseau",
    "stage systeme",
    "stage cybersecurite",
    "stage cloud",
    "stage devops",
    "stage support",
)

JOB_QUERIES: tuple[str, ...] = (
    "noel",
    "saisonnier",
    "preparateur de commandes",
    "logistique",
    "vendeur",
    "caisse",
)

_NON_FRENCH_HINTS = (
    ", tx", ", ca", ", az", ", va", ", ny", ", fl", ", il", ", nc", ", ga", ", ks",
    "united states", "india", "germany", "deutschland", "spain", "espana", "united kingdom",
    "getafe", "hamburg", "bremen", "munich", "bristol", "filton", "manching",
)


def enabled(env: dict[str, str] | None = None) -> bool:
    source = env or {}
    flag = str(source.get("WORKDAY_ENABLED", "1")).strip().lower()
    return flag not in {"0", "false", "no", "non"}


def _parse_portals(raw: str) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    for chunk in str(raw or "").split(","):
        parts = [p.strip() for p in chunk.split(":") if p.strip()]
        if len(parts) >= 3:
            tenant, inst, site = parts[:3]
            company = parts[3] if len(parts) >= 4 else tenant.capitalize()
            out.append((tenant, inst, site, company))
    return out


def _portals_for(env: dict[str, str], campaign: str) -> list[tuple[str, str, str, str]]:
    key = f"WORKDAY_{campaign.upper()}_PORTALS"
    raw = str(env.get(key) or env.get("WORKDAY_PORTALS") or "").strip()
    if raw:
        parsed = _parse_portals(raw)
        if parsed:
            return parsed
    return list(STAGE_PORTALS if campaign == "stage" else JOB_PORTALS)


def _plausible_zone_location(location_text: str) -> bool:
    low = _fold(location_text)
    if not low or low in {"multiple locations", "2 locations", "3 locations"}:
        return True
    return not any(marker in low for marker in _NON_FRENCH_HINTS)


def _allow_pure_dev() -> bool:
    try:
        import candidate_config

        cfg = candidate_config.get_profile()
        return bool(cfg.allow_pure_software_dev)
    except Exception:
        return False


def _active_contracts() -> tuple[str, ...]:
    try:
        import candidate_config

        return tuple(candidate_config.get_profile().contracts)
    except Exception:
        return ("stage", "job")


def _pre_matches(title: str, campaign: str) -> bool:
    folded = _fold(title)
    if not folded:
        return False
    contracts = _active_contracts()
    if campaign == "alternance":
        if not any(
            tok in folded
            for tok in ("alternan", "apprent", "contrat pro", "professionnalisation")
        ):
            return False
        if not _allow_pure_dev() and any(
            _fold(m) in folded for m in PURE_DEVELOPMENT_TITLES
        ):
            return False
        return True
    if campaign == "stage":
        is_alt = "alternan" in folded or "apprent" in folded
        is_stg = any(tok in folded for tok in ("stage", "stagiaire", "intern"))
        if is_alt and "alternance" in contracts:
            pass
        elif not is_stg or is_alt:
            return False
        if not _allow_pure_dev() and any(
            _fold(m) in folded for m in PURE_DEVELOPMENT_TITLES
        ):
            return False
        return True
    if any(bad in folded for bad in ("alternan", "apprent", "caces", "cariste")):
        return False
    return True


def _contract_type(info: dict, campaign: str, title: str = "") -> str:
    folded = _fold(title)
    if campaign == "alternance" or "alternan" in folded or "apprent" in folded:
        return "alternance"
    if campaign == "stage":
        return "stage"
    tt = _fold(str(info.get("timeType") or ""))
    if "part" in tt:
        return "part_time"
    if "full" in tt:
        return "full_time"
    return ""


def normalize_posting(
    tenant: str,
    instance: str,
    site: str,
    company: str,
    posting: dict,
    *,
    campaign: str,
    detail: dict | None = None,
    coord_cache: dict | None = None,
) -> dict | None:
    """Convertit un jobPosting Workday (+ detail optionnel) en offre normalisée."""
    if not isinstance(posting, dict):
        return None
    title = str(posting.get("title") or "").strip()
    ext_path = str(posting.get("externalPath") or "").strip()
    if not title or not ext_path:
        return None
    if not ext_path.startswith("/"):
        ext_path = "/" + ext_path

    info = (detail or {}).get("jobPostingInfo") if isinstance(detail, dict) else {}
    if not isinstance(info, dict):
        info = {}
    country_desc = _fold(str(((info.get("country") or {}).get("descriptor")) or ""))
    if country_desc and country_desc != "france":
        return None

    loc_raw = str(info.get("location") or posting.get("locationsText") or "").strip()
    if not loc_raw:
        bullets = posting.get("bulletFields") or []
        if bullets and isinstance(bullets, list):
            loc_raw = str(bullets[0] or "").strip()
    lat, lon = resolve_coordinates(loc_raw, cache=coord_cache if coord_cache is not None else {})
    if not within_any_zone(lat, lon, campaign):
        return None

    desc = strip_html(str(info.get("jobDescription") or ""))
    external_url = str(info.get("externalUrl") or "").strip()
    url = external_url or f"https://{tenant}.{instance}.myworkdayjobs.com/{site}{ext_path}"

    return build_offer(
        offer_id=stable_id("wd", tenant, site, ext_path),
        url=url,
        title=title,
        company=company,
        city=loc_raw,
        latitude=lat,
        longitude=lon,
        description=desc or f"{title} — {company} ({loc_raw})",
        source="workday",
        contract_type=_contract_type(info, campaign, title),
    )


def search(
    env: dict[str, str] | None = None,
    *,
    campaign: str = "stage",
    max_details: int = 25,
) -> list[dict]:
    """Interroge les portails Workday CXS configurés dans les bassins cibles."""
    env = env or {}
    if not enabled(env):
        return []
    portals = _portals_for(env, campaign)
    if not portals:
        return []
    queries = STAGE_QUERIES if campaign == "stage" else JOB_QUERIES
    results: list[dict] = []
    seen_paths: set[tuple[str, str]] = set()
    coord_cache: dict = {}
    details_fetched = 0

    for tenant, inst, site, company in portals:
        base_host = f"https://{tenant}.{inst}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
        rate_limited = False
        for q in queries:
            if rate_limited:
                break
            payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q}
            try:
                status, data = public_network.post_json(f"{base_host}/jobs", payload, headers={"User-Agent": UA}, timeout=10)
            except Exception as exc:
                LOG.info("Workday %s/%s erreur: %s", tenant, site, type(exc).__name__)
                continue
            if is_rate_limited(status):
                LOG.warning("Workday %s rate-limited (%s)", tenant, status)
                break
            if status != 200 or not isinstance(data, dict):
                continue
            for jp in data.get("jobPostings") or []:
                if not isinstance(jp, dict):
                    continue
                ext_path = str(jp.get("externalPath") or "").strip()
                title = str(jp.get("title") or "").strip()
                if not ext_path or (tenant, ext_path) in seen_paths or not _pre_matches(title, campaign):
                    continue
                seen_paths.add((tenant, ext_path))
                loc_hint = str(jp.get("locationsText") or "")
                if not _plausible_zone_location(loc_hint):
                    continue
                detail = None
                if details_fetched < max_details:
                    clean_path = ext_path if ext_path.startswith("/") else "/" + ext_path
                    try:
                        d_status, d_data = public_network.get_json(f"{base_host}{clean_path}", headers={"User-Agent": UA}, timeout=10)
                        details_fetched += 1
                        if is_rate_limited(d_status):
                            rate_limited = True
                            break
                        if d_status == 200 and isinstance(d_data, dict):
                            detail = d_data
                    except Exception:
                        pass
                item = normalize_posting(
                    tenant, inst, site, company, jp,
                    campaign=campaign, detail=detail, coord_cache=coord_cache,
                )
                if item:
                    results.append(item)
    return results
