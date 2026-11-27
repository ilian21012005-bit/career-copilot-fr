"""Form-field filling, CV upload, radio/select answering, and required consent checks."""

from __future__ import annotations

import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from career_copilot.submission.dom import first_visible
from career_copilot.submission.models import (
    BROWSER_ERRORS,
    LOG,
    FormFillingError,
    FormSelectors,
    SubmitResult,
    fold,
)


def wait_funnel(page: Any, selectors: FormSelectors, timeout_ms: int) -> Any:
    deadline = time.monotonic() + timeout_ms / 1000
    last_error = ""
    while time.monotonic() < deadline:
        for selector in selectors.funnel:
            locator = page.locator(selector).first
            try:
                if locator.count() and locator.is_visible():
                    return locator
            except BROWSER_ERRORS as exc:
                last_error = str(exc)
        page.wait_for_timeout(150)
    raise FormFillingError(
        "conteneur du formulaire introuvable ("
        + ", ".join(selectors.funnel)
        + ")"
        + (f" — {last_error}" if last_error else "")
    )


def _upload_hellowork_cv(
    page: Any, container: Any, file_input: Any, path: Path, timeout_ms: int
) -> None:
    if path.stat().st_size > 2 * 1024 * 1024:
        raise FormFillingError("le CV dépasse la limite HelloWork de 2 Mo")
    with page.expect_response(
        lambda response: urllib.parse.urlparse(response.url).path.lower() == "/fr-fr/uploadcv",
        timeout=timeout_ms,
    ) as uploaded:
        file_input.set_input_files(str(path.resolve()))
    if not uploaded.value.ok:
        raise FormFillingError(f"téléversement du CV refusé ({uploaded.value.status})")
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        selected = container.locator("select[name='JweHashResume']").first
        if selected.count() and selected.evaluate(
            "(e, expected) => !!e.value && e.selectedOptions[0]?.textContent.trim() === expected",
            path.name,
        ):
            break
        hashed = container.locator("input[name='JweHashResume']").first
        if hashed.count() and (hashed.input_value() or "").strip():
            break
        page.wait_for_timeout(150)
    else:
        raise FormFillingError("le CV téléversé n'est pas confirmé comme CV sélectionné")
    toggle = container.locator("#cover-letter-collapse-funnel")
    if toggle.count() and not toggle.is_checked():
        container.locator("label[for='cover-letter-collapse-funnel']").click()


def fill_fields(
    page: Any,
    container: Any,
    selectors: FormSelectors,
    cv_path: str | Path,
    letter_text: str,
    result: SubmitResult,
    *,
    hellowork: bool = False,
    timeout_ms: int = 15_000,
) -> None:
    path = Path(cv_path)
    if not path.exists():
        raise FormFillingError(f"CV introuvable : {path}")
    file_input = first_visible(page, container, selectors.file)
    if file_input is None:
        raise FormFillingError("champ fichier (CV) introuvable")
    if hellowork:
        _upload_hellowork_cv(page, container, file_input, path, timeout_ms)
    else:
        file_input.set_input_files(str(path))
    result.filled.append(f"CV → {path.name}")

    letter = first_visible(page, container, selectors.letter)
    if letter is None:
        raise FormFillingError("zone de lettre de motivation introuvable")
    payload = letter_text
    limit = letter.get_attribute("maxlength")
    soft_limit = int(limit) if limit and int(limit) >= 0 else 2900
    if len(payload) > soft_limit:
        payload = payload[:soft_limit]
    letter.fill(payload)
    if letter.input_value() != payload:
        raise FormFillingError("le contenu de la lettre n'a pas été conservé")
    result.filled.append(f"lettre ({len(payload)} caractères)")


