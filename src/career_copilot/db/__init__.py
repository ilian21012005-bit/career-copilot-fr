"""Database layer: SQLite WAL connections and PRAGMA user_version migrations."""

from __future__ import annotations

from .migrations import (
    CAREER_MIGRATIONS,
    LATEST_SCHEMA_VERSION,
    Migration,
    current_version,
    ensure_migrated,
    open_wal_connection,
    run_migrations,
    wal_session,
)

__all__ = [
    "CAREER_MIGRATIONS",
    "LATEST_SCHEMA_VERSION",
    "Migration",
    "current_version",
    "ensure_migrated",
    "open_wal_connection",
    "run_migrations",
    "wal_session",
]
