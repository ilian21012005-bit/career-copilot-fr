"""HelloWork funnel bootstrap helpers and candidate-space receipt verification."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from career_copilot.submission.models import (
    BROWSER_ERRORS,
    HELLOWORK_HOSTS,
    LOG,
    assert_target,
    fold,
    hellowork_numeric_id,
)

_RECEIPT_STATES: dict[str, str] = {
    "envoyee": "submitted",
    "consultee": "submitted",
    "en cours d'envoi": "pending",
    "a finaliser": "to_finish",
}


def dismiss_cookie_banner(page: Any) -> None:
    """Close HelloWork cookie banner if it covers the application funnel."""
    for name in ("Tout accepter", "Continuer sans accepter"):
        try:
            btn = page.get_by_role("button", name=name)
            if btn.count():
                btn.first.click(timeout=2_000)
                page.wait_for_timeout(400)
                return
        except BROWSER_ERRORS as exc:
            LOG.debug("Bandeau cookies (%s) ignoré : %s", name, exc)


def open_hellowork_funnel(page: Any, offer_url: str, numeric_id: str) -> None:
    """Bring the native FormRO funnel into view via #postuler anchor / header CTA."""
    try:
        if "#postuler" not in (page.url or ""):
            page.evaluate("window.location.hash = 'postuler'")
            page.wait_for_timeout(300)
    except BROWSER_ERRORS as exc:
        LOG.debug("Navigation ancre #postuler ignorée : %s", exc)
    btn = page.locator("[data-cy='applyButtonHeader']").first
    try:
        if btn.count():
            btn.click(timeout=2_500)
            page.wait_for_timeout(400)
    except BROWSER_ERRORS as exc:
        LOG.debug("Clic CTA header échoué (%s), tentative JS", exc)
        try:
            page.evaluate("document.querySelector('[data-cy=applyButtonHeader]')?.click()")
        except BROWSER_ERRORS as js_exc:
            LOG.debug("Fallback clic CTA header ignoré : %s", js_exc)
    _ = (offer_url, numeric_id)


def reload_hellowork_funnel(page: Any, numeric_id: str, offer_url: str) -> None:
    """Force-load the turbo-frame when lazy loading stalls on a spinner."""
    if not numeric_id:
        return
    _ = offer_url
    try:
        loaded = page.evaluate(
            """(id) => {
                const root = document.querySelector('#offer-detail-funnel-container');
                const frame = (root && root.querySelector('turbo-frame#offer-detail-step-frame'))
                    || document.querySelector('turbo-frame#offer-detail-step-frame');
                if (!frame) return false;
                const src = '/fr-fr/offres/getinitialformframeview?offerId=' + id;
                frame.setAttribute('loading', 'eager');
                frame.setAttribute('src', src);
                if (typeof frame.reload === 'function') {
                    try { frame.reload(); } catch (e) {}
                }
                return true;
            }""",
            numeric_id,
        )
        if loaded:
            page.wait_for_timeout(1_200)
    except BROWSER_ERRORS as exc:
        LOG.debug("Rechargement turbo-frame ignoré : %s", exc)


