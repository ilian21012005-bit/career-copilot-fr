"""Typed dependency container and row helpers for assisted application flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AssistDeps:
    """Explicit runtime dependencies injected by callers or legacy shims."""

    store: Any
    offers: Any
    scoring: Any
    kit: Any
    profile: Any
    offer_letters: Any


def row_get(row: Any, key: str, default: Any = None) -> Any:
    """Read a field from a mapping or ``sqlite3.Row`` without raising ``AttributeError``."""
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def offer_from_row_safe(row: Any, offer_cls: Any) -> Any:
    """Build an ``Offer`` instance even from a partial mapping or SQLite row."""
    return offer_cls(
        id=str(row_get(row, "id") or ""),
        url=str(row_get(row, "url") or ""),
        title=str(row_get(row, "title") or ""),
        company=str(row_get(row, "company") or ""),
        city=str(row_get(row, "city") or ""),
        department=str(row_get(row, "department") or ""),
        contract=str(row_get(row, "contract") or ""),
        posted_at=str(row_get(row, "posted_at") or ""),
        salary=str(row_get(row, "salary") or ""),
        missions=str(row_get(row, "missions") or ""),
        profile=str(row_get(row, "profile") or ""),
        benefits=str(row_get(row, "benefits") or ""),
        description=str(row_get(row, "description") or ""),
        apply_mode=str(row_get(row, "apply_mode") or "hellowork"),
        latitude=row_get(row, "latitude"),
        longitude=row_get(row, "longitude"),
        zone=str(row_get(row, "zone") or ""),
        distance_km=row_get(row, "distance_km"),
        location_status=str(row_get(row, "location_status") or "unknown"),
    )
