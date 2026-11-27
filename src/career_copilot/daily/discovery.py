"""Offer discovery, public ATS sync, response radar, email routing, and interview prep."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from typing import Any

from career_copilot.daily.deps import RECOVERABLE_ERRORS, DailyDeps
from career_copilot.daily.state import configure_logger, retry


def scan_response_radar(deps: DailyDeps, log: logging.Logger) -> dict[str, int]:
    """Scan critical recruiter replies/invitations in read-only mode via `response_radar`."""
    env = deps.load_env()
    password = env.get("GMAIL_APP_PASSWORD", "")
    if not password:
        return {"scanned": 0, "action_required": 0, "notified": 0}
    response_radar = importlib.import_module("response_radar")

    radar = response_radar.scan_and_notify(password, days=14, notify=True)
    result = {
        "scanned": int(radar.get("scanned", 0) or 0),
        "action_required": int(radar.get("action_required", 0) or 0),
        "notified": int(radar.get("notified", 0) or 0),
    }
    if result["action_required"]:
        log.info(
            "Radar réponses : %s action(s) requise(s) détectée(s), %s notifiée(s).",
            result["action_required"],
            result["notified"],
        )
    return result


def tag_student_job_if_matched(deps: DailyDeps, offer: Any) -> bool:
    """Tag a non-IT/non-stage HelloWork alert as `job_etudiant` when it matches student criteria."""
    if deps.scoring.campaign_of(offer) == "job":
        return True
    header_f = deps.fold(f"{offer.title} {offer.contract}")
    if "stage" in header_f or any(word in header_f for word in ("alternance", "apprentissage")):
        return False
    if deps.filters.stage_relevant(offer.title, "hellowork"):
        return False
    matched = deps.filters.keep(
        {
            "title": offer.title,
            "text": f"{offer.title} {offer.missions} {offer.description}",
            "contract_type": offer.contract,
            "source": offer.apply_mode or "hellowork",
            "latitude": offer.latitude,
            "longitude": offer.longitude,
            "origin_lat": 48.6994,
            "origin_lon": 2.2406,
        },
        "job",
    )
    if matched:
        offer.contract = "job_etudiant"
    return bool(matched)


def discover(
    deps: DailyDeps,
    log: logging.Logger,
    cap: int,
    delay: float,
    sleep: Callable[[float], Any],
    errors: list[str],
) -> dict[str, int]:
    """Read mails and alert URLs into new scored offers without aborting on partial failures."""
    env = deps.load_env()
    password = env.get("GMAIL_APP_PASSWORD", "")
    if not password:
        log.warning("GMAIL_APP_PASSWORD absent : découverte ignorée.")
        errors.append("mails: mot de passe absent")
        return {}

    result: dict[str, int] = {"mails": 0, "alert_offers": 0, "new_offers": 0}
    try:
        mails = retry(
            lambda: deps.alerts.import_all(password, verbose=False),
            log,
            "lecture des mails",
            delay,
            sleep,
        )
        result["mails"] = len(mails)
        log.info("%s confirmation(s) traitée(s).", len(mails))
    except RECOVERABLE_ERRORS as exc:
        log.error("Lecture des confirmations impossible : %s", exc)
        errors.append(f"mails: {exc}")

    try:
        urls = retry(
            lambda: deps.alerts.alert_urls(password, verbose=False, limit=cap, errors=errors),
            log,
            "alertes",
            delay,
            sleep,
        )
    except RECOVERABLE_ERRORS as exc:
        log.error("Lecture des alertes impossible : %s", exc)
        errors.append(f"alertes: {exc}")
        return result

    result["alert_offers"] = len(urls)
    log.info("%s offre(s) dans les alertes.", len(urls))
    tag_fn = deps.tag_student_job_fn or (lambda off: tag_student_job_if_matched(deps, off))
    added = 0
    for url in urls:
        offer_id = deps.offers.offer_id(url)
        try:
            offer = retry(
                lambda url=url: deps.offers.read(url),
                log,
                f"fiche {url}",
                delay,
                sleep,
                attempts=2,
            )
        except RECOVERABLE_ERRORS as exc:
            log.error("Fiche illisible %s : %s", url, exc)
            errors.append(f"fiche {url}: {exc}")
            deps.store.retry_alert_offer(offer_id, str(exc))
            continue
        try:
            deps.geo.resolve(offer)
            tag_fn(offer)
            resultat = deps.scoring.evaluate(offer)
            existed = deps.store.get(offer.id) is not None
            deps.store.save_offer(offer, resultat)
            deps.store.resolve_alert_offer(offer.id)
            if not existed:
                added += 1
            log.info(
                "[%3d] %s — %s · %s · %s",
                resultat.value,
                offer.company,
                offer.title[:60],
                f"{offer.zone} {offer.distance_km:.0f} km" if offer.zone else "à vérifier",
                resultat.verdict,
            )
        except RECOVERABLE_ERRORS as exc:
            log.error("Traitement impossible %s : %s", url, exc)
            errors.append(f"offre {url}: {exc}")
            deps.store.retry_alert_offer(offer_id, str(exc))

    result["new_offers"] = added
    log.info("%s nouvelle(s) offre(s) enregistrée(s).", added)
    return result


def sync_public_sources(
    deps: DailyDeps,
    env: dict[str, str] | None = None,
    log: logging.Logger | None = None,
) -> dict[str, int]:
    """Synchronize public internship & student job ATS boards."""
    ats_public = importlib.import_module("ats_public")
    csp_offres = importlib.import_module("csp_offres")
    recruitee = importlib.import_module("recruitee")
    smartrecruiters = importlib.import_module("smartrecruiters")
    source_common = importlib.import_module("source_common")
    teamtailor = importlib.import_module("teamtailor")
    workday = importlib.import_module("workday")

    cfg = env if env is not None else deps.load_env()
    active_log = log or (
        deps.logger_fn("hellowork.daily") if deps.logger_fn else configure_logger(deps)
    )
    counts = {
        "smartrecruiters": 0,
        "workday": 0,
        "csp": 0,
        "teamtailor": 0,
        "recruitee": 0,
        "ats_public": 0,
    }
    for key, mod in (
        ("smartrecruiters", smartrecruiters),
        ("workday", workday),
        ("csp", csp_offres),
        ("teamtailor", teamtailor),
        ("recruitee", recruitee),
        ("ats_public", ats_public),
    ):
        if not mod.enabled(cfg):
            continue
        try:
            found = mod.search(cfg, campaign="stage")
            added = source_common.ingest_stage_offers_to_store(found)
            counts[key] = added
            active_log.info("%s : %s offres récupérées, %s ajoutées.", key, len(found), added)
        except RECOVERABLE_ERRORS as exc:
            active_log.warning("%s indisponible : %s", key, type(exc).__name__)
    counts["smartrecruiters_job"] = 0
    if smartrecruiters.enabled(cfg):
        try:
            found = smartrecruiters.search(cfg, campaign="job")
            counts["smartrecruiters_job"] = source_common.ingest_job_offers_to_store(found)
            active_log.info(
                "smartrecruiters job : %s offres récupérées, %s ajoutées.",
                len(found),
                counts["smartrecruiters_job"],
            )
        except RECOVERABLE_ERRORS as exc:
            active_log.warning("smartrecruiters job indisponible : %s", type(exc).__name__)
    return counts


def _build_public_email_pool(deps: DailyDeps) -> list[Any]:
    seen_ids: set[str] = set()
    pool: list[Any] = []
    for row in [
        *deps.store.plan_for(),
        *deps.store.list_offers(
            min_score=deps.profile.MIN_SCORE,
            location="in_zone",
            limit=200,
            eligible=True,
            exclude_capabilities=("auto_hellowork", "dead_partner"),
        ),
    ]:
        row_id = str(row["id"] or "")
        if not row_id or row_id in seen_ids:
            continue
        seen_ids.add(row_id)
        pool.append(row)
    return pool


def route_public_emails(deps: DailyDeps, log: logging.Logger) -> int:
    """Queue public recruiter emails for non-auto eligible offers."""
    application_contact = importlib.import_module("application_contact")

    queued = 0
    auto_kits = 0
    max_auto_kits = 10
    deps.mail_store.init()
    for row in _build_public_email_pool(deps):
        oid = str(row["id"] or "")
        cap = str(row["apply_capability"] or "")
        if (
            not oid
            or cap in ("auto_hellowork", "dead_partner")
            or row["status"] not in ("new", "shortlist", "prepared")
        ):
            continue
        candidate = deps.assist_apply.extract_public_recruiter_email(
            row["description"] or "",
            row["missions"] or "",
            row["profile"] or "",
            row["notes"] or "",
        )
        if not candidate:
            continue
        combined = "\n".join(
            str(row[key] or "") for key in ("description", "missions", "profile", "notes")
        )
        email = application_contact.recipient(combined)
        if not email:
            continue
        offer_obj = deps.offers.from_row(row)
        campaign = deps.scoring.campaign_of(offer_obj)
        key = f"{email.lower()}|{campaign}|{deps.filters._fold(offer_obj.title or '')}"
        if deps.mail_store.get_target(key) is not None:
            continue
        if campaign == "stage" and auto_kits < max_auto_kits:
            saved_kit = deps.store.kit_for(oid)
            if not saved_kit or not deps.store.kit_is_current(oid, saved_kit):
                try:
                    if offer_obj.latitude is None or offer_obj.longitude is None:
                        deps.geo.resolve(offer_obj)
                    result = deps.scoring.evaluate(offer_obj)
                    files = deps.kit.build(offer_obj, result)
                    deps.store.save_kit(
                        oid, files["subject"], files["letter"], files["cv"], files["dossier"]
                    )
                    deps.store.set_status(oid, "prepared")
                    auto_kits += 1
                except ValueError as exc:
                    log.warning("Kit auto ignoré pour %s : %s", oid, exc)
        if not deps.mail_store.is_queued(key):
            deps.mail_store.queue_email(
                {
                    "key": key,
                    "campaign": campaign,
                    "email": email,
                    "name": offer_obj.company or "",
                    "title": offer_obj.title or "",
                    "url": str(row["partner_url"] or offer_obj.url or ""),
                    "hw_offer_id": oid,
                    "city": offer_obj.city or "",
                    "source": str(offer_obj.apply_mode or "hellowork"),
                    "description": offer_obj.description or "",
                }
            )
            queued += 1
    if queued:
        log.info("File e-mail public : %s offre(s) non-HelloWork routée(s).", queued)
    return queued


def prepare_interview_preps(deps: DailyDeps, log: logging.Logger) -> int:
    """Create deterministic interview prep sheets for replied/interview offers."""
    created = 0
    for status in ("interview", "replied"):
        for row in deps.store.list_offers(status=status, min_score=0, limit=50):
            url = str(row["url"] or "").strip()
            if not url or deps.interview_prep.load_prep(url) is not None:
                continue
            prep = deps.interview_prep.generate_deterministic_prep(dict(row))
            deps.interview_prep.save_prep(url, prep)
            created += 1
    if created:
        log.info("Fiches entretien préparées : %s.", created)
    return created