def candidatures_empty(page: Any) -> bool | None:
    """Return True when `mes-candidatures.html` confirms zero applications exist."""
    try:
        page.goto(
            "https://www.hellowork.com/fr-fr/candidat/mes-candidatures.html",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        assert_target(page.url, allow_hellowork=True)
        page.wait_for_timeout(1_200)
        text = fold(page.locator("body").inner_text(timeout=8_000) or "")
        if "vous n'avez pas encore de candidature" in text:
            return True
        if page.locator("article[data-cy='applicationCard']").count():
            return False
        return None
    except BROWSER_ERRORS as exc:
        LOG.debug("Vérification page mes-candidatures vide indisponible : %s", exc)
        return None


def _parse_receipt_card(page_url: str, card: Any) -> tuple[str, str, str, str] | None:
    lines = [s.strip() for s in card.inner_text().splitlines() if s.strip()]
    state = fold(lines[0]).replace("’", "'") if lines else ""
    try:
        href = (
            card.get_by_role("link", name="Voir le détail", exact=True).get_attribute("href") or ""
        )
    except BROWSER_ERRORS as exc:
        LOG.debug("Lien détail reçu absent : %s", exc)
        href = ""
    url = urllib.parse.urljoin(page_url, href)
    parsed = urllib.parse.urlparse(url)
    match = re.fullmatch(r"/fr-fr/candidat/mes-candidatures/(\d+)\.html", parsed.path)
    if not match or parsed.hostname not in HELLOWORK_HOSTS:
        return None
    return state, (lines[0] if lines else ""), url, match.group(1)


def check_hellowork_application(
    page: Any, *, offer_id: str, offer_title: str, company: str
) -> dict[str, str] | None:
    """Read official receipt, validating title, company, and original offer URL."""
    numeric_id = offer_id if re.fullmatch(r"\d+", offer_id or "") else ""
    page.goto(
        "https://www.hellowork.com/fr-fr/candidat/mes-candidatures.html",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    assert_target(page.url, allow_hellowork=True)
    cards = page.locator("article[data-cy='applicationCard']").filter(
        has=page.get_by_role("heading", name=offer_title, exact=True)
    )
    try:
        cards.first.wait_for(state="visible", timeout=8_000)
    except BROWSER_ERRORS as exc:
        LOG.debug("Aucune carte de candidature visible : %s", exc)
        return None
    candidates: list[tuple[str, str, str, str, bool]] = []
    for index in range(cards.count()):
        card = cards.nth(index)
        company_ok = bool(card.get_by_text(company, exact=True).count()) if company else False
        if not company_ok and not numeric_id:
            continue
        parsed_card = _parse_receipt_card(page.url, card)
        if parsed_card is not None:
            candidates.append((*parsed_card, company_ok))
    candidates.sort(key=lambda item: 0 if item[4] else 1)
    for state, raw_state, url, app_id, _company_ok in candidates:
        if state not in _RECEIPT_STATES:
            continue
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        source = page.get_by_role("link", name="L'offre", exact=True).get_attribute("href") or ""
        source_url = urllib.parse.urlparse(urllib.parse.urljoin(page.url, source))
        if source_url.hostname not in HELLOWORK_HOSTS:
            continue
        source_numeric = hellowork_numeric_id(source_url.path)
        if numeric_id and source_numeric != numeric_id:
            continue
        if not numeric_id and not source_numeric:
            continue
        return {
            "status": _RECEIPT_STATES[state],
            "message": f"HelloWork : {raw_state}",
            "application_id": app_id,
            "url": url,
        }
    return None


def list_hellowork_receipts(page: Any, *, max_pages: int = 2) -> dict[str, dict[str, str]]:
    """Collect candidate-space receipts indexed by numeric HelloWork offer ID."""
    card_entries: list[tuple[str, str, str, str]] = []
    for p in range(1, max(1, max_pages) + 1):
        list_url = (
            "https://www.hellowork.com/fr-fr/candidat/mes-candidatures.html"
            if p == 1
            else f"https://www.hellowork.com/fr-fr/candidat/mes-candidatures.html?p={p}"
        )
        page.goto(list_url, wait_until="domcontentloaded", timeout=30_000)
        assert_target(page.url, allow_hellowork=True)
        if "connexion" in urllib.parse.urlparse(page.url).path:
            break
        cards = page.locator("article[data-cy='applicationCard']")
        try:
            cards.first.wait_for(state="visible", timeout=5_000)
        except BROWSER_ERRORS as exc:
            LOG.debug("Fin pagination mes-candidatures page %d : %s", p, exc)
            break
        count = cards.count()
        if not count:
            break
        for idx in range(count):
            parsed_card = _parse_receipt_card(page.url, cards.nth(idx))
            if parsed_card is not None and parsed_card[0] in _RECEIPT_STATES:
                card_entries.append(parsed_card)

    receipts: dict[str, dict[str, str]] = {}
    for state, raw_state, url, app_id in card_entries:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            assert_target(page.url, allow_hellowork=True)
            source = (
                page.get_by_role("link", name="L'offre", exact=True).get_attribute("href") or ""
            )
            source_url = urllib.parse.urlparse(urllib.parse.urljoin(page.url, source))
            if source_url.hostname not in HELLOWORK_HOSTS:
                continue
            source_numeric = hellowork_numeric_id(source_url.path)
            if source_numeric and source_numeric not in receipts:
                receipts[source_numeric] = {
                    "status": _RECEIPT_STATES[state],
                    "message": f"HelloWork : {raw_state}",
                    "application_id": app_id,
                    "url": url,
                }
        except BROWSER_ERRORS as exc:
            LOG.debug("Lecture détail reçu %s ignorée : %s", app_id, exc)
    return receipts
