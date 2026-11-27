"""ATS portal detection, selector registry, and target URL resolution."""

from __future__ import annotations

from typing import Any

from career_copilot.assist.deps import row_get

_ATS_HOST_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("hellowork.com",), "hellowork"),
    (("myworkdayjobs.com", "workday"), "workday"),
    (("greenhouse.io",), "greenhouse"),
    (("lever.co",), "lever"),
    (("smartrecruiters.com",), "smartrecruiters"),
    (("welcometothejungle.com",), "wttj"),
    (("teamtailor.com",), "teamtailor"),
    (("recruitee.com",), "recruitee"),
    (("jobaffinity.fr",), "jobaffinity"),
)


def detect_ats(url: str) -> str:
    """Identify the probable ATS portal from a target URL."""
    low = (url or "").lower()
    for markers, name in _ATS_HOST_RULES:
        if any(marker in low for marker in markers):
            return name
    return "generic"


BASE_QUESTION_SELECTORS: dict[str, tuple[str, ...]] = {
    "school": (
        'input[name*="school" i]',
        'input[id*="school" i]',
        'input[name*="ecole" i]',
        'input[name*="école" i]',
        'input[name*="university" i]',
        'input[placeholder*="École" i]',
    ),
    "availability": (
        'input[name*="avail" i]',
        'input[id*="avail" i]',
        'input[name*="disponib" i]',
        'textarea[name*="disponib" i]',
        'input[placeholder*="Disponibilit" i]',
    ),
    "mobility": (
        'input[name*="mobil" i]',
        'input[id*="mobil" i]',
        'input[placeholder*="Mobilit" i]',
    ),
    "address": (
        'input[name*="address" i]',
        'input[name*="adresse" i]',
        'input[autocomplete="street-address"]',
    ),
    "postal_code": (
        'input[name*="postal" i]',
        'input[name*="zip" i]',
        'input[name*="code_postal" i]',
        'input[autocomplete="postal-code"]',
    ),
    "linkedin_url": (
        'input[name*="linkedin" i]',
        'input[id*="linkedin" i]',
        'input[placeholder*="LinkedIn" i]',
    ),
    "github_url": (
        'input[name*="github" i]',
        'input[id*="github" i]',
        'input[placeholder*="GitHub" i]',
    ),
    "portfolio_url": (
        'input[name*="portfolio" i]',
        'input[id*="portfolio" i]',
        'input[name*="website" i]',
        'input[placeholder*="Portfolio" i]',
    ),
}


