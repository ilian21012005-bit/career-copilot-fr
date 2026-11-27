"""Multi-step native funnel execution with explicit injectable hooks."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from career_copilot.submission import dom, form_fill, receipts
from career_copilot.submission.models import (
    BROWSER_ERRORS,
    FINAL_LABELS,
    LOG,
    NEXT_LABELS,
    FormFillingError,
    FormSelectors,
    SubmitResult,
    UnsafeTargetError,
    assert_target,
    fold,
    human_like_delay,
    slug,
)


@dataclass(frozen=True)
class FunnelHooks:
    """Explicit hooks enabling deterministic testing without module-global mutation."""

    wait_funnel: Callable[..., Any] = form_fill.wait_funnel
    fill_fields: Callable[..., None] = form_fill.fill_fields
    human_like_delay: Callable[..., float] = human_like_delay
    confirmation: Callable[..., str] = dom.confirmation
    find_button: Callable[..., Any] = dom.find_button
    required_missing: Callable[..., list[str]] = dom.required_missing
    capture_root: Callable[[], Path] = lambda: Path("data") / "sandbox" / "captures"
    data_dir: Callable[[], Path] = lambda: Path("data")
    recovery_paused: Callable[[], bool] = lambda: False
    check_application: Callable[..., dict[str, str] | None] = receipts.check_hellowork_application


@dataclass
class _FunnelState:
    final_action_started: bool = False


def _fill_pending_answers(
    page: Any,
    container: Any,
    pending: dict[str, str],
    result: SubmitResult,
    timeout_ms: int,
) -> bool:
    filled_any = False
    for label in list(pending):
        if form_fill.answer(
            page, container, label, pending[label], timeout_ms=min(timeout_ms, 1_500)
        ):
            result.filled.append(f"{label} = {pending.pop(label)}")
            filled_any = True
    return filled_any


def _handle_final_button(
    page: Any,
    container: Any,
    final: Any,
    *,
    step: int,
    pending: dict[str, str],
    result: SubmitResult,
    selectors: FormSelectors,
    shots: Path | None,
    dry_run: bool,
    accept_consent: bool,
    allow_hellowork: bool,
    timeout_ms: int,
    state: _FunnelState,
    before_final_action: Callable[[], None] | None,
    hooks: FunnelHooks,
) -> tuple[str, Any]:
    """Handle clicking a final CTA button. Returns `(flow_action, container)`."""
    if dry_run:
        result.status = "dry_run"
        result.detail = "clic final non effectué (dry_run)"
        dom.capture(page, shots, f"{step + 1:02d}-avant-envoi", result)
        return "break", container
    if accept_consent:
        form_fill.check_consents(page, container)
    _fill_pending_answers(page, container, pending, result, timeout_ms)
    missing = hooks.required_missing(container, final)
    if missing:
        result.status = "unknown" if state.final_action_started and allow_hellowork else "blocked"
        result.detail = "champs obligatoires incomplets : " + ", ".join(missing)
        dom.capture(page, shots, f"{step + 1:02d}-bloque", result)
        return "break", container
    before_sig = dom.step_signature(container, final)
    if allow_hellowork and hooks.recovery_paused():
        result.status = "unknown" if state.final_action_started else "blocked"
        result.detail = "Envois suspendus après restauration"
        return "break", container
    if allow_hellowork and before_final_action:
        before_final_action()
    state.final_action_started = True
    final.click()
    page.wait_for_timeout(min(2000, timeout_ms // 3))
    assert_target(page.url, allow_hellowork=allow_hellowork)
    try:
        container = hooks.wait_funnel(page, selectors, min(timeout_ms, 8_000))
    except BROWSER_ERRORS as exc:
        LOG.debug("Attente post-clic conteneur ignorée : %s", exc)
    scope = container if allow_hellowork else None
    message = hooks.confirmation(page, selectors, scope=scope)
    if (
        not message
        and not dom.has_antibot(page, container)
        and not dom.dissuasion_state(container)[0]
    ):
        message = dom.wait_confirmation(
            page,
            selectors,
            min(timeout_ms, 12_000),
            scope=scope,
            confirmation_fn=hooks.confirmation,
        )
    if message:
        result.status = "submitted"
        result.confirmation = message
        dom.capture(page, shots, f"{step + 1:02d}-confirmation", result)
        return "break", container
    if dom.has_antibot(page, container):
        result.status = "blocked"
        result.detail = "anti-bot / captcha détecté après clic (validation manuelle requise)"
        dom.capture(page, shots, f"{step + 1:02d}-bloque", result)
        return "break", container
    return _inspect_post_click_followup(
        page,
        container,
        step=step,
        pending=pending,
        result=result,
        shots=shots,
        before_sig=before_sig,
        timeout_ms=timeout_ms,
        hooks=hooks,
    )


def _inspect_post_click_followup(
    page: Any,
    container: Any,
    *,
    step: int,
    pending: dict[str, str],
    result: SubmitResult,
    shots: Path | None,
    before_sig: str,
    timeout_ms: int,
    hooks: FunnelHooks,
) -> tuple[str, Any]:
    filled_after_click = _fill_pending_answers(page, container, pending, result, timeout_ms)
    is_dissuasion, constraints, unsupported = dom.dissuasion_state(container)
    if is_dissuasion:
        if unsupported:
            result.status = "to_finish"
            result.detail = "condition prérequise non remplie : " + ", ".join(unsupported[:4])
            dom.capture(page, shots, f"{step + 1:02d}-bloque", result)
            return "break", container
        if constraints:
            result.detail = "conditions acceptées : " + ", ".join(constraints[:4])
    more: list[str] = []
    nxt = None
    next_step_btn = None
    try:
        nxt = hooks.find_button(page, container, FINAL_LABELS, partial=False)
        next_step_btn = hooks.find_button(page, container, NEXT_LABELS) if nxt is None else None
        more = hooks.required_missing(container, nxt) if nxt is not None else []
    except BROWSER_ERRORS as exc:
        LOG.debug("Inspection champs post-clic ignorée : %s", exc)
    if more:
        result.detail = "questions supplémentaires après Postuler : " + ", ".join(more[:6])
        return "continue", container
    if filled_after_click and nxt is not None:
        return "continue", container
    after_sig = dom.step_signature(container, nxt or next_step_btn)
    if after_sig and after_sig != before_sig and (nxt is not None or next_step_btn is not None):
        return "continue", container
    result.status = "unknown"
    result.detail = dom.error_text(page) or (
        "clic final effectué, mais aucune confirmation détectée ; "
        "vérifie l'espace candidat avant toute nouvelle tentative"
    )
    dom.capture(page, shots, f"{step + 1:02d}-bloque", result)
    return "break", container


def _advance_next_step(
    page: Any,
    container: Any,
    *,
    step: int,
    result: SubmitResult,
    shots: Path | None,
    allow_hellowork: bool,
    timeout_ms: int,
    state: _FunnelState,
    before_final_action: Callable[[], None] | None,
    hooks: FunnelHooks,
) -> bool:
    """Click a NEXT button if present. Returns True when funnel loop should break."""
    next_button = hooks.find_button(page, container, NEXT_LABELS)
    if next_button is None:
        labels = [label for label, _ in dom.buttons(page, container)]
        anti_bot = dom.has_antibot(page, container)
        result.status = (
            "blocked"
            if anti_bot
            else ("unknown" if state.final_action_started and allow_hellowork else "blocked")
        )
        result.detail = "aucun bouton reconnu (vu : " + ", ".join(labels[:6]) + ")"
        dom.capture(page, shots, f"{step + 1:02d}-bloque", result)
        return True
    missing = hooks.required_missing(container, next_button)
    if missing:
        result.status = "unknown" if state.final_action_started and allow_hellowork else "blocked"
        result.detail = "champs obligatoires incomplets : " + ", ".join(missing)
        dom.capture(page, shots, f"{step + 1:02d}-bloque", result)
        return True
    before = " ".join((container.inner_text() or "").split())
    if allow_hellowork:
        if before_final_action:
            before_final_action()
        state.final_action_started = True
    next_button.click()
    step_deadline = time.monotonic() + min(timeout_ms, 8_000) / 1000
    changed = False
    while time.monotonic() < step_deadline:
        page.wait_for_timeout(200)
        current = " ".join((container.inner_text() or "").split())
        if current and current != before:
            changed = True
            break
    if not changed:
        result.status = "unknown" if state.final_action_started and allow_hellowork else "blocked"
        result.detail = (
            "l'étape du formulaire n'a pas progressé ; arrêt pour éviter un double envoi"
        )
        dom.capture(page, shots, f"{step + 1:02d}-bloque", result)
        return True
    assert_target(page.url, allow_hellowork=allow_hellowork)
    return False


def execute_auto_submit(
    page: Any,
    offer_id: str,
    *,
    cv_path: str | Path,
    letter_text: str,
    answers: dict[str, str] | None = None,
    dry_run: bool = True,
    accept_consent: bool = False,
    selectors: FormSelectors | None = None,
    pacing: tuple[float, float] = (2.0, 5.0),
    max_steps: int = 8,
    timeout_ms: int = 15_000,
    screenshot_dir: str | Path | None = None,
    allow_hellowork: bool = False,
    capture_screenshots: bool = True,
    rng: random.Random | None = None,
    before_final_action: Callable[[], None] | None = None,
    hooks: FunnelHooks | None = None,
) -> SubmitResult:
    """Fill the funnel step by step and submit when `dry_run=False`."""
    active_hooks = hooks or FunnelHooks()
    selectors = selectors or FormSelectors()
    started = time.monotonic()
    result = SubmitResult(offer_id=offer_id, status="error")
    state = _FunnelState()
    shots = (
        (Path(screenshot_dir) if screenshot_dir else active_hooks.capture_root() / slug(offer_id))
        if capture_screenshots
        else None
    )

    try:
        if allow_hellowork and not dry_run and active_hooks.recovery_paused():
            return SubmitResult(
                offer_id=offer_id,
                status="blocked",
                detail="Envois suspendus après restauration",
            )
        assert_target(page.url, allow_hellowork=allow_hellowork)
        container = active_hooks.wait_funnel(page, selectors, timeout_ms)
        dom.capture(page, shots, "01-formulaire", result)

        if dry_run and allow_hellowork:
            if not Path(cv_path).is_file() or not letter_text.strip():
                raise FormFillingError("CV ou lettre manquant")
            result.status = "dry_run"
            result.detail = "formulaire direct détecté ; aperçu sans téléversement ni envoi"
            dom.capture(page, shots, "02-apercu", result)
            result.elapsed = round(time.monotonic() - started, 2)
            return result

        active_hooks.fill_fields(
            page,
            container,
            selectors,
            cv_path,
            letter_text,
            result,
            hellowork=allow_hellowork,
            timeout_ms=timeout_ms,
        )
        active_hooks.human_like_delay(page, *pacing, rng=rng)
        pending = dict(answers or {})

        for step in range(1, max_steps + 1):
            result.steps = step
            if allow_hellowork and "votre session a expire" in fold(container.inner_text()):
                result.status = "unknown" if state.final_action_started else "session_expired"
                result.detail = "HelloWork a refusé le formulaire : session de candidature expirée"
                break
            message = active_hooks.confirmation(
                page, selectors, scope=container if allow_hellowork else None
            )
            if message:
                result.status = "submitted"
                result.confirmation = message
                dom.capture(page, shots, f"{step + 1:02d}-confirmation", result)
                break
            if step > 1:
                active_hooks.human_like_delay(page, *pacing, rng=rng)
            _fill_pending_answers(page, container, pending, result, timeout_ms)

            final = active_hooks.find_button(page, container, FINAL_LABELS, partial=False)
            if final is not None:
                action, container = _handle_final_button(
                    page,
                    container,
                    final,
                    step=step,
                    pending=pending,
                    result=result,
                    selectors=selectors,
                    shots=shots,
                    dry_run=dry_run,
                    accept_consent=accept_consent,
                    allow_hellowork=allow_hellowork,
                    timeout_ms=timeout_ms,
                    state=state,
                    before_final_action=before_final_action,
                    hooks=active_hooks,
                )
                if action == "break":
                    break
                continue

            if _advance_next_step(
                page,
                container,
                step=step,
                result=result,
                shots=shots,
                allow_hellowork=allow_hellowork,
                timeout_ms=timeout_ms,
                state=state,
                before_final_action=before_final_action,
                hooks=active_hooks,
            ):
                break
        else:
            result.status = (
                "unknown" if state.final_action_started and allow_hellowork else "blocked"
            )
            result.detail = f"tunnel non terminé après {max_steps} étapes"
        result.skipped = list(pending)
    except UnsafeTargetError as exc:
        if not (state.final_action_started and allow_hellowork):
            raise
        result.status = "unknown"
        result.detail = str(exc)
    except FormFillingError as exc:
        result.status = "unknown" if state.final_action_started and allow_hellowork else "blocked"
        result.detail = str(exc)
    except BROWSER_ERRORS as exc:
        result.status = "unknown" if state.final_action_started and allow_hellowork else "error"
        result.detail = f"{type(exc).__name__}: {exc}"
        dom.capture(page, shots, "99-erreur", result)

    result.elapsed = round(time.monotonic() - started, 2)
    return result
