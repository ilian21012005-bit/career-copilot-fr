"""Excel projection reconciliation, receipt reconciliation, and daily/apply CLI entrypoints."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any

from career_copilot.hellowork_cli import apply_flow
from career_copilot.hellowork_cli.deps import (
    LOG,
    CliDeps,
    find_offer,
    has_blocking_errors,
    stats_line,
)
from career_copilot.submission.models import BROWSER_ERRORS


def reconcile_excel_projections(deps: CliDeps, log: Callable[[str], None]) -> bool:
    ok = True
    for row in deps.store.pending_excel_projections():
        oid = row["id"]
        applied_at = row["projection_applied_at"]
        try:
            campaign = deps.scoring.campaign_of(deps.offers.from_row(row))
            deps.suivi.record_application(
                row["url"],
                campaign=campaign,
                title=row["title"],
                company=row["company"],
                city=row["city"] or "",
                source=row["apply_mode"] or "hellowork",
                notes=row["projection_note"] or "",
                contract_type=row["contract"]
                or ("Stage" if campaign == "stage" else "Job étudiant"),
                applied_at=applied_at,
                lookup_distance=False,
            )
            deps.store.finish_excel_projection(oid, applied_at)
        except (OSError, ValueError, RuntimeError) as exc:
            ok = False
            log(f"{oid} — suivi Excel à réconcilier : {type(exc).__name__}")
    return ok


def reconcile_pending_hellowork(deps: CliDeps, context: Any, log: Callable[[str], None]) -> int:
    """Reconcile `submission_pending`/`submission_unknown` offers via `mes-candidatures.html`."""
    pending_rows = [
        *deps.store.list_offers(status="submission_pending", min_score=0, limit=100),
        *deps.store.list_offers(status="submission_unknown", min_score=0, limit=100),
    ]
    if not pending_rows:
        return 0
    page = context.new_page()
    reconciled = 0
    try:
        receipts = deps.submit_handler.list_hellowork_receipts(page, max_pages=2)
    except BROWSER_ERRORS as exc:
        log(f"Réconciliation espace candidat indisponible : {type(exc).__name__}: {exc}")
        return 0
    finally:
        try:
            page.close()
        except BROWSER_ERRORS as exc:
            LOG.debug("Fermeture page réconciliation ignorée : %s", exc)
    if not receipts:
        return 0
    for row in pending_rows:
        oid = str(row["id"] or "")
        num_id = deps.submit_handler._hellowork_numeric_id(str(row["url"] or ""), oid)
        rec = receipts.get(num_id)
        if not rec:
            continue
        r_status = rec.get("status")
        note = f"{rec.get('url') or ''} — {rec.get('message') or ''}".strip(" —")
        if r_status == "submitted":
            reference = str(rec.get("application_id") or rec.get("url") or "")
            deps.store.confirm(
                oid,
                channel="hellowork-playwright",
                note=note,
                proof_kind="ats_receipt" if reference else "",
                proof_reference=reference,
                project_to_excel=True,
            )
            log(
                f"{oid} ({row['company']}) — confirmée dans l'espace candidat ({rec.get('message')})."
            )
            reconciled += 1
        elif r_status == "to_finish":
            deps.store.set_status(oid, "to_finish", note)
            deps.store.mark_plan(oid, "to_finish")
            log(f"{oid} ({row['company']}) — à finaliser sur le site recruteur ({note}).")
            reconciled += 1
        elif r_status == "pending" and row["status"] != "submission_pending":
            deps.store.mark_submission_pending(oid, note)
            reconciled += 1
    return reconciled


def _active_apply_rows(deps: CliDeps) -> Callable[..., bool]:
    if deps.apply_rows_fn is not None:
        return deps.apply_rows_fn
    return lambda rows, **kw: apply_flow.apply_rows(deps, rows, **kw)


def _run_daily_auto_submit(
    deps: CliDeps, result: dict[str, Any], run_apply: Callable[..., bool], *, apply_ok: bool
) -> bool:
    planned = result.get("plan") and not has_blocking_errors(result)
    rows = deps.store.plan_for() if planned else []
    if not (planned or deps.store.has_unreconciled_submissions()):
        return apply_ok
    try:
        before_today = int(deps.store.stats().get("aujourd'hui", 0) or 0)
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        before_today = 0
    try:
        apply_kwargs: dict[str, Any] = {
            "send": True,
            "headless": True,
            "accept_consent": True,
            "enforce_eligibility": True,
            "blocked_offer_ids": set(result.get("lm_failed_ids") or []),
        }
        if result.get("lm_deferred_ids"):
            apply_kwargs["deferred_offer_ids"] = set(result.get("lm_deferred_ids") or [])
        apply_ok = run_apply(rows, **apply_kwargs) and apply_ok
    except (*BROWSER_ERRORS, sqlite3.Error) as exc:
        apply_ok = False
        result["auto_fatal_error"] = True
        deps.daily.logger().exception("Envoi automatique interrompu : %s", exc)
    try:
        after_today = int(deps.store.stats().get("aujourd'hui", 0) or 0)
        result["auto_submitted"] = max(0, after_today - before_today)
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        result.setdefault("auto_submitted", 0)
    try:
        deps.report.build()
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        deps.daily.logger().warning("Rapport quotidien non régénéré après envoi : %s", exc)
    return apply_ok


def cmd_daily(deps: CliDeps, args: Any) -> int:
    deps.store.init()
    projection_ok = reconcile_excel_projections(deps, deps.daily.logger().warning)
    result = (
        deps.daily.run_if_due(
            sync=not args.no_sync,
            max_offers=args.max,
            auto_submit=args.auto_submit,
            record_state=not args.auto_submit,
        )
        if args.if_due
        else deps.daily.run(
            sync=not args.no_sync,
            max_offers=args.max,
            record_state=not args.auto_submit,
        )
    )
    run_apply = _active_apply_rows(deps)
    if result.get("skipped"):
        print(f"Cycle ignoré : {result.get('reason')}.")
        if args.auto_submit and deps.store.has_unreconciled_submissions():
            return (
                0
                if run_apply([], send=True, headless=True, accept_consent=False) and projection_ok
                else 1
            )
        return 0 if projection_ok else 1
    print(
        f"Cycle terminé : {result.get('mails', 0)} mail(s), "
        f"{result.get('alert_offers', 0)} offre(s) d'alerte, "
        f"{result.get('new_offers', 0)} nouvelle(s), "
        f"{result.get('plan', 0)} dans la file, {result.get('kits', 0)} dossier(s)."
    )
    if result.get("errors"):
        print("Erreurs :")
        for error in result["errors"][:8]:
            print(f"  - {error}")
    apply_ok = projection_ok
    if result.get("plan"):
        print(f"File cliquable : {result.get('report', '')}")
        print(deps.stats_line_fn() if deps.stats_line_fn is not None else stats_line(deps))
    else:
        print("Aucune offre pertinente aujourd'hui : rien n'est inventé pour remplir le quota.")
    if args.auto_submit:
        apply_ok = _run_daily_auto_submit(deps, result, run_apply, apply_ok=apply_ok)
        if not projection_ok:
            result["auto_fatal_error"] = True
        if not apply_ok:
            result.setdefault("errors", []).append("envoi automatique incomplet ou à vérifier")
        result["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        deps.daily._write_state(result, auto_submit=True)
    return 1 if has_blocking_errors(result) or not apply_ok else 0


def cmd_apply(deps: CliDeps, args: Any) -> int:
    if args.daily:
        if args.offer_id:
            print("Donne soit un identifiant, soit --daily, pas les deux.")
            return 2
        rows = deps.store.plan_for()
    else:
        if not args.offer_id:
            print("Donne un identifiant d'offre ou utilise --daily.")
            return 2
        row = find_offer(deps, args.offer_id)
        if not row:
            print(f"Offre inconnue : {args.offer_id}")
            return 1
        rows = [row]
    if not rows:
        print("Aucune offre à traiter.")
        return 0
    apply_ok = _active_apply_rows(deps)(
        rows,
        send=args.send,
        headless=args.headless,
        accept_consent=args.accept_consent,
        enforce_eligibility=args.daily,
    )
    deps.report.build()
    return 0 if apply_ok else 1
