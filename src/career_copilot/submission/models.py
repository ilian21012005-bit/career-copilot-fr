"""Models, URL guards, constants, and concrete browser exception types for submission."""

from __future__ import annotations

import importlib
import logging
import random
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

LOG = logging.getLogger("career_copilot.submission")

ALLOWED_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
HELLOWORK_HOSTS: tuple[str, ...] = ("hellowork.com", "www.hellowork.com")

FINAL_LABELS: tuple[str, ...] = (
    "envoyer ma candidature",
    "soumettre ma candidature",
    "confirmer ma candidature",
    "valider ma candidature",
    "terminer ma candidature",
    "postuler",
    "envoyer",
    "confirmer",
)
NEXT_LABELS: tuple[str, ...] = ("suivant", "continuer", "etape suivante", "poursuivre")
CONFIRMATION_TEXTS: tuple[str, ...] = (
    "candidature envoyée",
    "candidature bien envoyée",
    "candidature transmise",
    "candidature a été envoyée",
    "candidature a bien été envoyée",
    "candidature est envoyée",
    "candidature est bien envoyée",
    "candidature a été transmise",
    "candidature a bien été transmise",
    "envoyée avec succès",
    "votre candidature a bien ete transmise",
    "votre candidature a bien été transmise",
    "nous avons bien recu votre candidature",
    "nous avons bien reçu votre candidature",
    "merci pour votre candidature",
)


class UnsafeTargetError(RuntimeError):
    """Target URL is outside allowed loopback or HTTPS HelloWork bounds."""


class FormFillingError(RuntimeError):
    """A mandatory form field could not be filled or verified."""


class SubmitBlocked(RuntimeError):
    """The application funnel stopped before confirmation."""


def _resolve_browser_errors() -> tuple[type[BaseException], ...]:
    errors: list[type[BaseException]] = [
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OSError,
        TimeoutError,
    ]
    try:
        playwright_error = importlib.import_module("playwright.sync_api").Error

        errors.append(playwright_error)
    except ImportError:
        pass
    return tuple(errors)


BROWSER_ERRORS: tuple[type[BaseException], ...] = _resolve_browser_errors()


@dataclass(frozen=True)
class FormSelectors:
    """Overridable CSS selectors for the application funnel."""

    funnel: tuple[str, ...] = (
        "#offer-detail-funnel-container",
        "[data-testid='apply-funnel']",
        "#apply-funnel",
        "form#application",
    )
    file: tuple[str, ...] = ("input[type=file]",)
    letter: tuple[str, ...] = (
        "#cover-letter",
        "textarea[name*='cover' i]",
        "textarea[name*='lettre' i]",
        "textarea[name*='motivation' i]",
        "textarea",
    )
    confirmation: tuple[str, ...] = (
        "#confirmation",
        "[data-testid='confirmation']",
        "[role='status']:has-text('envoyée')",
    )


@dataclass
class SubmitResult:
    offer_id: str
    status: str
    steps: int = 0
    elapsed: float = 0.0
    confirmation: str = ""
    screenshots: list[str] = field(default_factory=list)
    filled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    detail: str = ""
    application_id: str = ""
    receipt_url: str = ""

    @property
    def submitted(self) -> bool:
        return self.status == "submitted"

    def __str__(self) -> str:
        return (
            f"{self.offer_id}: {self.status} en {self.steps} étape(s), "
            f"{self.elapsed:.1f}s — {self.confirmation or self.detail}"
        )


def human_like_delay(
    page: Any,
    minimum: float = 2.0,
    maximum: float = 5.0,
    rng: random.Random | None = None,
) -> float:
    """Pacing pause between form actions without synthetic mouse movement."""
    source = rng or random
    low, high = sorted((max(0.0, minimum), max(0.0, maximum)))
    pause = source.uniform(low, high)
    page.wait_for_timeout(int(pause * 1000))
    return pause


def assert_local(url: str) -> None:
    assert_target(url, allow_hellowork=False)


def assert_target(url: str, *, allow_hellowork: bool) -> None:
    parsed = urllib.parse.urlparse(url or "")
    try:
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise UnsafeTargetError("URL cible invalide : port incorrect.") from exc
    has_credentials = parsed.username is not None or parsed.password is not None
    local = parsed.scheme in {"http", "https"} and host in ALLOWED_HOSTS and not has_credentials
    hellowork = (
        allow_hellowork
        and parsed.scheme == "https"
        and host in HELLOWORK_HOSTS
        and port in (None, 443)
        and not has_credentials
    )
    if not (local or hellowork):
        raise UnsafeTargetError(
            f"Cible refusée ({url or 'about:blank'}) : seules les cibles locales "
            "et, en mode autorisé, les pages HTTPS HelloWork sont acceptées."
        )


def offer_unavailable(text: str) -> bool:
    folded = re.sub(r"\s+", " ", fold(text)).replace("’", "'")
    return bool(re.search(r"\bcette offre d'emploi\b.{0,160}\bn'est plus disponible\b", folded))


def hellowork_numeric_id(offer_url: str, offer_id: str = "") -> str:
    """Extract numeric HelloWork job ID from `/emplois/<id>.html`."""
    match = re.search(r"/emplois/(\d+)\.html", offer_url or "")
    if match:
        return match.group(1)
    if re.fullmatch(r"\d+", offer_id or ""):
        return offer_id
    return offer_id or ""


def slug(text: str) -> str:
    safe = "".join(char if char.isalnum() else "-" for char in (text or "offre"))
    return "-".join(part for part in safe.split("-") if part)[:48] or "offre"


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    return (
        "".join(char for char in normalized if unicodedata.category(char) != "Mn").lower().strip()
    )
