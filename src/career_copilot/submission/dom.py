"""DOM inspection, buttons, anti-bot/dissuasion detection, confirmations, and captures."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from career_copilot.fs_privacy import ensure_private_directory, protect_private_file
from career_copilot.submission.models import (
    BROWSER_ERRORS,
    CONFIRMATION_TEXTS,
    LOG,
    FormFillingError,
    FormSelectors,
    SubmitResult,
    fold,
)

_UNSUPPORTED_DISSUASION_RE = re.compile(
    r"\b(?:"
    r"permis\s+[bcd]|permis\s+de\s+conduire|vehicule\s+personnel|voiture\s+personnelle|"
    r"caces(?:\s+[0-9r]+)?|cariste|poids\s+lourd|spl|ssiap|bafa|"
    r"cap\s+(?:cuisine|boulanger|patissier)|bep\s+cuisine"
    r")\b"
)
_DISSUASION_NEGATIONS_RE = re.compile(
    r"\b(?:sans|aucun(?:e)?|pas\s+de|non\s+requis|non\s+obligatoire|facultatif)\b"
)


def step_signature(container: Any, button: Any | None = None) -> str:
    """Compact signature of active DOM step to detect genuine step transitions."""
    try:
        text = " ".join((container.inner_text(timeout=1_000) or "").split())
    except BROWSER_ERRORS as exc:
        LOG.debug("Lecture texte étape impossible : %s", exc)
        text = ""
    action = ""
    if button is not None:
        try:
            action = str(
                button.evaluate("e => (e.form || e.closest('form'))?.getAttribute('action') || ''")
                or ""
            )
        except BROWSER_ERRORS as exc:
            LOG.debug("Lecture action formulaire impossible : %s", exc)
            action = ""
    return f"{action}|{text}" if (text or action) else ""


def has_antibot(page: Any, container: Any) -> bool:
    """Detect anti-bot widgets (FriendlyCaptcha, Turnstile) without bypassing them."""
    scope = container if container is not None else page
    try:
        labels = [label for label, _ in buttons(page, scope)]
        if any("clique ici pour verifier" in fold(lbl) or "captcha" in fold(lbl) for lbl in labels):
            return True
    except BROWSER_ERRORS as exc:
        LOG.debug("Lecture boutons anti-bot impossible : %s", exc)
    try:
        if "clique ici pour verifier" in fold(scope.inner_text(timeout=1_000) or ""):
            return True
    except BROWSER_ERRORS as exc:
        LOG.debug("Lecture texte anti-bot impossible : %s", exc)
    try:
        widgets = scope.locator(
            ".frc-captcha, [data-sitekey], iframe[src*='captcha'], iframe[src*='turnstile']"
        )
        return bool(widgets.count() > 0)
    except BROWSER_ERRORS as exc:
        LOG.debug("Détection sélecteur anti-bot impossible : %s", exc)
        return False


def dissuasion_state(container: Any) -> tuple[bool, list[str], list[str]]:
    """Inspect a HelloWork pre-condition screen (`product.preselect_question`)."""
    if container is None:
        return False, [], []
    try:
        payload = container.evaluate(
            """root => {
                const isDissuasion = Boolean(
                    root.querySelector(
                        "form[action*='dissuasion'], [data-analytics-values-param*='preselect_question']"
                    )
                );
                const scope = root.querySelector('#offer-detail-step-frame') || root;
                const items = Array.from(scope.querySelectorAll('li'))
                    .map(el => (el.innerText || '').trim())
                    .filter(Boolean);
                return { isDissuasion, items, text: root.innerText || '' };
            }"""
        )
    except BROWSER_ERRORS as exc:
        LOG.debug("Inspection écran dissuasion impossible : %s", exc)
        return False, [], []
    folded_text = fold(str(payload.get("text") or ""))
    is_dissuasion = bool(payload.get("isDissuasion")) or (
        "conditions de travail specifiques" in folded_text
        and "vous pouvez poursuivre votre candidature" in folded_text
    )
    if not is_dissuasion:
        return False, [], []
    constraints = [str(item).strip() for item in (payload.get("items") or []) if str(item).strip()]
    unsupported = [
        item
        for item in constraints
        if _UNSUPPORTED_DISSUASION_RE.search(fold(item))
        and not _DISSUASION_NEGATIONS_RE.search(fold(item))
    ]
    return True, constraints, unsupported


def buttons(page: Any, container: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    scope = container if container is not None else page
    locator = scope.locator("button, [role='button'], input[type='submit']")
    for index in range(locator.count()):
        item = locator.nth(index)
        try:
            if not (item.is_visible() and item.is_enabled()):
                continue
            label = (item.inner_text() or item.get_attribute("value") or "").strip()
            if label:
                found.append((label, item))
        except BROWSER_ERRORS as exc:
            LOG.debug("Lecture bouton #%d ignorée : %s", index, exc)
    return found


def find_button(page: Any, container: Any, labels: tuple[str, ...], *, partial: bool = True) -> Any:
    for label, locator in buttons(page, container):
        folded = fold(label)
        if any(folded == target or (partial and target in folded) for target in labels):
            return locator
    return None


def required_missing(container: Any, button: Any | None = None) -> list[str]:
    """Validate the submitted form, excluding unrelated forms such as the uploader."""
    try:
        script = """root => [...(root.elements || root.querySelectorAll('input,select,textarea'))]
            .filter(e => e.willValidate && !e.validity.valid)
            .map(e => e.labels?.[0]?.innerText?.trim() || e.name || e.id || e.type || 'champ')"""
        if button is not None:
            return list(
                button.evaluate(
                    "e => { const root = e.form || e.closest('form'); "
                    "if (!root) throw new Error('formulaire du bouton introuvable'); "
                    "return (" + script + ")(root); }"
                )
            )
        return list(container.evaluate(script))
    except BROWSER_ERRORS as exc:
        raise FormFillingError("impossible de vérifier les champs du formulaire") from exc


def first_visible(page: Any, container: Any, selectors: tuple[str, ...]) -> Any:
    _ = page
    for selector in selectors:
        locator = container.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return locator
        except BROWSER_ERRORS as exc:
            LOG.debug("Sélecteur %s ignoré : %s", selector, exc)
    return None


def confirmation(page: Any, selectors: FormSelectors, *, scope: Any | None = None) -> str:
    root = scope if scope is not None else page
    for selector in selectors.confirmation:
        locator = root.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                text = (locator.inner_text() or "").strip()
                if text and (
                    scope is None or any(fold(s) in fold(text) for s in CONFIRMATION_TEXTS)
                ):
                    return text
        except BROWSER_ERRORS as exc:
            LOG.debug("Lecture confirmation (%s) ignorée : %s", selector, exc)
    for text in CONFIRMATION_TEXTS:
        locator = root.get_by_text(re.compile(re.escape(text), re.I)).first
        try:
            if locator.count() and locator.is_visible():
                return (locator.inner_text() or text).strip()
        except BROWSER_ERRORS as exc:
            LOG.debug("Texte confirmation ignoré : %s", exc)
    return ""


def wait_confirmation(
    page: Any,
    selectors: FormSelectors,
    timeout_ms: int,
    *,
    scope: Any | None = None,
    confirmation_fn: Any = None,
) -> str:
    check_fn = confirmation_fn or confirmation
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        message = check_fn(page, selectors, scope=scope)
        if message:
            return str(message)
        page.wait_for_timeout(200)
    return ""


def error_text(page: Any) -> str:
    for selector in ("#funnel-status", ".error", "[role='alert']", "[aria-live='polite']"):
        locator = page.locator(selector).first
        try:
            if locator.count():
                text = (locator.inner_text() or "").strip()
                if text and "envoi…" not in text.lower():
                    return text
        except BROWSER_ERRORS as exc:
            LOG.debug("Lecture alerte DOM (%s) ignorée : %s", selector, exc)
    return ""


def capture(page: Any, folder: Path | None, name: str, result: SubmitResult) -> None:
    if folder is None:
        return
    try:
        ensure_private_directory(folder)
        path = folder / f"{name}.png"
        page.screenshot(path=str(path), full_page=True)
        protect_private_file(path)
        result.screenshots.append(str(path))
    except BROWSER_ERRORS as exc:
        LOG.debug("Capture écran %s ignorée : %s", name, exc)
