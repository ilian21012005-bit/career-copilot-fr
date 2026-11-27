"""Explicit WAL database handle for the career store (zero module-global context hacks)."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from career_copilot.db.migrations import open_wal_connection, run_migrations

STATUSES: tuple[str, ...] = (
    "new",
    "shortlist",
    "prepared",
    "applied",
    "to_finish",
    "replied",
    "interview",
    "submission_unknown",
    "submission_pending",
    "ignored",
)

MANUAL_APPLICATION_CHANNELS: frozenset[str] = frozenset(
    {"candidature-manuelle", "telegram-manuel", "hellowork-manual"}
)


def now_iso() -> str:
    """Return local timezone-aware ISO-8601 timestamp (seconds precision)."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    """Return local ISO date string (YYYY-MM-DD)."""
    return datetime.now().astimezone().date().isoformat()


@dataclass
class DatabaseHandle:
    """Thread-safe handle to a SQLite WAL database with PRAGMA user_version migrations."""

    db_path_getter: Callable[[], Path]
    data_dir_getter: Callable[[], Path] | None = None
    connect_fn: Callable[[], sqlite3.Connection] | None = None
    init_done: set[tuple[str, int]] = field(default_factory=set)
    _init_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def for_path(
        cls,
        db_path: Path | str,
        *,
        data_dir: Path | str | None = None,
    ) -> DatabaseHandle:
        resolved = Path(db_path)
        resolved_data_dir = Path(data_dir) if data_dir is not None else resolved.parent
        return cls(
            db_path_getter=lambda: resolved,
            data_dir_getter=lambda: resolved_data_dir,
        )

    @property
    def db_path(self) -> Path:
        return Path(self.db_path_getter())

    @property
    def data_dir(self) -> Path:
        if self.data_dir_getter is not None:
            return Path(self.data_dir_getter())
        return self.db_path.parent

    def connect(self) -> sqlite3.Connection:
        if self.connect_fn is not None:
            return self.connect_fn()
        return open_wal_connection(self.db_path, foreign_keys=False)

    @contextmanager
    def db(self) -> Generator[sqlite3.Connection]:
        """Short-lived transactional WAL connection closed on exit."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def session(self, conn: sqlite3.Connection | None = None) -> Generator[sqlite3.Connection]:
        """Reuse an open transaction or start a new one."""
        if conn is not None:
            yield conn
            return
        with self.db() as owned:
            yield owned

    def init(self) -> None:
        """Apply versioned schema migrations once per (resolved_path, inode)."""
        path = self.db_path
        resolved = str(path.resolve())
        with self._init_lock:
            if path.exists():
                try:
                    key = (resolved, path.stat().st_ino)
                    if key in self.init_done:
                        return
                except OSError:
                    pass
            with self.db() as conn:
                run_migrations(conn)
            with suppress(OSError):
                self.init_done.add((resolved, path.stat().st_ino))
