"""Playwright per-row application preparation, guard checks, submission, and outcome persistence."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from career_copilot.hellowork_cli.deps import (
    AUTO_SUBMIT_CAPABILITY,
    LOG,
    CliDeps,
    alert_hw_session_once,
    has_auto_submit_capability,
    resolve_submit_cap,
    stage_cv_is_valid,
)
from career_copilot.submission.models import BROWSER_ERRORS

_TERMINAL_STATUSES = frozenset(
    {
        "applied",
        "to_finish",
        "replied",
        "interview",
        "ignored",
        "submission_unknown",
        "submission_pending",
    }
)
_SESSION_ALERT_KEYWORDS = ("captcha", "cloudflare", "connexion", "connecter", "session")


def _close_playwright_session(playwright: Any, context: Any) -> None:
    try:
        context.close()
    finally:
        try:
            playwright.stop()
        except BROWSER_ERRORS as exc:
            LOG.debug("Arrêt Playwright ignoré : %s", exc)


def _validate_and_load_kit(
    deps: CliDeps,
    row: Any,
    *,
    send: bool,
    enforce_eligibility: bool,
    blocked_ids: set[str],
    deferred_ids: set[str],
    log: Callable[[str], None],
) -> tuple[str, dict[str, Any] | None]:
    """Validate offer eligibility and kit freshness. Returns `(action, bundle)`."""
    offer_id = row["id"]
    if str(offer_id) in blocked_ids:
        log(f"{offer_id} — lettre IA non validée ce cycle ; candidature reportée.")
        return "fail", None
    if str(offer_id) in deferred_ids:
        log(
            f"{offer_id} — en file d'attente IA anti-rafale ; candidature reportée au prochain créneau."
        )
        return "skip", None
    fresh_row = deps.store.get(offer_id)
    if fresh_row is None:
        log(f"{offer_id} — offre supprimée du suivi, ignorée.")
        return "skip", None
    if deps.store.has_application(offer_id) or fresh_row["status"] in _TERMINAL_STATUSES:
        log(f"{offer_id} — déjà traité, ignoré.")
        return "skip", None
    offer_obj = (
        deps.offer_from_row_fn(fresh_row)
        if deps.offer_from_row_fn is not None
        else deps.offers.from_row(fresh_row)
    )
    campaign = deps.scoring.campaign_of(offer_obj)
    if enforce_eligibility:
        if not has_auto_submit_capability(fresh_row):
            log(
                f"{offer_id} — capacité d'envoi automatique non confirmée ; conservée pour traitement manuel."
            )
            return "skip", None
        current_score = deps.scoring.evaluate(offer_obj)
        if not deps.scoring.is_eligible_for_plan(
            current_score, AUTO_SUBMIT_CAPABILITY, campaign=campaign
        ):
            log(
                f"{offer_id} — offre non éligible aujourd'hui ({current_score.value}/100), ignorée."
            )
            return "skip", None
    saved = deps.store.kit_for(offer_id)
    if saved and not deps.store.kit_is_current(offer_id, saved):
        log(
            f"{offer_id} — dossier périmé après modification de l'offre ; préparation et relecture nécessaires."
        )
        return "fail", None
    if not saved:
        result = deps.scoring.evaluate(offer_obj)
        files = deps.kit.build(offer_obj, result)
        deps.store.save_kit(
            offer_id, files["subject"], files["letter"], files["cv"], files["dossier"]
        )
        saved = deps.store.kit_for(offer_id)
    cv_path = Path(saved["cv_path"]) if saved and saved["cv_path"] else None
    letter_data = deps.offer_letters.load(fresh_row["url"]) or {}
    letter_text = str(letter_data.get("letter") or "")
    if not cv_path or not cv_path.is_file() or not letter_text.strip():
        log(f"{offer_id} — CV ou lettre manquant ; aucune candidature envoyée.")
        deps.store.event("submission_blocked", offer_id, "CV ou lettre manquant")
        return "fail", None
    if send and enforce_eligibility and not deps.offer_letters.validation_is_current(letter_data):
        log(f"{offer_id} — contrôle de lettre absent ou périmé ; candidature reportée.")
        deps.store.event("submission_blocked", offer_id, "contrôle lettre absent ou périmé")
        return "fail", None
    if send and enforce_eligibility and not deps.store.kit_documents_current(saved, letter_text):
        log(f"{offer_id} — dossier ou profil modifié ou sans empreinte ; candidature reportée.")
        deps.store.event("submission_blocked", offer_id, "documents ou profil non vérifiés")
        return "fail", None
    cv_valid_fn = deps.stage_cv_is_valid_fn or stage_cv_is_valid
    if send and not cv_valid_fn(fresh_row, cv_path):
        log(f"{offer_id} — CV de stage personnalisé absent ou invalide ; envoi bloqué.")
        deps.store.event("submission_blocked", offer_id, "CV stage personnalisé absent/invalide")
        return "fail", None
    return "ready", {
        "row": fresh_row,
        "offer_id": offer_id,
        "campaign": campaign,
        "saved": saved,
        "cv_path": cv_path,
        "letter_text": letter_text,
    }


def _record_submit_outcome(
    deps: CliDeps,
    offer_id: str,
    result: Any,
    *,
    send: bool,
    held: bool,
) -> tuple[bool, bool, bool]:
    """Persist submit outcome. Returns `(row_ok, submitted_inc, should_stop_session)`."""
    row_ok = result.status in ("submitted", "dry_run", "expired", "to_finish", "unsupported")
    if result.submitted:
        reference = str(result.application_id or result.receipt_url or "")
        deps.store.confirm(
            offer_id,
            channel="hellowork-playwright",
            note=result.confirmation,
            proof_kind="ats_receipt" if reference else "",
            proof_reference=reference,
            project_to_excel=True,
        )
        return row_ok, True, False
    is_session_issue = result.status in ("not_logged_in", "session_expired", "login_required") or (
        result.status == "blocked"
        and any(w in (result.detail or "").lower() for w in _SESSION_ALERT_KEYWORDS)
    )
    if is_session_issue:
        if deps.alert_hw_session_once_fn is not None:
            deps.alert_hw_session_once_fn(result.status, result.detail or "")
        else:
            alert_hw_session_once(deps, result.status, result.detail or "")
        deps.store.event("submission_" + result.status, offer_id, result.detail)
        stop = result.status in ("not_logged_in", "session_expired", "login_required")
        return row_ok, False, stop
    if result.status == "unknown":
        deps.store.mark_submission_unknown(offer_id, result.detail)
    elif result.status == "pending":
        deps.store.mark_submission_pending(
            offer_id, result.receipt_url + " — " + result.confirmation
        )
    elif result.status in ("to_finish", "unsupported"):
        deps.store.set_status(offer_id, "to_finish", result.receipt_url or result.detail)
        deps.store.mark_plan(offer_id, "to_finish")
        deps.store.event(
            "submission_" + result.status, offer_id, result.detail or result.confirmation
        )
    elif result.status == "expired":
        if send:
            deps.store.skip(offer_id, result.detail)
    elif result.status != "dry_run":
        row_ok = False
        if held:
            deps.store.mark_submission_unknown(offer_id, result.detail)
        deps.store.event(
            "submission_" + result.status, offer_id, result.detail or result.confirmation
        )
    return row_ok, False, False


def _submit_prepared_bundle(
    deps: CliDeps,
    context: Any,
    bundle: dict[str, Any],
    *,
    send: bool,
    accept_consent: bool,
    enforce_eligibility: bool,
    log: Callable[[str], None],
) -> tuple[bool, bool, bool]:
    row = bundle["row"]
    offer_id = bundle["offer_id"]
    saved = bundle["saved"]
    letter_text = bundle["letter_text"]
    page = context.new_page()
    held = False

    def before_final_action() -> None:
        nonlocal held
        if enforce_eligibility:
            latest_letter = deps.offer_letters.load(row["url"]) or {}
            if latest_letter.get(
                "letter"
            ) != letter_text or not deps.offer_letters.validation_is_current(latest_letter):
                raise deps.submit_handler.FormFillingError("Lettre modifiée ou contrôle périmé")
            if not deps.store.kit_documents_current(saved, letter_text):
                raise deps.submit_handler.FormFillingError(
                    "Documents ou profil modifiés depuis la préparation"
                )
        if not deps.store.kit_is_current(offer_id, saved):
            raise deps.submit_handler.FormFillingError(
                "Dossier périmé depuis l'ouverture du formulaire"
            )
        if not held:
            if not deps.store.claim_submission(offer_id):
                raise deps.submit_handler.FormFillingError("Candidature déjà traitée ou en cours")
            held = True

    try:
        result = deps.submit_handler.submit_hellowork_offer(
            page,
            row["url"],
            offer_id=offer_id,
            offer_title=row["title"],
            company=row["company"],
            cv_path=bundle["cv_path"],
            letter_text=letter_text,
            answers=deps.profile.form_answers_for(bundle["campaign"]),
            dry_run=not send,
            accept_consent=accept_consent,
            before_final_action=before_final_action if send else None,
        )
    except deps.submit_handler.UnsafeTargetError as exc:
        log(f"{offer_id} — cible refusée : {exc}")
        deps.store.event("submission_blocked", offer_id, str(exc))
        return False, False, False
    finally:
        try:
            page.close()
        except BROWSER_ERRORS as exc:
            LOG.debug("Fermeture page candidature ignorée : %s", exc)

    log(str(result))
    return _record_submit_outcome(deps, offer_id, result, send=send, held=held)


def apply_rows(
    deps: CliDeps,
    rows: list[Any],
    *,
    send: bool,
    headless: bool,
    accept_consent: bool,
    enforce_eligibility: bool = False,
    blocked_offer_ids: set[str] | None = None,
    deferred_offer_ids: set[str] | None = None,
    max_submits: int | None = None,
) -> bool:
    """Use the dedicated logged-in Chrome profile; only confirmations count as sent."""
    from career_copilot.hellowork_cli import reconcile

    def log(message: str) -> None:
        print(message)
        deps.daily.logger().info("apply: %s", message)

    profile_dir = deps.data_dir() / "hw-session"
    profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        profile_dir.chmod(0o700)
    ok = True
    blocked = set(blocked_offer_ids or set())
    deferred = set(deferred_offer_ids or set())
    with ExitStack() as stack:
        try:
            stack.enter_context(deps.submit_handler.session_lock(user_data_dir=profile_dir))
            playwright, context = deps.submit_handler.launch_persistent(
                profile_dir, headless=headless, sandbox=True
            )
        except BROWSER_ERRORS as exc:
            log(f"Impossible d'ouvrir le profil HelloWork : {type(exc).__name__}: {exc}")
            log("Ferme d'abord la fenêtre Chrome utilisant data/hw-session.")
            return False
        stack.callback(_close_playwright_session, playwright, context)
        if send:
            if deps.reconcile_pending_fn is not None:
                deps.reconcile_pending_fn(context, log)
            else:
                reconcile.reconcile_pending_hellowork(deps, context, log)
        submit_cap = resolve_submit_cap(
            send=send, enforce_eligibility=enforce_eligibility, max_submits=max_submits
        )
        submitted_count = 0
        for row in rows:
            if submit_cap is not None and submitted_count >= submit_cap:
                log(
                    f"Plafond anti-rafale atteint ({submit_cap} envoi(s) sur ce créneau) ; suite au prochain créneau."
                )
                break
            action, bundle = _validate_and_load_kit(
                deps,
                row,
                send=send,
                enforce_eligibility=enforce_eligibility,
                blocked_ids=blocked,
                deferred_ids=deferred,
                log=log,
            )
            if action == "fail":
                ok = False
                continue
            if action != "ready" or bundle is None:
                continue
            row_ok, inc, stop = _submit_prepared_bundle(
                deps,
                context,
                bundle,
                send=send,
                accept_consent=accept_consent,
                enforce_eligibility=enforce_eligibility,
                log=log,
            )
            if not row_ok:
                ok = False
            if inc:
                submitted_count += 1
            if stop:
                break
    if send:
        excel_ok = (
            deps.reconcile_excel_fn(log)
            if deps.reconcile_excel_fn is not None
            else reconcile.reconcile_excel_projections(deps, log)
        )
        ok = excel_ok and ok
    return ok
