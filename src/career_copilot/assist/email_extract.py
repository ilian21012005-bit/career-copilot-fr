"""Recruiter e-mail extraction and Île-de-France geographic helpers."""

from __future__ import annotations

import re
from typing import Any

from career_copilot.assist.deps import row_get

_EMAIL_RE = re.compile(r"\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b")

_IGNORED_EMAIL_PREFIXES: tuple[str, ...] = (
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "ne-pas-repondre",
    "nepasrepondre",
    "bounce",
    "mailer-daemon",
    "notification",
    "notifications",
    "rgpd",
    "dpo",
    "privacy",
    "abuse",
    "support",
    "webmaster",
)

_IGNORED_EMAIL_DOMAINS: tuple[str, ...] = (
    "example.com",
    "example.org",
    "exemple.fr",
    "exemple.com",
    "exemple.org",
    "domaine.fr",
    "hellowork.com",
    "linkedin.com",
    "indeed.com",
    "welcometothejungle.com",
    "glassdoor.com",
    "sentry.io",
    "w3.org",
    "schema.org",
)

_PREFERRED_EMAIL_HINTS: tuple[str, ...] = (
    "recrut",
    "rh",
    "hr",
    "talent",
    "career",
    "carriere",
    "jobs",
    "stage",
    "candidat",
    "alternance",
)

_EMAIL_NEGATIVE_CONTEXT: tuple[str, ...] = (
    "impersonation",
    "reported to",
    "report ",
    "usurpation",
    "fraude",
    "phishing",
    "escroquerie",
    "signalement",
    "signaler",
    "protection des donnees",
    "donnees personnelles",
    "data privacy",
    "privacy policy",
    "gdpr",
    "rgpd",
)

_IMAGE_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")

_IDF_DEPARTMENTS: frozenset[str] = frozenset({"75", "77", "78", "91", "92", "93", "94", "95"})
_IDF_ZONES: frozenset[str] = frozenset(
    {
        "idf",
        "paris",
        "proche",
        "ile-de-france",
        "banlieue",
        "petite-couronne",
        "grande-couronne",
    }
)


def _is_valid_recruiter_email(email: str, raw_text: str, start: int, end: int) -> bool:
    local, _, domain = email.partition("@")
    if not local or not domain or domain.endswith(_IMAGE_SUFFIXES):
        return False
    if any(
        local == prefix or local.startswith((f"{prefix}+", f"{prefix}."))
        for prefix in _IGNORED_EMAIL_PREFIXES
    ):
        return False
    if any(
        domain == blocked or domain.endswith(f".{blocked}") for blocked in _IGNORED_EMAIL_DOMAINS
    ):
        return False
    ctx = raw_text[max(0, start - 140) : min(len(raw_text), end + 80)].lower()
    return not any(marker in ctx for marker in _EMAIL_NEGATIVE_CONTEXT)


def extract_public_recruiter_email(*texts: str) -> str:
    """Extract a credible public recruiter e-mail address from offer texts."""
    candidates: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        raw_text = str(text)
        for match in _EMAIL_RE.finditer(raw_text):
            email = match.group(1).strip().lower().rstrip(".,;:")
            if email in seen:
                continue
            if not _is_valid_recruiter_email(email, raw_text, match.start(), match.end()):
                continue
            seen.add(email)
            candidates.append(email)

    if not candidates:
        return ""
    for email in candidates:
        local = email.split("@", 1)[0]
        if any(hint in local for hint in _PREFERRED_EMAIL_HINTS):
            return email
    return candidates[0]


def is_idf_offer(row: Any) -> bool:
    """Return ``True`` if the offer is located in Île-de-France or within 50 km."""
    zone = str(row_get(row, "zone") or "").strip().lower()
    if zone in _IDF_ZONES or "idf" in zone or "paris" in zone:
        return True
    dept = str(row_get(row, "department") or "").strip()
    if any(dept.startswith(prefix) for prefix in _IDF_DEPARTMENTS):
        return True
    dist = row_get(row, "distance_km")
    if dist is not None:
        try:
            return float(dist) <= 50.0
        except (TypeError, ValueError):
            return False
    return False