def _try_answer_radio(
    container: Any, label: str, value: str, folded_value: str, timeout_ms: int
) -> bool:
    try:
        radios = container.locator(
            f"input[type='radio'][name], input[type='radio'][aria-label*='{value}' i]"
        )
        for index in range(min(radios.count(), 40)):
            radio = radios.nth(index)
            if not radio.is_visible():
                continue
            accessible = fold(
                (radio.get_attribute("aria-label") or "")
                + " "
                + (
                    radio.evaluate("e => (e.labels && e.labels[0] && e.labels[0].innerText) || ''")
                    or ""
                )
                + " "
                + (radio.get_attribute("value") or "")
            )
            group = fold(
                radio.evaluate(
                    """e => {
                        const root = e.closest('fieldset,[role=radiogroup],.form-group,div');
                        const legend = root && (root.querySelector('legend,label,p,span'));
                        return (legend && legend.innerText) || '';
                    }"""
                )
                or ""
            )
            if folded_value in accessible or (
                fold(label) in group
                and (
                    folded_value in accessible
                    or folded_value == fold(radio.get_attribute("value") or "")
                )
            ):
                radio.check(timeout=timeout_ms)
                return True
    except BROWSER_ERRORS as exc:
        LOG.debug("Réponse radio « %s » ignorée : %s", label, exc)
    return False


def _fill_locator_control(locator: Any, value: str, folded_value: str, timeout_ms: int) -> bool:
    tag = (locator.evaluate("el => el.tagName") or "").lower()
    input_type = (locator.get_attribute("type") or "").lower()
    if tag == "select":
        selected_value = locator.evaluate(
            """(el, target) => {
                const fold = value => String(value || "").normalize("NFD")
                    .replace(/[\\u0300-\\u036f]/g, "").trim().toLowerCase();
                const wanted = fold(target);
                const option = Array.from(el.options).find(item =>
                    fold(item.label || item.textContent) === wanted || fold(item.value) === wanted
                );
                return option ? option.value : null;
            }""",
            value,
        )
        if selected_value is None:
            return False
        locator.select_option(value=selected_value, timeout=timeout_ms)
        return True
    if input_type == "checkbox":
        if folded_value in ("oui", "true", "1", "yes", "aucune"):
            locator.check(timeout=timeout_ms)
            return True
        return False
    if input_type == "radio":
        locator.check(timeout=timeout_ms)
        return True
    readonly = locator.get_attribute("readonly") is not None
    disabled = locator.is_disabled()
    try:
        editable = locator.is_editable()
    except BROWSER_ERRORS:
        editable = not readonly and not disabled
    if readonly or disabled or not editable:
        return False
    locator.fill(value, timeout=timeout_ms)
    return True


def answer(page: Any, container: Any, label: str, value: str, *, timeout_ms: int = 1_500) -> bool:
    """Fill a visible control by label or name; ignore read-only fields."""
    _ = page
    folded_value = fold(value)
    if _try_answer_radio(container, label, value, folded_value, timeout_ms):
        return True
    if folded_value in {"aucune", "non", "no"}:
        try:
            box = container.get_by_label(re.compile(r"aucune", re.I)).first
            if box.count() and box.is_visible():
                box.check(timeout=timeout_ms)
                return True
        except BROWSER_ERRORS as exc:
            LOG.debug("Case « Aucune » ignorée : %s", exc)

    for locator in (
        container.get_by_label(label, exact=True).first,
        container.get_by_label(label, exact=False).first,
        container.locator(f"[name='{label}']").first,
        container.locator(f"#{label}").first,
    ):
        try:
            if not locator.count() or not locator.is_visible():
                continue
            if _fill_locator_control(locator, value, folded_value, timeout_ms):
                return True
        except BROWSER_ERRORS as exc:
            LOG.debug("Remplissage champ « %s » ignoré : %s", label, exc)
    return False


def check_consents(page: Any, container: Any) -> int:
    """Check only controls marked required; leave optional consents unchecked."""
    _ = page
    checked = 0
    boxes = container.locator("input[type='checkbox']")
    for index in range(boxes.count()):
        box = boxes.nth(index)
        try:
            required = (
                box.get_attribute("required") is not None
                or box.get_attribute("aria-required") == "true"
            )
            if required and box.is_visible() and not box.is_checked():
                box.check()
                checked += 1
        except BROWSER_ERRORS as exc:
            LOG.debug("Case consentement #%d ignorée : %s", index, exc)
    return checked
