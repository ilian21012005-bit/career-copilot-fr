"""Declarative plugin contract and dependency container for offer sources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourcePlugin:
    """Declarative contract for an offer discovery connector."""

    id: str
    label: str
    commercial_safe: bool
    contracts: tuple[str, ...]
    requires_credentials: bool
    legal_notice: str
    is_enabled: Callable[[dict[str, str]], bool]
    fetch_offers: Callable[[dict[str, str], str], list[dict[str, Any]]]


@dataclass(frozen=True)
class SourcesDeps:
    """Explicit runtime dependencies injected into source registry operations."""

    config: Any
    candidate_config: Any
    filters: Any
    presets: Any
    public_network: Any
    source_common: Any
    geo: Any
    hw_offers: Any
    scoring: Any
    hw_store: Any
    get_plugins: Callable[[], tuple[SourcePlugin, ...]]
