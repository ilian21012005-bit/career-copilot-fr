"""Human-in-the-loop offer importer from URL, pasted text, or 1-click bookmarklet."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from career_copilot.sources.deps import SourcesDeps

LOG = logging.getLogger("career_copilot.sources.importer")

_FETCH_ERRORS = (OSError, RuntimeError, TimeoutError, ValueError)


def infer_imported_contract(
    raw_contract: str,
    raw_title: str,
    raw_text: str,
    cfg: Any,
    fold_fn: Callable[[str], str],
) -> str:
    """Infer normalized contract type for a manually imported offer."""
    if raw_contract not in ("stage", "alternance", "job", "job_etudiant"):
        folded_all = fold_fn(f"{raw_title} {raw_text[:600]}")
        if any(k in folded_all for k in ("alternance", "apprentissage", "apprenti", "contrat pro")):
            return "Alternance"
        if any(k in folded_all for k in ("stage", "stagiaire", "intern", "internship")):
            return "Stage"
        if cfg.preset_id == "student_job_only" or cfg.contracts == ("job",):
            return "job_etudiant"
        if cfg.target_contract == "alternance":
            return "Alternance"
        return "job_etudiant" if cfg.target_contract == "job" else "Stage"
    if raw_contract == "job":
        return "job_etudiant"
    if raw_contract == "alternance":
        return "Alternance"
    if raw_contract == "stage":
        return "Stage"
    return raw_contract


def _fetch_remote_offer_text(
    raw_url: str,
    raw_title: str,
    deps: SourcesDeps,
) -> tuple[str, str]:
    try:
        status, body = deps.public_network.fetch(
            raw_url,
            headers={"User-Agent": deps.source_common.UA, "Accept": "text/html"},
            timeout=10,
            max_bytes=1 * 1024 * 1024,
        )
        if status == 200 and body:
            html_str = body.decode("utf-8", errors="replace")
            title = raw_title
            if not title:
                match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_str)
                if match:
                    title = deps.source_common.strip_html(match.group(1), limit=180)
            text = deps.source_common.strip_html(html_str, limit=6000)
            return title, text
    except _FETCH_ERRORS as exc:
        LOG.debug("Récupération distante ignorée (%s): %s", raw_url, exc)
    return raw_title, ""


def _resolve_offer_geo(
    offer: Any,
    raw_city: str,
    cfg: Any,
    deps: SourcesDeps,
    *,
    use_network: bool,
) -> None:
    def _geocoder(city: str, dept: str = "") -> tuple[float, float] | None:
        direct = deps.geo.geocode(city, dept, network=False)
        if direct:
            return direct
        muni = deps.geo.geocode_municipality(city, network=use_network)
        if muni and muni.get("lat") is not None:
            return (float(muni["lat"]), float(muni["lon"]))
        return None

    deps.geo.resolve(offer, geocoder=_geocoder)
    if offer.latitude is None and cfg.zones:
        z0 = cfg.zones[0]
        if not raw_city or deps.filters._fold(raw_city) == deps.filters._fold(
            str(z0.get("name") or "")
        ):
            offer.latitude = float(z0["lat"])
            offer.longitude = float(z0["lon"])
            deps.geo.resolve(offer, geocoder=lambda _c, _d="": (offer.latitude, offer.longitude))


def import_offer_from_url_or_text(payload: dict[str, Any], deps: SourcesDeps) -> dict[str, Any]:
    """Import, geocode, validate, and score an offer submitted via URL, text, or bookmarklet."""
    if not isinstance(payload, dict):
        raise ValueError("Les données de l'offre doivent être un objet JSON.")

    raw_url = str(payload.get("url") or "").strip()
    raw_title = str(payload.get("title") or "").strip()
    raw_company = str(payload.get("company") or "").strip()
    raw_city = str(payload.get("city") or "").strip()
    raw_contract = str(payload.get("contract") or "").strip().lower()
    raw_text = str(payload.get("text") or payload.get("description") or "").strip()

    if raw_url:
        if len(raw_url) > 2048:
            raise ValueError("L'URL de l'offre est trop longue.")
        scheme, host, _port, _path = deps.public_network.target(raw_url)
        if scheme not in ("http", "https") or not host:
            raise ValueError("Une URL HTTP/HTTPS publique valide est requise.")

    if raw_url and not raw_text and bool(payload.get("fetch_remote", False)):
        raw_title, raw_text = _fetch_remote_offer_text(raw_url, raw_title, deps)

    if not raw_title and raw_text:
        first_line = next((ln.strip() for ln in raw_text.splitlines() if len(ln.strip()) >= 4), "")
        raw_title = first_line[:140]
    if not raw_title:
        raise ValueError("Le titre de l'offre (ou le texte de l'annonce) est requis.")

    if not raw_city and (raw_title or raw_text):
        inferred_city, _dept = deps.source_common.infer_fr_city(raw_title, raw_text)
        if inferred_city:
            raw_city = inferred_city

    cfg = deps.candidate_config.get_profile()
    if not raw_city and cfg.zones:
        raw_city = str(cfg.zones[0].get("name") or "")

    contract = infer_imported_contract(raw_contract, raw_title, raw_text, cfg, deps.filters._fold)
    company = raw_company or "Entreprise"
    oid = deps.source_common.stable_id("manual", raw_url or f"{raw_title}|{company}|{raw_city}")
    offer = deps.hw_offers.Offer(
        id=oid,
        url=raw_url or f"https://manual.local/offers/{oid}",
        title=raw_title[:200],
        company=company[:140],
        city=raw_city[:120],
        department=deps.source_common.extract_department(raw_city),
        contract=contract,
        posted_at=datetime.now().astimezone().strftime("%Y-%m-%d"),
        description=raw_text[:8000] or raw_title,
        missions=raw_text[:4000],
        apply_mode="manual",
    )

    _resolve_offer_geo(offer, raw_city, cfg, deps, use_network=bool(payload.get("network", False)))

    score_res = deps.scoring.evaluate(offer)
    deps.hw_store.init()
    deps.hw_store.save_offer(offer, score_res)
    return {
        "ok": True,
        "offer": {
            "id": offer.id,
            "url": offer.url,
            "title": offer.title,
            "company": offer.company,
            "city": offer.city,
            "contract": offer.contract,
            "campaign": deps.scoring.campaign_of(offer),
            "zone": score_res.zone,
            "distance_km": score_res.distance_km,
            "location_status": score_res.location_status,
            "score": score_res.value,
            "verdict": score_res.verdict,
            "rejected": score_res.rejected,
            "reject_reason": score_res.reject_reason,
            "parts": score_res.parts,
            "reasons": score_res.reasons,
            "matched": score_res.matched,
            "gaps": score_res.gaps,
        },
    }
