"""Assisted Playwright prefill payload builder and HITL form-fill engine."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

from career_copilot.assist.ats_adapters import (
    ATS_ADAPTERS,
    SUBMIT_FORBIDDEN_MARKERS,
    detect_ats,
    resolve_ats_adapter,
    resolve_target_url,
)
from career_copilot.assist.deps import AssistDeps, offer_from_row_safe, row_get
from career_copilot.assist.email_extract import extract_public_recruiter_email

log = logging.getLogger("career_copilot.assist.prefill")

CONFIRMED_STATUSES: frozenset[str] = frozenset({"applied", "interview", "replied"})

_GATE_MARKERS: tuple[tuple[str, str], ...] = (
    ("captcha", "captcha"),
    ("turnstile", "cloudflare_turnstile"),
    ("verify you are human", "anti_bot"),
    ("vérifier que vous êtes humain", "anti_bot"),
    ("se connecter pour postuler", "login_required"),
    ("sign in to apply", "login_required"),
)

_IDENTITY_SELECTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "first_name",
        (
            'input[name*="first" i]',
            'input[id*="first" i]',
            'input[autocomplete="given-name"]',
            'input[placeholder*="Prénom" i]',
        ),
    ),
    (
        "last_name",
        (
            'input[name*="last" i]',
            'input[id*="last" i]',
            'input[autocomplete="family-name"]',
            'input[placeholder*="Nom" i]',
        ),
    ),
    (
        "email",
        ('input[type="email"]', 'input[name*="mail" i]', 'input[autocomplete="email"]'),
    ),
    (
        "phone",
        (
            'input[type="tel"]',
            'input[name*="phone" i]',
            'input[name*="tel" i]',
            'input[autocomplete="tel"]',
        ),
    ),
    (
        "city",
        ('input[name*="city" i]', 'input[name*="ville" i]', 'input[autocomplete="address-level2"]'),
    ),
)

_QUESTION_KEYS: tuple[str, ...] = (
    "school",
    "availability",
    "mobility",
    "address",
    "postal_code",
    "linkedin_url",
    "github_url",
    "portfolio_url",
)

_QUESTION_ALIASES: dict[str, tuple[str, ...]] = {
    "school": ("École", "Ecole", "school", "Formation"),
    "availability": ("disponibilite", "disponibilité", "Disponibilité", "availability"),
    "mobility": ("mobilite", "mobilité", "Mobilité", "mobility"),
    "address": ("Adresse", "adresse", "address"),
    "postal_code": ("Code postal", "code_postal", "postal_code"),
    "city": ("Ville", "ville", "city"),
    "linkedin_url": ("LinkedIn", "linkedin", "linkedin_url"),
    "github_url": ("GitHub", "github", "github_url"),
    "portfolio_url": ("Portfolio", "portfolio", "portfolio_url"),
}

_CV_FILE_SELECTORS: tuple[str, ...] = (
    'input[type="file"][name*="cv" i]',
    'input[type="file"][name*="resume" i]',
    'input[type="file"]',
)
_LETTER_FILE_SELECTORS: tuple[str, ...] = (
    'input[type="file"][name*="letter" i]',
    'input[type="file"][name*="motiv" i]',
)


def read_letter_text_safe(offer_url: str, letter_path: str, offer_letters_mod: Any) -> str:
    """Extract cover-letter text from saved offer_letters JSON or a safe ``.txt``/``.md`` file."""
    if offer_url:
        try:
            saved = offer_letters_mod.load(offer_url)
            if isinstance(saved, dict):
                text = str(saved.get("letter") or "").strip()
                if text:
                    return text
        except (OSError, ValueError) as exc:
            log.debug("Lecture lettre JSON ignorée (%s): %s", offer_url, exc)
    if letter_path:
        try:
            path = Path(letter_path)
            if (
                not path.is_symlink()
                and path.is_file()
                and path.suffix.lower() in (".txt", ".md")
                and path.stat().st_size <= 256 * 1024
            ):
                return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            log.debug("Lecture lettre fichier ignorée (%s): %s", letter_path, exc)
    return ""


def build_prefill_payload(row: Any, kit_data: Any, deps: AssistDeps) -> dict[str, Any]:
    """Build the assisted prefill payload from the active candidate profile and offer kit."""
    cand = deps.profile.CANDIDATE
    target_url = resolve_target_url(row)
    offer_url = str(row_get(row, "url") or "").strip()
    cv_path = str(row_get(kit_data, "cv_path") or "")
    letter_path = str(row_get(kit_data, "letter_path") or "")
    ats = detect_ats(target_url)
    ats_adapter = resolve_ats_adapter(ats)
    campaign = deps.scoring.campaign_of(offer_from_row_safe(row, deps.offers.Offer))
    answers = deps.profile.form_answers_for(campaign)
    letter_text = read_letter_text_safe(offer_url, letter_path, deps.offer_letters)
    recruiter_email = extract_public_recruiter_email(
        row_get(row, "description", ""),
        row_get(row, "missions", ""),
        row_get(row, "profile", ""),
        row_get(row, "notes", ""),
    )
    return {
        "offer_id": str(row_get(row, "id") or ""),
        "company": str(row_get(row, "company") or ""),
        "title": str(row_get(row, "title") or ""),
        "target_url": target_url,
        "ats": ats,
        "ats_adapter": ats_adapter,
        "recruiter_email": recruiter_email,
        "letter_text": letter_text,
        "answers": answers,
        "fields": {
            "first_name": str(cand.get("first_name") or ""),
            "last_name": str(cand.get("last_name") or ""),
            "name": str(cand.get("name") or ""),
            "email": str(cand.get("email") or ""),
            "phone": str(cand.get("phone") or ""),
            "city": str(cand.get("home") or ""),
            "address": str(cand.get("address") or ""),
            "postal_code": str(cand.get("postal_code") or ""),
            "linkedin_url": str(cand.get("linkedin_url") or ""),
            "github_url": str(cand.get("github_url") or ""),
            "portfolio_url": str(cand.get("portfolio_url") or ""),
            "school": str(cand.get("school") or ""),
        },
        "files": {
            "cv": cv_path if cv_path and Path(cv_path).is_file() else "",
            "letter": letter_path if letter_path and Path(letter_path).is_file() else "",
        },
    }


def ui_probe_errors() -> tuple[type[BaseException], ...]:
    """Return expected UI/Playwright probe exception types (never bare catch-all)."""
    base: tuple[type[BaseException], ...] = (
        AttributeError,
        LookupError,
        OSError,
        RuntimeError,
        TimeoutError,
        TypeError,
        ValueError,
    )
    try:
        playwright_error = importlib.import_module("playwright.sync_api").Error
    except ImportError:
        return base
    return (*base, playwright_error) if isinstance(playwright_error, type) else base


def detect_blocking_gate(page: Any) -> str:
    """Detect login walls, CAPTCHAs, or anti-bot challenges without bypassing them."""
    try:
        body_text = (page.inner_text("body") or "").lower()
    except ui_probe_errors() as exc:
        log.debug("Lecture corps de page ignorée: %s", exc)
        body_text = ""
    for marker, reason in _GATE_MARKERS:
        if marker in body_text:
            return reason
    return ""


def fill_first_matching(page: Any, selectors: tuple[str, ...], value: str) -> bool:
    """Fill the first visible input matching any selector in ``selectors``."""
    if not value:
        return False
    errs = ui_probe_errors()
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                locator.fill(value, timeout=2000)
                return True
        except errs as exc:
            log.debug("Remplissage ignoré (%s): %s", selector, exc)
    return False


def upload_first_matching(page: Any, selectors: tuple[str, ...], file_path: str) -> bool:
    """Attach a local file to the first matching file input."""
    if not file_path or not Path(file_path).is_file():
        return False
    errs = ui_probe_errors()
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.set_input_files(file_path, timeout=3000)
                return True
        except errs as exc:
            log.debug("Téléversement ignoré (%s): %s", selector, exc)
    return False


def has_visible_email_input(page: Any) -> bool:
    """Return ``True`` if an email input is already visible on the page."""
    try:
        locator = page.locator('input[type="email"]').first
        return bool(locator.count() > 0 and locator.is_visible())
    except ui_probe_errors() as exc:
        log.debug("Détection input email ignorée: %s", exc)
        return False


def is_submit_like_element(locator: Any) -> bool:
    """Refuse any button that looks like a final submit action (HITL guardrail)."""
    errs = ui_probe_errors()
    try:
        el_type = str(locator.get_attribute("type") or "").strip().lower()
        if el_type == "submit":
            return True
    except errs as exc:
        log.debug("Lecture type attribut ignorée: %s", exc)
    try:
        text = str(locator.inner_text() or "").strip().lower()
        if any(marker in text for marker in SUBMIT_FORBIDDEN_MARKERS):
            return True
    except errs as exc:
        log.debug("Lecture texte bouton ignorée: %s", exc)
    return False


def open_form_if_needed(page: Any, adapter: dict[str, Any]) -> bool:
    """Click once on a safe selector to reveal a collapsed application form."""
    if has_visible_email_input(page):
        return False
    errs = ui_probe_errors()
    for selector in adapter.get("open_form_selectors") or ():
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                if is_submit_like_element(locator):
                    continue
                locator.click(timeout=3000)
                page.wait_for_timeout(800)
                return True
        except errs as exc:
            log.debug("Ouverture formulaire ignorée (%s): %s", selector, exc)
    return False


def question_value(key: str, fields: dict[str, str], answers: dict[str, str]) -> str:
    """Resolve a standard ATS question value from ``fields`` or ``answers``."""
    direct = str(fields.get(key) or "").strip()
    if direct:
        return direct
    for alias in _QUESTION_ALIASES.get(key, (key,)):
        val = str(answers.get(alias) or "").strip()
        if val:
            return val
    return ""


def _prefill_page_fields(
    page: Any,
    payload: dict[str, Any],
    adapter: dict[str, Any],
) -> tuple[list[str], list[str]]:
    filled: list[str] = []
    uploaded: list[str] = []
    fields = payload["fields"]
    answers = payload["answers"]

    for key, selectors in _IDENTITY_SELECTORS:
        if fill_first_matching(page, selectors, fields.get(key, "")):
            filled.append(key)

    letter_selectors = tuple(adapter.get("letter_selectors") or ())
    if fill_first_matching(page, letter_selectors, payload.get("letter_text", "")):
        filled.append("letter_text")

    question_selectors = adapter.get("question_selectors") or {}
    for q_key in _QUESTION_KEYS:
        selectors = tuple(question_selectors.get(q_key) or ())
        val = question_value(q_key, fields, answers)
        if selectors and val and fill_first_matching(page, selectors, val):
            filled.append(q_key)

    files = payload["files"]
    if upload_first_matching(page, _CV_FILE_SELECTORS, files.get("cv", "")):
        uploaded.append("cv")
    if upload_first_matching(page, _LETTER_FILE_SELECTORS, files.get("letter", "")):
        uploaded.append("letter")
    return filled, uploaded


def launch_assisted_prefill(
    offer_id: str,
    deps: AssistDeps,
    *,
    headless: bool = False,
) -> dict[str, Any]:
    """Open an offer in Playwright and prefill form fields without ever clicking Submit."""
    deps.store.init()
    row = deps.store.get(offer_id)
    if not row:
        raise KeyError(f"Offre introuvable : {offer_id}")
    status = str(row_get(row, "status") or "")
    if status in CONFIRMED_STATUSES:
        raise ValueError(f"Offre déjà confirmée ({status}) : pré-remplissage bloqué.")

    kit_data = deps.store.kit_for(offer_id)
    if not kit_data or not deps.store.kit_is_current(offer_id, kit_data):
        offer_obj = offer_from_row_safe(row, deps.offers.Offer)
        result = deps.scoring.evaluate(offer_obj)
        files = deps.kit.build(offer_obj, result)
        deps.store.save_kit(
            offer_id, files["subject"], files["letter"], files["cv"], files["dossier"]
        )
        kit_data = deps.store.kit_for(offer_id)

    payload = build_prefill_payload(row, kit_data, deps)
    target_url = payload["target_url"]
    if not target_url.startswith(("http://", "https://")):
        raise ValueError("URL cible invalide pour le pré-remplissage.")

    adapter = ATS_ADAPTERS.get(payload["ats_adapter"], ATS_ADAPTERS["generic"])

    sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright

    filled: list[str] = []
    uploaded: list[str] = []
    gate = ""
    form_opened = False
    errs = ui_probe_errors()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1200)

            gate = detect_blocking_gate(page)
            if not gate:
                form_opened = open_form_if_needed(page, adapter)
                if form_opened:
                    gate = detect_blocking_gate(page)

            if not gate:
                filled, uploaded = _prefill_page_fields(page, payload, adapter)

            if not headless:
                try:
                    page.wait_for_event("close", timeout=600_000)
                except errs as exc:
                    log.debug("Attente fermeture fenêtre interrompue: %s", exc)
        finally:
            try:
                browser.close()
            except errs as exc:
                log.debug("Fermeture navigateur ignorée: %s", exc)

    return {
        "ok": True,
        "offer_id": offer_id,
        "ats": payload["ats"],
        "ats_adapter": payload["ats_adapter"],
        "target_url": target_url,
        "gate": gate,
        "form_opened": form_opened,
        "filled": filled,
        "uploaded": uploaded,
        "submitted": False,
    }
