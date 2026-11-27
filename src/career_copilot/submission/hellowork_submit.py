"""HelloWork offer navigation wrapper and candidate-space post-submit reconciliation."""

from __future__ import annotations

import re
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from career_copilot.submission import receipts
from career_copilot.submission.funnel import FunnelHooks, execute_auto_submit
from career_copilot.submission.models import (
    BROWSER_ERRORS,
    LOG,
    SubmitResult,
    UnsafeTargetError,
    assert_target,
    fold,
    hellowork_numeric_id,
    offer_unavailable,
    slug,
)


def submit_hellowork_offer(
    page: Any,
    offer_url: str,
    *,
    offer_id: str,
    offer_title: str = "",
    company: str = "",
    cv_path: str | Path,
    letter_text: str,
    answers: dict[str, str] | None = None,
    dry_run: bool = True,
    accept_consent: bool = False,
    pacing: tuple[float, float] = (2.0, 5.0),
    timeout_ms: int = 20_000,
    before_final_action: Callable[[], None] | None = None,
    hooks: FunnelHooks | None = None,
    inner_fn: Callable[..., SubmitResult] | None = None,
) -> SubmitResult:
    """Apply with navigation strictly confined to HTTPS HelloWork pages."""

    def guard(route: Any) -> None:
        request = route.request
        if request.is_navigation_request():
            try:
                assert_target(request.url, allow_hellowork=True)
                allowed = True
            except UnsafeTargetError:
                allowed = False
            if not allowed:
                route.abort()
                return
        route.continue_()

    page.route("**/*", guard)
    runner = inner_fn or submit_hellowork_offer_inner
    try:
        kwargs: dict[str, Any] = {
            "offer_id": offer_id,
            "offer_title": offer_title,
            "company": company,
            "cv_path": cv_path,
            "letter_text": letter_text,
            "answers": answers,
            "dry_run": dry_run,
            "accept_consent": accept_consent,
            "pacing": pacing,
            "timeout_ms": timeout_ms,
            "before_final_action": before_final_action,
        }
        if runner is submit_hellowork_offer_inner:
            kwargs["hooks"] = hooks
        return runner(page, offer_url, **kwargs)
    finally:
        try:
            page.unroute("**/*", guard)
        except BROWSER_ERRORS as exc:
            LOG.debug("Nettoyage route guard ignoré : %s", exc)


def _reconcile_unknown_result(
    page: Any,
    result: SubmitResult,
    *,
    hw_offer_id: str,
    offer_title: str,
    company: str,
    hooks: FunnelHooks,
) -> SubmitResult:
    if result.status != "unknown" or not offer_title or not company:
        return result
    try:
        receipt = hooks.check_application(
            page,
            offer_id=hw_offer_id,
            offer_title=offer_title,
            company=company,
        )
    except BROWSER_ERRORS as exc:
        LOG.debug("Vérification espace candidat indisponible : %s", exc)
        receipt = None
        result.detail += " ; vérification de l'espace candidat indisponible"
    if receipt:
        result.status = receipt["status"]
        result.confirmation = receipt["message"]
        result.application_id = receipt["application_id"]
        result.receipt_url = receipt["url"]
        result.detail = "État vérifié dans l'espace candidat HelloWork"
    elif receipts.candidatures_empty(page) is True:
        result.status = "blocked"
        result.detail = (
            "clic final sans candidature visible dans l'espace candidat ; réessai possible"
        )
    return result


