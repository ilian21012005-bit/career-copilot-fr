"""Mémoire locale : qui a déjà été contacté, et quand relancer."""

from __future__ import annotations

import sqlite3
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from config import DB_PATH
from private_storage import ensure_private_directory, protect_private_file

_INIT_LOCK = threading.Lock()
_INIT_DONE: set[tuple[str, int]] = set()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if DB_PATH.parent.is_symlink() or DB_PATH.is_symlink():
        raise ValueError("Base candidatures symbolique interdite")
    if os.name != "nt":
        DB_PATH.parent.chmod(0o700)
    ensure_private_directory(DB_PATH.parent, trusted_root=DB_PATH.parent)
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    protect_private_file(DB_PATH, trusted_root=DB_PATH.parent)
    protect_private_file(Path(f"{DB_PATH}-wal"), trusted_root=DB_PATH.parent)
    protect_private_file(Path(f"{DB_PATH}-shm"), trusted_root=DB_PATH.parent)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init() -> None:
    resolved = str(Path(DB_PATH).resolve())
    with _INIT_LOCK:
        if DB_PATH.exists():
            try:
                key = (resolved, DB_PATH.stat().st_ino)
                if key in _INIT_DONE:
                    return
            except OSError:
                pass
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS targets (
                    id TEXT PRIMARY KEY,
                    campaign TEXT NOT NULL,
                    name TEXT,
                    email TEXT,
                    url TEXT,
                    city TEXT,
                    status TEXT NOT NULL,
                    detail TEXT,
                    first_seen TEXT NOT NULL,
                    emailed_at TEXT,
                    relanced_at TEXT,
                    subject TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    summary TEXT
                )
                """
            )
            columns = {row['name'] for row in conn.execute('PRAGMA table_info(targets)')}
            for name in (
                'send_attempt_at', 'relance_attempt_at', 'title', 'hw_offer_id',
                'attachment_path', 'attachment_hash', 'manual_relanced_at', 'projection_pending',
            ):
                if name not in columns:
                    conn.execute(f'ALTER TABLE targets ADD COLUMN {name} TEXT')
            conn.execute('''CREATE TABLE IF NOT EXISTS mail_queue (
                target_id TEXT PRIMARY KEY, payload TEXT NOT NULL, queued_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending')''')
        try:
            _INIT_DONE.add((resolved, DB_PATH.stat().st_ino))
        except OSError:
            pass


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def get_target(target_id: str) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()


def upsert_seen(target_id: str, campaign: str, name: str, email: str, url: str, city: str, detail: str) -> None:
    with _connect() as conn:
        existing = conn.execute("SELECT id FROM targets WHERE id = ?", (target_id,)).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO targets (id, campaign, name, email, url, city, status, detail, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, 'seen', ?, ?)
            """,
            (target_id, campaign, name, email, url, city, detail, now_iso()),
        )


