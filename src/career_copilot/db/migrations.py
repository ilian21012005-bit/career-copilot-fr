"""SQLite WAL connection factory and PRAGMA user_version migration runner."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from career_copilot.fs_privacy import ensure_private_directory, protect_private_file


@dataclass(frozen=True)
class Migration:
    """Single versioned schema migration applied atomically."""

    version: int
    name: str
    sql: str = ""
    apply_fn: Callable[[sqlite3.Connection], None] | None = None


def open_wal_connection(
    db_path: Path | str,
    *,
    timeout: float = 5.0,
    foreign_keys: bool = True,
) -> sqlite3.Connection:
    """Open a private SQLite connection configured for WAL mode."""
    target = Path(db_path)
    if target.parent.is_symlink():
        raise ValueError("Répertoire de base SQLite symbolique interdit")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        target.parent.chmod(0o700)
    ensure_private_directory(target.parent, trusted_root=target.parent)
    if target.is_symlink():
        raise ValueError("Base SQLite symbolique interdite")

    conn = sqlite3.connect(target, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-8000")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys=ON")

    protect_private_file(target, trusted_root=target.parent)
    protect_private_file(Path(f"{target}-wal"), trusted_root=target.parent)
    protect_private_file(Path(f"{target}-shm"), trusted_root=target.parent)
    return conn


@contextmanager
def wal_session(
    db_path: Path | str,
    *,
    timeout: float = 5.0,
    foreign_keys: bool = True,
) -> Generator[sqlite3.Connection]:
    """Open a short-lived WAL connection with commit/rollback and guaranteed close."""
    conn = open_wal_connection(db_path, timeout=timeout, foreign_keys=foreign_keys)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def current_version(conn: sqlite3.Connection) -> int:
    """Read SQLite PRAGMA user_version."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row is not None else 0


def _apply_sql_statements(conn: sqlite3.Connection, sql: str) -> None:
    """Execute semicolon-separated DDL/DML statements inside the active transaction."""
    buffer = ""
    for piece in sql.split(";"):
        chunk = piece.strip()
        if not chunk and not buffer:
            continue
        buffer = f"{buffer}{piece};"
        if sqlite3.complete_statement(buffer):
            stmt = buffer.strip()
            if stmt and stmt != ";":
                conn.execute(stmt)
            buffer = ""
    remainder = buffer.strip()
    if remainder and remainder != ";":
        conn.execute(remainder)


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_def: str,
) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")


def _migrate_v2_columns_and_backfills(conn: sqlite3.Connection) -> None:
    """Idempotently add v2 columns and normalize legacy redirect statuses."""
    for column, column_def in (
        ("external_id", "TEXT"),
        ("proof_kind", "TEXT"),
        ("proof_reference", "TEXT"),
    ):
        _ensure_column(conn, "applications", column, column_def)

    conn.execute(
        "UPDATE applications SET status = 'to_finish' "
        "WHERE channel = 'hellowork-redirect' AND status = 'sent'"
    )

    for column, column_def in (
        ("offer_fingerprint", "TEXT"),
        ("cv_sha256", "TEXT"),
        ("letter_sha256", "TEXT"),
        ("profile_fingerprint", "TEXT"),
    ):
        _ensure_column(conn, "kits", column, column_def)

    for column, column_def in (
        ("latitude", "REAL"),
        ("longitude", "REAL"),
        ("zone", "TEXT"),
        ("distance_km", "REAL"),
        ("location_status", "TEXT DEFAULT 'unknown'"),
        ("partner_url", "TEXT"),
        ("apply_capability", "TEXT"),
        ("partner_checked_at", "TEXT"),
    ):
        _ensure_column(conn, "offers", column, column_def)