def submit_hellowork_offer_inner(
    page: Any,
    offer_url: str,
    *,
    offer_id: str,
    offer_title: str = "",
    company: str = "",
    cv_path: str | Path,
    letter_text: str,
    answers: dict[str, str] | None = None,
    dry_run: bool = True,
    accept_consent: bool = False,
    pacing: tuple[float, float] = (2.0, 5.0),
    timeout_ms: int = 20_000,
    before_final_action: Callable[[], None] | None = None,
    hooks: FunnelHooks | None = None,
) -> SubmitResult:
    """Open a HelloWork offer and submit only its native HelloWork funnel."""
    active_hooks = hooks or FunnelHooks()
    assert_target(offer_url, allow_hellowork=True)
    parsed = urllib.parse.urlparse(offer_url)
    if not re.fullmatch(r"/fr-fr/emplois/\d+\.html", parsed.path):
        raise UnsafeTargetError("URL refusée : une fiche HTTPS HelloWork exacte est requise.")

    page.goto(
        "https://www.hellowork.com/fr-fr/candidat/mes-candidatures.html",
        wait_until="domcontentloaded",
        timeout=timeout_ms,
    )
    if "connexion" in urllib.parse.urlparse(page.url).path:
        return SubmitResult(
            offer_id=offer_id,
            status="not_logged_in",
            detail="reconnexion HelloWork nécessaire",
        )
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except BROWSER_ERRORS as exc:
        LOG.debug("Attente networkidle expirée : %s", exc)
    page.goto(offer_url, wait_until="domcontentloaded", timeout=timeout_ms)
    assert_target(page.url, allow_hellowork=True)
    receipts.dismiss_cookie_banner(page)
    funnel = page.locator("#offer-detail-funnel-container").first
    hw_offer_id = hellowork_numeric_id(offer_url, offer_id)
    try:
        if offer_unavailable(page.locator("body").inner_text(timeout=timeout_ms)):
            return SubmitResult(
                offer_id=offer_id,
                status="expired",
                detail="l'offre n'est plus disponible sur HelloWork",
            )
        funnel.scroll_into_view_if_needed(timeout=timeout_ms)
        receipts.open_hellowork_funnel(page, offer_url, hw_offer_id)
        deadline = time.monotonic() + max(timeout_ms / 1000, 30.0)
        bumped_at = 0.0
        while time.monotonic() < deadline:
            frame = page.locator(
                "#offer-detail-funnel-container turbo-frame#offer-detail-step-frame"
            ).first
            if not frame.count():
                frame = page.locator("turbo-frame#offer-detail-step-frame").first
            try:
                text = " ".join((frame.inner_text(timeout=1000) or "").split())
            except BROWSER_ERRORS:
                page.wait_for_timeout(250)
                continue
            if "site du recruteur" in fold(text) and "finaliser votre candidature" in fold(text):
                return SubmitResult(
                    offer_id=offer_id,
                    status="unsupported",
                    detail="cette offre redirige vers un ATS externe ; aucune action effectuée",
                )
            if frame.locator("form#offer-detail-main-step-form, form").count():
                result = execute_auto_submit(
                    page,
                    offer_id,
                    cv_path=cv_path,
                    letter_text=letter_text,
                    answers=answers,
                    dry_run=dry_run,
                    accept_consent=accept_consent,
                    pacing=pacing,
                    timeout_ms=timeout_ms,
                    screenshot_dir=active_hooks.data_dir()
                    / "hellowork"
                    / "captures"
                    / slug(offer_id),
                    allow_hellowork=True,
                    capture_screenshots=False,
                    before_final_action=before_final_action,
                    hooks=active_hooks,
                )
                return _reconcile_unknown_result(
                    page,
                    result,
                    hw_offer_id=hw_offer_id,
                    offer_title=offer_title,
                    company=company,
                    hooks=active_hooks,
                )
            now = time.monotonic()
            if now - bumped_at > 4.0:
                receipts.reload_hellowork_funnel(page, hw_offer_id, offer_url)
                bumped_at = now
            page.wait_for_timeout(250)
        return SubmitResult(
            offer_id=offer_id,
            status="blocked",
            detail="le tunnel direct HelloWork n'a pas chargé de formulaire",
        )
    except UnsafeTargetError:
        raise
    except BROWSER_ERRORS as exc:
        return SubmitResult(
            offer_id=offer_id,
            status="error",
            detail=f"{type(exc).__name__}: {exc}",
        )