def merge_question_selectors(
    overrides: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Combine base question selectors with ATS-specific selector overrides."""
    merged = dict(BASE_QUESTION_SELECTORS)
    if overrides:
        for key, extra in overrides.items():
            merged[key] = tuple(dict.fromkeys((*extra, *merged.get(key, ()))))
    return merged


ATS_ADAPTERS: dict[str, dict[str, Any]] = {
    "greenhouse": {
        "open_form_selectors": (
            'a[href*="#app"]',
            'a[href*="#application"]',
            'button[data-qa="apply"]',
        ),
        "letter_selectors": (
            'textarea[name*="cover" i]',
            'textarea[id*="cover" i]',
            'textarea[name*="letter" i]',
            'textarea[name*="motiv" i]',
            "textarea",
        ),
        "question_selectors": merge_question_selectors(
            {
                "school": ('input[id*="education" i]', 'input[name*="school" i]'),
                "linkedin_url": ('input[name*="question"][placeholder*="LinkedIn" i]',),
            }
        ),
    },
    "lever": {
        "open_form_selectors": (
            'a.postings-btn[href*="/apply"]',
            'a[href$="/apply"]',
        ),
        "letter_selectors": (
            'textarea[name="comments"]',
            'textarea[name*="cover" i]',
            'textarea[name*="motiv" i]',
            "textarea",
        ),
        "question_selectors": merge_question_selectors(
            {
                "school": ('input[name="org"]',),
                "linkedin_url": ('input[name="urls[LinkedIn]"]',),
                "github_url": ('input[name="urls[GitHub]"]',),
                "portfolio_url": ('input[name="urls[Portfolio]"]', 'input[name="urls[Other]"]'),
            }
        ),
    },
    "smartrecruiters": {
        "open_form_selectors": (
            "a#st-apply",
            "button#st-apply",
            'a[data-test="apply-button"]',
        ),
        "letter_selectors": (
            'textarea[name*="cover" i]',
            'textarea[name*="letter" i]',
            'textarea[name*="motiv" i]',
            "textarea",
        ),
        "question_selectors": merge_question_selectors(),
    },
    "workday": {
        "open_form_selectors": (
            'a[data-automation-id="adventureButton"]',
            'button[data-automation-id="adventureButton"]',
        ),
        "letter_selectors": (
            'textarea[data-automation-id*="cover" i]',
            'textarea[name*="letter" i]',
            'textarea[name*="motiv" i]',
            "textarea",
        ),
        "question_selectors": merge_question_selectors(
            {
                "address": ('input[data-automation-id="addressSection_addressLine1"]',),
                "postal_code": ('input[data-automation-id="addressSection_postalCode"]',),
                "school": ('input[data-automation-id*="school" i]',),
            }
        ),
    },
    "teamtailor": {
        "open_form_selectors": (
            'a[href*="#apply"]',
            'button[data-action*="apply"]',
            "a[data-open-apply]",
        ),
        "letter_selectors": (
            'textarea[name*="cover" i]',
            'textarea[id*="cover" i]',
            'textarea[name*="motiv" i]',
            "textarea",
        ),
        "question_selectors": merge_question_selectors(),
    },
    "recruitee": {
        "open_form_selectors": (
            'a[href*="#offer-apply"]',
            'button[data-cy="apply-button"]',
            'a[data-cy="apply-button"]',
        ),
        "letter_selectors": (
            'textarea[name*="cover" i]',
            'textarea[id*="cover" i]',
            'textarea[name*="motiv" i]',
            "textarea",
        ),
        "question_selectors": merge_question_selectors(),
    },
    "wttj": {
        "open_form_selectors": (
            'button[data-testid="job_header-button-apply"]',
            'a[data-testid="job_header-button-apply"]',
            'button[data-qa="btn-apply"]',
        ),
        "letter_selectors": (
            'textarea[name*="cover" i]',
            'textarea[name*="letter" i]',
            'textarea[name*="motiv" i]',
            "textarea",
        ),
        "question_selectors": merge_question_selectors(),
    },
    "jobaffinity": {
        "open_form_selectors": (
            'a[href*="#apply"]',
            'a[href*="/apply/"]',
            'button[type="button"]:has-text("Postuler")',
        ),
        "letter_selectors": (
            'textarea[name*="cover" i]',
            'textarea[name*="letter" i]',
            'textarea[name*="motiv" i]',
            'textarea[id*="motiv" i]',
            "textarea",
        ),
        "question_selectors": merge_question_selectors(),
    },
    "generic": {
        "open_form_selectors": (
            'button[data-qa="btn-apply"]',
            'a[href*="#apply"]',
            'a[href*="#app"]',
        ),
        "letter_selectors": (
            'textarea[name*="cover" i]',
            'textarea[id*="cover" i]',
            'textarea[name*="letter" i]',
            'textarea[name*="motiv" i]',
            'textarea[placeholder*="motiv" i]',
            'textarea[placeholder*="lettre" i]',
        ),
        "question_selectors": merge_question_selectors(),
    },
}

SUBMIT_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "submit",
    "envoyer",
    "valider",
    "confirmer",
    "soumettre",
    "finaliser",
    "send application",
    "postuler maintenant",
)

POLLUTED_PARTNER_URL_MARKERS: tuple[str, ...] = (
    "apps.apple.com",
    "play.google.com",
    "utm_campaign=poweredby",
    "customer-success-stories",
    "app.teamtailor.com/login",
)


def resolve_ats_adapter(ats: str) -> str:
    """Return a registered adapter key, falling back to ``generic``."""
    return ats if ats in ATS_ADAPTERS else "generic"


def resolve_target_url(row: Any) -> str:
    """Resolve the best external or portal URL for an offer row."""
    partner = str(row_get(row, "partner_url") or "").strip()
    if partner.startswith(("http://", "https://")):
        cleaned_partner = partner.split("&q;", 1)[0].split("&quot;", 1)[0]
        if not any(marker in cleaned_partner.lower() for marker in POLLUTED_PARTNER_URL_MARKERS):
            return cleaned_partner
    notes = str(row_get(row, "notes") or "").strip()
    if notes.startswith(("http://", "https://")):
        return notes.split()[0]
    return str(row_get(row, "url") or "").strip()
