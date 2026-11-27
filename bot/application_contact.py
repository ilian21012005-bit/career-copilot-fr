"""Choix prudent du destinataire d'une candidature automatique."""

from __future__ import annotations

import re
import unicodedata

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
BLOCKED = ('noreply', 'no-reply', 'donotreply', 'exemple.com', 'example.com',
           'francetravail.fr', 'francetravail.io', 'pole-emploi.fr', 'pole-emploi.io', 'poleemploi.fr')


def _fold(text: str) -> str:
    normalized = unicodedata.normalize('NFD', (text or '').lower().replace('’', "'"))
    return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')


def link_only(text: str) -> bool:
    text = _fold(text)
    patterns = (
        r"\b(?:aucune?|pas de|sans)\s+candidature\w*\s+(?:par\s+)?(?:mail|e-?mail|courriel)",
        r"\b(?:candidature\w*|postul\w*)\b.{0,100}\b(?:uniquement|exclusivement)\b.{0,80}\b(?:lien|site|plateforme|formulaire|en ligne)\b",
        r"\b(?:uniquement|exclusivement)\b.{0,60}\b(?:via|sur|par)\b.{0,30}\b(?:lien|site|plateforme|formulaire)\b",
        r"\b(?:candidature\w*|postul\w*)\b.{0,80}\b(?:mail|e-?mail|courriel)\b.{0,60}\b(?:ne sera|ne seront|non traite|refuse)",
        r"\b(?:postulez|postuler|candidature)\s+(?:directement\s+)?(?:sur|via|par)\s+(?:notre\s+|le\s+|la\s+|un\s+)?(?:site|lien|plateforme|formulaire)\b",
    )
    return any(re.search(pattern, text, re.S) for pattern in patterns)


def _usable(address: str) -> bool:
    lowered = address.casefold()
    return not any(part in lowered for part in BLOCKED)


def recipient(description: str, *, contact_email: str = '', contact_text: str = '') -> str:
    """Une adresse du champ candidature ou explicitement associée à un CV."""
    if link_only(f'{contact_text}\n{description}'):
        return ''
    direct = EMAIL_RE.fullmatch((contact_email or '').strip())
    if direct and _usable(direct.group()):
        return direct.group()
    text = f'{contact_text}\n{description}'
    for match in EMAIL_RE.finditer(text):
        if not _usable(match.group()):
            continue
        context = _fold(text[max(0, match.start()-150):match.start()])
        context = re.split(r'[\n;!?]', context)[-1]
        action = re.search(r'\b(?:envoy\w*|adress\w*|transmet\w*|postul\w*|par\s+(?:e-?mail|mail|courriel))\b', context)
        application = re.search(r'\b(?:cv|candidatur\w*|postul\w*|dossier)\b', context)
        if action and application:
            return match.group()
    return ''
