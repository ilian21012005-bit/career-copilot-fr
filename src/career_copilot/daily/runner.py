"""Main daily pipeline orchestrator (`run`, `run_if_due`, summary logging)."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from career_copilot.daily.deps import RECOVERABLE_ERRORS, DailyDeps
from career_copilot.daily.discovery import (
    discover,
    prepare_interview_preps,
    route_public_emails,
    scan_response_radar,
    sync_public_sources,
)
from career_copilot.daily.planner import build, prepare
from career_copilot.daily.state import configure_logger, ran_today, write_state


def _run_sync_phase(
    deps: DailyDeps,
    log: logging.Logger,
    summary: dict[str, Any],
    *,
    cap: int,
    retry_delay: float,
    sleep: Callable[[float], Any],
) -> None:
    discover_fn = deps.discover_fn or (
        lambda lg, c, d, sl, errs: discover(deps, lg, c, d, sl, errs)
    )
    summary.update(discover_fn(log, cap, retry_delay, sleep, summary["errors"]))
    radar_fn = deps.scan_response_radar_fn or (lambda lg: scan_response_radar(deps, lg))
    try:
        summary["response_radar"] = radar_fn(log)
    except RECOVERABLE_ERRORS as exc:
        log.warning("Radar réponses indisponible : %s", exc)
    if not summary.get("alert_offers") and not deps.store.has_alert_history():
        log.warning(
            "Aucune alerte HelloWork traitée jusqu'ici. Vérifie leur réception "
            "dans la boîte mail et la configuration du compte."
        )
    sync_pub_fn = deps.sync_public_sources_fn or (lambda *, log: sync_public_sources(deps, log=log))
    try:
        summary["public_sources"] = sync_pub_fn(log=log)
    except RECOVERABLE_ERRORS as exc:
        log.warning("Sources publiques indisponibles : %s", exc)


def _run_enrichment_phase(deps: DailyDeps, log: logging.Logger, summary: dict[str, Any]) -> None:
    try:
        if deps.jobspy_source.available():
            js = deps.jobspy_source.scrape_batch(dry_run=False, results_wanted=10, hours_old=96)
            js_job = deps.jobspy_source.scrape_batch(
                dry_run=False, results_wanted=8, hours_old=96, campaign="job"
            )
            summary["jobspy_added"] = (js.get("added", 0) or 0) + (js_job.get("added", 0) or 0)
            summary["jobspy_unique"] = (js.get("unique_stage_like", 0) or 0) + (
                js_job.get("unique_stage_like", 0) or 0
            )
            all_js_errors = list(js.get("errors") or []) + list(js_job.get("errors") or [])
            if all_js_errors:
                summary["errors"].extend(f"jobspy: {err}" for err in all_js_errors[:5])
            log.info(
                "JobSpy : %s offres uniques (stage+job), %s nouvelles.",
                summary["jobspy_unique"],
                summary["jobspy_added"],
            )
        else:
            log.info("JobSpy indisponible (python-jobspy non installé).")
    except RECOVERABLE_ERRORS as exc:
        log.exception("JobSpy interrompu : %s", exc)
        summary["errors"].append(f"jobspy: {exc}")

    try:
        deep = deps.partner_deep.enrich_pending(limit=30)
        summary["partner_deep"] = len(deep)
        summary["manual_required"] = sum(1 for r in deep if r.get("manual_required"))
        summary["auto_ready"] = sum(1 for r in deep if r.get("auto_submit"))
        log.info(
            "Analyse partenaire : %s offres (manuel=%s auto=%s).",
            len(deep),
            summary["manual_required"],
            summary["auto_ready"],
        )
    except RECOVERABLE_ERRORS as exc:
        log.exception("Analyse partenaire interrompue : %s", exc)
        summary["errors"].append(f"partner_deep: {exc}")

    try:
        pruned = deps.ats_alive.prune_dead_offers(limit_hw=200, limit_suivi=500, timeout=8.0)
        summary["dead_pruned"] = pruned.get("total_ignored", 0)
        if pruned.get("total_ignored"):
            log.info(
                "Liens morts purgés : %s (hw=%s, suivi=%s).",
                pruned["total_ignored"],
                pruned.get("hw_ignored", 0),
                pruned.get("suivi_ignored", 0),
            )
    except RECOVERABLE_ERRORS as exc:
        log.exception("Purge liens morts interrompue : %s", exc)
        summary["errors"].append(f"prune_dead: {exc}")


def _run_prepare_phase(deps: DailyDeps, log: logging.Logger, summary: dict[str, Any]) -> None:
    prepare_fn = deps.prepare_kits_fn or (lambda: prepare(deps))
    route_fn = deps.route_public_emails_fn or (lambda lg: route_public_emails(deps, lg))
    prep_fn = deps.prepare_interview_preps_fn or (lambda lg: prepare_interview_preps(deps, lg))
    try:
        made = prepare_fn()
        summary["kits"] = len(made)
        lm_limit = max(0, min(int(os.getenv("HW_LOCAL_LM_LIMIT", "10") or "10"), 50))
        if lm_limit > 0:
            pending_before = deps.lm_ai.pending(limit=200)
            lm_reports = deps.lm_ai.process_pending_local(limit=lm_limit)
            summary["lm_generated"] = sum(1 for r in lm_reports if r.get("ok"))
            summary["lm_failed_ids"] = [
                str(r["id"]) for r in lm_reports if not r.get("ok") and r.get("id")
            ]
            summary["lm_failed"] = len(summary["lm_failed_ids"])
            attempted_ids = {str(r["id"]) for r in lm_reports if r.get("id")}
            summary["lm_deferred_ids"] = [
                str(item["id"])
                for item in pending_before
                if item.get("id") and str(item["id"]) not in attempted_ids
            ]
            if summary["lm_failed"]:
                summary["errors"].append(
                    f"lettres IA: {summary['lm_failed']} dossier(s) à reprendre"
                )
        else:
            summary["lm_generated"] = 0
            summary["lm_failed"] = 0
            summary["lm_failed_ids"] = []
            summary["lm_deferred_ids"] = []
        summary["lm_pending"] = len(deps.lm_ai.pending(limit=50))
        ready_path = deps.ready_queue.export_json()
        ready_data = json.loads(ready_path.read_text(encoding="utf-8"))
        summary["ready_to_click"] = ready_data.get("count", 0)
        summary["content_validation_pending"] = sum(
            bool(item.get("automatic_content_blockers")) for item in ready_data.get("offers", [])
        )
        summary["public_emails_queued"] = route_fn(log)
        summary["interview_preps"] = prep_fn(log)
        stale_flag = deps.data_dir() / "hellowork" / "lm-worker-needed.flag"
        if stale_flag.exists():
            stale_flag.unlink()
    except RECOVERABLE_ERRORS as exc:
        log.exception("Préparation des dossiers interrompue : %s", exc)
        summary["errors"].append(f"dossiers: {exc}")


def log_summary(log: logging.Logger, summary: dict[str, Any]) -> None:
    log.info(
        "Cycle terminé : %s mail(s), %s offre(s) d'alerte, %s nouvelle(s), "
        "%s dans la file, %s dossier(s), %s erreur(s).",
        summary.get("mails", 0),
        summary.get("alert_offers", 0),
        summary.get("new_offers", 0),
        summary.get("plan", 0),
        summary.get("kits", 0),
        len(summary.get("errors", [])),
    )
    if summary.get("content_validation_pending"):
        log.warning(
            "%s dossier(s) techniquement prêts restent à contrôler avant envoi automatique.",
            summary["content_validation_pending"],
        )
    if summary.get("errors"):
        for error in summary["errors"][:5]:
            log.warning("  erreur : %s", error)


def run(
    deps: DailyDeps,
    *,
    sync: bool = True,
    prepare_flag: bool = True,
    max_offers: int | None = None,
    target: int | None = None,
    log: logging.Logger | None = None,
    retry_delay: float = 3.0,
    sleep: Callable[[float], Any] = time.sleep,
    record_state: bool = True,
    auto_submit: bool = False,
) -> dict[str, Any]:
    """Execute the full idempotent daily pipeline and return a serializable summary."""
    active_log = log or (
        deps.logger_fn("hellowork.daily") if deps.logger_fn else configure_logger(deps)
    )
    started = datetime.now().astimezone()
    cap = min(max_offers or deps.profile.DAILY_MAX, deps.profile.DAILY_MAX)
    summary: dict[str, Any] = {
        "started_at": started.isoformat(timespec="seconds"),
        "mails": 0,
        "alert_offers": 0,
        "linkedin_alert_links": 0,
        "new_offers": 0,
        "errors": [],
        "plan": 0,
        "kits": 0,
    }
    deps.store.init()
    active_log.info("Cycle quotidien démarré (cap %s offres).", cap)

    if sync:
        _run_sync_phase(deps, active_log, summary, cap=cap, retry_delay=retry_delay, sleep=sleep)
    else:
        active_log.info("Découverte ignorée (--no-sync).")

    _run_enrichment_phase(deps, active_log, summary)

    build_fn = deps.build_fn or (lambda t, c: build(deps, t, c))
    try:
        chosen = build_fn(target, cap)
    except RECOVERABLE_ERRORS as exc:
        active_log.exception("Construction de la file impossible : %s", exc)
        summary["errors"].append(f"plan: {exc}")
        chosen = []
    summary["plan"] = len(chosen)

    if prepare_flag and chosen:
        _run_prepare_phase(deps, active_log, summary)

    try:
        paths = deps.report.build()
        summary["report"] = str(paths.get("plan", ""))
        summary["report_html"] = str(paths.get("html", ""))
    except RECOVERABLE_ERRORS as exc:
        active_log.exception("Rapport impossible : %s", exc)
        summary["errors"].append(f"rapport: {exc}")

    summary["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    if record_state:
        writer = deps.write_state_fn or (
            lambda data, *, auto_submit=False: write_state(deps, data, auto_submit=auto_submit)
        )
        writer(summary, auto_submit=auto_submit)
    log_summary(active_log, summary)
    return summary


def run_if_due(deps: DailyDeps, *, auto_submit: bool = False, **kwargs: Any) -> dict[str, Any]:
    """Skip execution if a successful run already completed on the current slot."""
    check_fn = deps.ran_today_fn or (
        lambda *, auto_submit=False: ran_today(deps, auto_submit=auto_submit)
    )
    if check_fn(auto_submit=auto_submit):
        return {"skipped": True, "reason": "déjà exécuté aujourd'hui"}
    if deps.run_fn is not None:
        return deps.run_fn(auto_submit=auto_submit, **kwargs)
    prepare_flag = kwargs.pop("prepare", True)
    return run(deps, prepare_flag=prepare_flag, auto_submit=auto_submit, **kwargs)
