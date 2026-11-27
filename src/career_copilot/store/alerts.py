"""Read-mail tracking and alert link/offer retry queue operations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from career_copilot.store.connection import DatabaseHandle, now_iso


def mail_seen(handle: DatabaseHandle, message_id: str) -> bool:
    with handle.db() as conn:
        return (
            conn.execute("SELECT 1 FROM mails WHERE message_id = ?", (message_id,)).fetchone()
            is not None
        )


def mail_kind(handle: DatabaseHandle, message_id: str) -> str:
    with handle.db() as conn:
        row = conn.execute("SELECT kind FROM mails WHERE message_id = ?", (message_id,)).fetchone()
    return str(row["kind"] or "") if row else ""


def has_alert_history(handle: DatabaseHandle) -> bool:
    with handle.db() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM mails WHERE kind IN ('alert', 'alert_done') LIMIT 1"
            ).fetchone()
            is not None
        )


def remember_mail(
    handle: DatabaseHandle,
    message_id: str,
    kind: str,
    company: str,
    subject: str,
) -> None:
    with handle.db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO mails (message_id, seen_at, kind, company, subject) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, now_iso(), kind, company, subject),
        )


def set_mail_kind(handle: DatabaseHandle, message_id: str, kind: str) -> None:
    with handle.db() as conn:
        conn.execute("UPDATE mails SET kind = ? WHERE message_id = ?", (kind, message_id))


def queue_alert_offer(handle: DatabaseHandle, message_id: str, offer_id: str, url: str) -> None:
    with handle.db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO alert_offers (message_id, offer_id, url, queued_at)
               VALUES (?, ?, ?, ?)""",
            (message_id, offer_id, url, now_iso()),
        )


def queue_alert_link(handle: DatabaseHandle, message_id: str, url: str) -> None:
    with handle.db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO alert_links (message_id, url, queued_at) VALUES (?, ?, ?)",
            (message_id, url, now_iso()),
        )


def pending_alert_links(handle: DatabaseHandle, limit: int = 20) -> list[sqlite3.Row]:
    with handle.db() as conn:
        return list(
            conn.execute(
                """SELECT message_id, url FROM alert_links
                   WHERE status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   ORDER BY attempts, queued_at LIMIT ?""",
                (now_iso(), max(1, int(limit))),
            )
        )


def resolve_alert_link(handle: DatabaseHandle, message_id: str, url: str, offer_id: str) -> None:
    offer_url = f"https://www.hellowork.com/fr-fr/emplois/{offer_id}.html"
    with handle.db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO alert_offers (message_id, offer_id, url, queued_at)
               VALUES (?, ?, ?, ?)""",
            (message_id, offer_id, offer_url, now_iso()),
        )
        conn.execute(
            """UPDATE alert_links SET status = 'done', offer_id = ?, last_error = ''
               WHERE message_id = ? AND url = ?""",
            (offer_id, message_id, url),
        )


def retry_alert_link(handle: DatabaseHandle, message_id: str, url: str, error: str) -> None:
    with handle.db() as conn:
        row = conn.execute(
            "SELECT attempts FROM alert_links WHERE message_id = ? AND url = ? AND status = 'pending'",
            (message_id, url),
        ).fetchone()
        if row is None:
            return
        attempts = int(row["attempts"]) + 1
        hours = 1 if attempts == 1 else (4 if attempts == 2 else 24)
        next_at = (datetime.now().astimezone() + timedelta(hours=hours)).isoformat(
            timespec="seconds"
        )
        conn.execute(
            """UPDATE alert_links SET attempts = ?, next_attempt_at = ?, last_error = ?
               WHERE message_id = ? AND url = ?""",
            (attempts, next_at, error[:1000], message_id, url),
        )


def pending_alert_urls(handle: DatabaseHandle, limit: int = 20) -> list[sqlite3.Row]:
    now = now_iso()
    with handle.db() as conn:
        return list(
            conn.execute(
                """SELECT offer_id, MIN(url) AS url, MIN(queued_at) AS queued_at,
                          MIN(attempts) AS attempts
                   FROM alert_offers
                   WHERE status = 'pending' AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   GROUP BY offer_id
                   ORDER BY attempts, queued_at
                   LIMIT ?""",
                (now, max(1, int(limit))),
            )
        )


def resolve_alert_offer(handle: DatabaseHandle, offer_id: str) -> None:
    with handle.db() as conn:
        conn.execute(
            "UPDATE alert_offers SET status = 'done', last_error = '' WHERE offer_id = ?",
            (offer_id,),
        )


def retry_alert_offer(handle: DatabaseHandle, offer_id: str, error: str) -> None:
    with handle.db() as conn:
        rows = conn.execute(
            "SELECT message_id, attempts FROM alert_offers WHERE offer_id = ? AND status = 'pending'",
            (offer_id,),
        ).fetchall()
        for row in rows:
            attempts = int(row["attempts"]) + 1
            hours = 1 if attempts == 1 else (4 if attempts == 2 else 24)
            next_at = (datetime.now().astimezone() + timedelta(hours=hours)).isoformat(
                timespec="seconds"
            )
            conn.execute(
                """UPDATE alert_offers SET attempts = ?, next_attempt_at = ?, last_error = ?
                   WHERE message_id = ? AND offer_id = ?""",
                (attempts, next_at, error[:1000], row["message_id"], offer_id),
            )