_V1_CORE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS offers (
    id TEXT PRIMARY KEY,
    url TEXT,
    title TEXT,
    company TEXT,
    city TEXT,
    department TEXT,
    contract TEXT,
    posted_at TEXT,
    salary TEXT,
    description TEXT,
    missions TEXT,
    profile TEXT,
    benefits TEXT,
    apply_mode TEXT,
    score INTEGER NOT NULL DEFAULT 0,
    score_parts TEXT,
    reasons TEXT,
    gaps TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    notes TEXT,
    latitude REAL,
    longitude REAL,
    zone TEXT,
    distance_km REAL,
    location_status TEXT DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS email_submission_claims (
    offer_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kits (
    offer_id TEXT PRIMARY KEY,
    subject TEXT,
    letter_path TEXT,
    cv_path TEXT,
    dossier_path TEXT,
    created_at TEXT NOT NULL,
    offer_fingerprint TEXT,
    cv_sha256 TEXT,
    letter_sha256 TEXT,
    profile_fingerprint TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id TEXT,
    company TEXT,
    title TEXT,
    applied_at TEXT NOT NULL,
    channel TEXT NOT NULL,
    evidence TEXT,
    external_id TEXT,
    proof_kind TEXT,
    proof_reference TEXT,
    status TEXT NOT NULL DEFAULT 'sent'
);

CREATE TABLE IF NOT EXISTS application_excel_projection (
    offer_id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    offer_id TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS mails (
    message_id TEXT PRIMARY KEY,
    seen_at TEXT NOT NULL,
    kind TEXT,
    company TEXT,
    subject TEXT
);

CREATE TABLE IF NOT EXISTS alert_offers (
    message_id TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    url TEXT NOT NULL,
    queued_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (message_id, offer_id)
);

CREATE TABLE IF NOT EXISTS alert_links (
    message_id TEXT NOT NULL,
    url TEXT NOT NULL,
    queued_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    offer_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    PRIMARY KEY (message_id, url)
);

CREATE TABLE IF NOT EXISTS plan (
    day TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    PRIMARY KEY (day, offer_id)
);
"""

_V3_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS alert_offers_pending
    ON alert_offers(status, next_attempt_at, attempts, queued_at);

CREATE INDEX IF NOT EXISTS alert_links_pending
    ON alert_links(status, next_attempt_at, attempts, queued_at);

CREATE INDEX IF NOT EXISTS offers_candidate_order
    ON offers(score DESC, first_seen DESC, id DESC)
    WHERE status IN ('new', 'shortlist', 'prepared');

CREATE INDEX IF NOT EXISTS offers_by_url
    ON offers(url) WHERE url IS NOT NULL AND url != '';

CREATE INDEX IF NOT EXISTS offers_by_status_score
    ON offers(status, score DESC, first_seen DESC);

CREATE INDEX IF NOT EXISTS applications_active_offer
    ON applications(offer_id) WHERE status != 'withdrawn';

CREATE INDEX IF NOT EXISTS events_by_offer_at
    ON events(offer_id, at DESC);
"""

_V4_RUNS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_seconds REAL,
    summary TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '',
    synced_messages INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS runs_by_started_at
    ON runs(started_at DESC, id DESC);
"""

CAREER_MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="core_tables", sql=_V1_CORE_TABLES_SQL),
    Migration(
        version=2,
        name="legacy_columns_and_redirect_status",
        apply_fn=_migrate_v2_columns_and_backfills,
    ),
    Migration(version=3, name="query_indexes", sql=_V3_INDEXES_SQL),
    Migration(version=4, name="runs_table", sql=_V4_RUNS_TABLE_SQL),
)

LATEST_SCHEMA_VERSION = CAREER_MIGRATIONS[-1].version


def run_migrations(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] = CAREER_MIGRATIONS,
) -> list[int]:
    """Apply all pending versioned migrations in order using PRAGMA user_version."""
    ordered = sorted(migrations, key=lambda item: item.version)
    seen: set[int] = set()
    for item in ordered:
        if item.version <= 0:
            raise ValueError(f"Numéro de migration invalide : {item.version}")
        if item.version in seen:
            raise ValueError(f"Numéro de migration dupliqué : {item.version}")
        seen.add(item.version)

    version = current_version(conn)
    applied: list[int] = []
    for item in ordered:
        if item.version <= version:
            continue
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        try:
            if item.sql:
                _apply_sql_statements(conn, item.sql)
            if item.apply_fn is not None:
                item.apply_fn(conn)
            conn.execute(f"PRAGMA user_version = {int(item.version)}")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        version = item.version
        applied.append(item.version)
    return applied


def ensure_migrated(
    db_path: Path | str,
    migrations: Sequence[Migration] = CAREER_MIGRATIONS,
) -> int:
    """Open a WAL connection, apply pending migrations, and return final schema version."""
    with wal_session(db_path) as conn:
        run_migrations(conn, migrations=migrations)
        return current_version(conn)
