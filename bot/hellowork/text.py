"""Petits utilitaires de texte partagés."""

from __future__ import annotations

import re
import unicodedata


def fold(text: str) -> str:
    """Minuscules sans accents, pour comparer des mots."""
    normalized = unicodedata.normalize("NFD", text or "")
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", stripped).strip().lower()


def has(text: str, word: str) -> bool:
    """Vrai si `word` apparaît comme mot entier (accents et casse ignorés)."""
    needle = fold(word)
    if not needle:
        return False
    return re.search(rf"(^|[^a-z0-9]){re.escape(needle)}([^a-z0-9]|$)", fold(text)) is not None


def clean_lines(text: str) -> list[str]:
    lines = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" \t•|-–—")
        if len(line) >= 2:
            lines.append(line)
    return lines


def shorten(text: str, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"