def mark_emailed(target_id: str, subject: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE targets
            SET status = 'emailed', emailed_at = ?, subject = ?, projection_pending = '1'
            WHERE id = ? AND status = 'sending_unknown'
            """,
            (now_iso(), subject, target_id),
        )


def claim_new_email(target: dict, subject: str, *, global_cap: int | None = None, campaign_cap: int | None = None,
                    attachment_path: str = "", attachment_hash: str = "") -> bool:
    """Atomically reserve a new application before contacting SMTP."""
    with _connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if global_cap is not None and _sent_today_on(conn) >= global_cap:
            return False
        if campaign_cap is not None and _sent_today_on(conn, target['campaign']) >= campaign_cap:
            return False
        stamp = now_iso()
        result = conn.execute(
            """INSERT OR IGNORE INTO targets
               (id, campaign, name, email, url, city, status, detail, first_seen, send_attempt_at, subject,
                title, hw_offer_id, attachment_path, attachment_hash)
               VALUES (?, ?, ?, ?, ?, ?, 'sending_unknown', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (target['key'], target['campaign'], target.get('name', ''), target.get('email', ''),
             target.get('url', ''), target.get('city', ''), target.get('source', ''), stamp, stamp, subject,
             target.get('title', ''), target.get('hw_offer_id', ''), attachment_path, attachment_hash),
        )
        return result.rowcount == 1


MAIL_QUEUE_MAX_DAYS = 7


def _queue_cutoff(max_days: int = MAIL_QUEUE_MAX_DAYS) -> str:
    return (datetime.now().astimezone() - timedelta(days=max_days)).isoformat(timespec='seconds')


def queue_email(target: dict) -> None:
    with _connect() as conn:
        conn.execute("""
            INSERT INTO mail_queue (target_id, payload, queued_at) VALUES (?, ?, ?)
            ON CONFLICT(target_id) DO UPDATE SET payload = excluded.payload,
                queued_at = excluded.queued_at, status = 'pending'
            WHERE mail_queue.status IN ('pending', 'expired') AND mail_queue.queued_at < ?
              AND NOT EXISTS (SELECT 1 FROM targets WHERE id = excluded.target_id)
            """, (target['key'], json.dumps(target, ensure_ascii=False), now_iso(), _queue_cutoff()))


def is_queued(target_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM mail_queue WHERE target_id = ? AND status = 'pending' AND queued_at >= ?",
            (target_id, _queue_cutoff()),
        ).fetchone()
    return row is not None


def pending_email(max_days: int = MAIL_QUEUE_MAX_DAYS) -> list[dict]:
    cutoff = _queue_cutoff(max_days)
    with _connect() as conn:
        rows = conn.execute("""SELECT q.payload FROM mail_queue q
            LEFT JOIN targets t ON t.id = q.target_id
            WHERE q.status = 'pending' AND q.queued_at >= ? AND t.id IS NULL
            ORDER BY q.queued_at, q.target_id""", (cutoff,)).fetchall()
    return [json.loads(row['payload']) for row in rows]


def finish_queue(target_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE mail_queue SET status = 'processed' WHERE target_id = ?", (target_id,))


def mark_relance_unknown(target_id: str, *, global_cap: int | None = None) -> bool:
    with _connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if global_cap is not None and _sent_today_on(conn) >= global_cap:
            return False
        result = conn.execute(
            "UPDATE targets SET status = 'relance_unknown', relance_attempt_at = ? "
            "WHERE id = ? AND status = 'emailed' AND relanced_at IS NULL AND manual_relanced_at IS NULL",
            (now_iso(), target_id),
        )
        return result.rowcount == 1


def mark_manual_relance(url: str, mailto_address: str = "") -> bool | None:
    """True if recorded, False if already sent/uncertain, None if absent from SMTP."""
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """SELECT id, status, manual_relanced_at FROM targets
               WHERE (url = ? OR (? != '' AND COALESCE(url, '') = '' AND lower(email) = lower(?)))
                 AND status IN ('emailed', 'relance_unknown', 'relanced', 'replied')""",
            (url, mailto_address, mailto_address),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1 or rows[0]["status"] != "emailed" or rows[0]["manual_relanced_at"]:
            return False
        conn.execute("UPDATE targets SET manual_relanced_at = ? WHERE id = ?", (now_iso(), rows[0]["id"]))
        return True


def mark_digest(target_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE targets SET status = 'digest' WHERE id = ? AND status = 'seen'", (target_id,))


def mark_relanced(target_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE targets SET status = 'relanced', relanced_at = ? WHERE id = ?",
            (now_iso(), target_id),
        )


def mark_replied(target_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE targets SET status = 'replied' WHERE id = ?", (target_id,))


def uncertain_targets() -> list[sqlite3.Row]:
    with _connect() as conn:
        return list(conn.execute(
            "SELECT * FROM targets WHERE status IN ('sending_unknown', 'relance_unknown') ORDER BY first_seen"
        ))


def resolve_uncertain(target_id: str, sent: bool, *, release_email_claim: bool = False) -> bool:
    """Resolve an uncertain SMTP attempt after checking Gmail's Sent folder."""
    with _connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT status FROM targets WHERE id = ?", (target_id,)).fetchone()
        if not row or row['status'] not in ('sending_unknown', 'relance_unknown'):
            return False
        if row['status'] == 'sending_unknown':
            if sent:
                conn.execute("UPDATE targets SET status = 'emailed', emailed_at = COALESCE(send_attempt_at, ?), "
                             "projection_pending = '1' WHERE id = ?",
                             (now_iso(), target_id))
                conn.execute("UPDATE mail_queue SET status = 'processed' WHERE target_id = ?",
                             (target_id,))
            elif release_email_claim:
                conn.execute("UPDATE targets SET status = 'sending_cancelled', projection_pending = '1' WHERE id = ?",
                             (target_id,))
            else:
                conn.execute("DELETE FROM targets WHERE id = ? AND status = 'sending_unknown'", (target_id,))
                conn.execute("UPDATE mail_queue SET status = 'pending', queued_at = ? WHERE target_id = ?",
                             (now_iso(), target_id))
        elif sent:
            conn.execute("UPDATE targets SET status = 'relanced', relanced_at = COALESCE(relance_attempt_at, ?) WHERE id = ?",
                         (now_iso(), target_id))
        else:
            conn.execute("UPDATE targets SET status = 'emailed', relance_attempt_at = NULL WHERE id = ?", (target_id,))
        return True


def unapplied_mail_projections() -> list[sqlite3.Row]:
    with _connect() as conn:
        return list(conn.execute(
            """SELECT t.*, q.payload AS queue_payload FROM targets t
               LEFT JOIN mail_queue q ON q.target_id = t.id WHERE t.projection_pending = '1'"""
        ))


def finish_mail_projection(target_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE targets SET projection_pending = NULL WHERE id = ?", (target_id,))
        conn.execute("UPDATE mail_queue SET status = 'processed' WHERE target_id = ?", (target_id,))


def finish_cancelled_mail_projection(target_id: str) -> bool:
    with _connect() as conn:
        cancelled = conn.execute(
            "DELETE FROM targets WHERE id = ? AND status = 'sending_cancelled'", (target_id,),
        ).rowcount
        if cancelled:
            conn.execute("UPDATE mail_queue SET status = 'pending', queued_at = ? WHERE target_id = ?",
                         (now_iso(), target_id))
        return bool(cancelled)


def has_cancelled_mail_projection(target_id: str) -> bool:
    with _connect() as conn:
        return conn.execute(
            "SELECT 1 FROM targets WHERE id = ? AND status = 'sending_cancelled'", (target_id,),
        ).fetchone() is not None


def _sent_today_on(conn: sqlite3.Connection, campaign: str | None = None) -> int:
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    query = "SELECT COUNT(*) FROM targets WHERE (emailed_at >= ? OR relanced_at >= ? OR send_attempt_at >= ? OR relance_attempt_at >= ?)"
    params: list[str] = [start, start, start, start]
    if campaign:
        query += " AND campaign = ?"
        params.append(campaign)
    return int(conn.execute(query, params).fetchone()[0])


def sent_today(campaign: str | None = None) -> int:
    with _connect() as conn:
        return _sent_today_on(conn, campaign)


def due_relances(days: int = 7) -> list[sqlite3.Row]:
    limit = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec="seconds")
    with _connect() as conn:
        return list(
            conn.execute(
                """
                SELECT * FROM targets
                WHERE status = 'emailed'
                  AND relanced_at IS NULL
                  AND manual_relanced_at IS NULL
                  AND emailed_at <= ?
                  AND email != ''
                """,
                (limit,),
            )
        )


def ran_recently(min_interval_seconds: int = 3 * 3600) -> bool:
    """Vrai si un cycle réussi s'est terminé aujourd'hui depuis moins de `min_interval_seconds`."""
    interval = max(0, int(min_interval_seconds))
    if interval == 0:
        return False
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT finished_at FROM runs
            WHERE finished_at IS NOT NULL
              AND summary IS NOT NULL
              AND summary NOT LIKE 'Échec du cycle%'
              AND summary NOT LIKE 'Échec%'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    if not row or not row["finished_at"]:
        return False
    now = datetime.now().astimezone()
    then = datetime.fromisoformat(row["finished_at"])
    if then.tzinfo is None:
        then = then.replace(tzinfo=now.tzinfo)
    return then.date() == now.date() and abs((now - then).total_seconds()) < interval


def already_ran_today(min_interval_seconds: int = 3 * 3600) -> bool:
    last = last_success()
    if not last:
        return False
    now = datetime.now().astimezone()
    then = datetime.fromisoformat(last)
    if then.tzinfo is None:
        then = then.replace(tzinfo=now.tzinfo)
    return then.date() == now.date() and abs((now - then).total_seconds()) < min_interval_seconds


def last_success() -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT finished_at FROM runs WHERE finished_at IS NOT NULL AND COALESCE(summary, '') NOT LIKE 'Échec%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["finished_at"] if row else None


def start_run() -> int:
    with _connect() as conn:
        cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now_iso(),))
        return int(cur.lastrowid)


def finish_run(run_id: int, summary: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE runs SET finished_at = ?, summary = ? WHERE id = ?",
            (now_iso(), summary, run_id),
        )


def recent_runs(limit: int = 20) -> list[dict]:
    """Return recent campaign runs with a derived status and duration."""
    limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, started_at, finished_at, summary
            FROM runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        started = row["started_at"]
        finished = row["finished_at"]
        duration_seconds = None
        if started and finished:
            try:
                duration_seconds = max(
                    0,
                    int((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()),
                )
            except ValueError:
                duration_seconds = None
        summary = row["summary"] or ""
        status = "running" if not finished else ("failed" if "échec" in summary.lower() or "erreur" in summary.lower() else "success")
        result.append({
            "id": row["id"],
            "started_at": started,
            "finished_at": finished,
            "duration_seconds": duration_seconds,
            "status": status,
            "summary": summary[-2000:],
        })
    return result
