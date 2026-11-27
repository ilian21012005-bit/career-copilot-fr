"""Unit tests for SQLite WAL connections and PRAGMA user_version migrations."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from career_copilot.db.migrations import (
    CAREER_MIGRATIONS,
    LATEST_SCHEMA_VERSION,
    Migration,
    current_version,
    ensure_migrated,
    open_wal_connection,
    run_migrations,
    wal_session,
)


class MigrationsTest(unittest.TestCase):
    def test_open_wal_connection_sets_pragmas_and_private_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "private" / "career.db"
            with wal_session(db_path) as conn:
                mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
                fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
                sync = conn.execute("PRAGMA synchronous").fetchone()[0]
            self.assertEqual(str(mode).lower(), "wal")
            self.assertEqual(int(fk), 1)
            self.assertEqual(int(sync), 1)
            if os.name != "nt":
                self.assertEqual(db_path.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(db_path.stat().st_mode & 0o777, 0o600)

    def test_open_wal_connection_refuses_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            real_db = Path(tmp) / "real.db"
            real_db.write_bytes(b"")
            link_db = Path(tmp) / "link.db"
            link_db.symlink_to(real_db)
            with self.assertRaises(ValueError):
                open_wal_connection(link_db)

    def test_ensure_migrated_applies_all_versions_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "career.db"
            version = ensure_migrated(db_path)
            self.assertEqual(version, LATEST_SCHEMA_VERSION)

            with wal_session(db_path) as conn:
                self.assertEqual(current_version(conn), LATEST_SCHEMA_VERSION)
                second = run_migrations(conn)
                self.assertEqual(second, [])
                tables = {
                    row["name"]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
                for expected in (
                    "offers",
                    "kits",
                    "applications",
                    "events",
                    "mails",
                    "alert_offers",
                    "alert_links",
                    "plan",
                    "email_submission_claims",
                    "application_excel_projection",
                ):
                    self.assertIn(expected, tables)

    def test_legacy_unversioned_db_upgrades_cleanly_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE offers (
                    id TEXT PRIMARY KEY,
                    url TEXT,
                    title TEXT,
                    company TEXT,
                    score INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'new',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
                CREATE TABLE applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    offer_id TEXT,
                    company TEXT,
                    title TEXT,
                    applied_at TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    evidence TEXT,
                    status TEXT NOT NULL DEFAULT 'sent'
                );
                CREATE TABLE kits (
                    offer_id TEXT PRIMARY KEY,
                    subject TEXT,
                    letter_path TEXT,
                    cv_path TEXT,
                    dossier_path TEXT,
                    created_at TEXT NOT NULL
                );
                INSERT INTO offers (id, title, company, score, status, first_seen, last_seen)
                VALUES ('o-1', 'Stage Réseau', 'Exemple SAS', 88, 'new', '2026-11-01', '2026-11-01');
                INSERT INTO applications (offer_id, company, title, applied_at, channel, status)
                VALUES ('o-1', 'Exemple SAS', 'Stage Réseau', '2026-11-02', 'hellowork-redirect', 'sent');
                """
            )
            conn.commit()
            conn.close()

            final_version = ensure_migrated(db_path)
            self.assertEqual(final_version, LATEST_SCHEMA_VERSION)

            with wal_session(db_path) as upgraded:
                offer_cols = {row["name"] for row in upgraded.execute("PRAGMA table_info(offers)")}
                self.assertIn("partner_checked_at", offer_cols)
                self.assertIn("apply_capability", offer_cols)
                app_row = upgraded.execute(
                    "SELECT status FROM applications WHERE offer_id = 'o-1'"
                ).fetchone()
                self.assertEqual(app_row["status"], "to_finish")

    def test_failed_migration_rolls_back_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rollback.db"
            broken = (
                Migration(version=1, name="ok", sql="CREATE TABLE t1 (id INTEGER PRIMARY KEY);"),
                Migration(
                    version=2,
                    name="boom",
                    sql="CREATE TABLE t2 (id INTEGER PRIMARY KEY); INSERT INTO missing_table VALUES (1);",
                ),
            )
            with wal_session(db_path) as conn:
                with self.assertRaises(sqlite3.OperationalError):
                    run_migrations(conn, migrations=broken)
                self.assertEqual(current_version(conn), 1)
                tables = {
                    row["name"]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
                }
                self.assertIn("t1", tables)
                self.assertNotIn("t2", tables)

    def test_duplicate_or_invalid_migration_versions_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "invalid.db"
            with wal_session(db_path) as conn:
                with self.assertRaises(ValueError):
                    run_migrations(conn, migrations=(Migration(version=0, name="zero"),))
                with self.assertRaises(ValueError):
                    run_migrations(
                        conn,
                        migrations=(
                            Migration(version=1, name="a"),
                            Migration(version=1, name="b"),
                        ),
                    )
                self.assertGreaterEqual(len(CAREER_MIGRATIONS), 3)


if __name__ == "__main__":
    unittest.main()
