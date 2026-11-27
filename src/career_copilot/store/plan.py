"""Daily application queue (plan table) operations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from career_copilot.store.connection import DatabaseHandle, today


def set_plan(
    handle: DatabaseHandle,
    offer_ids: list[str],
    day: str | None = None,
) -> None:
    """Replace the daily queue with ordered offer IDs, preserving prior statuses."""
    target_day = day or today()
    with handle.db() as conn:
        previous = {
            row["offer_id"]: row["status"]
            for row in conn.execute(
                "SELECT offer_id, status FROM plan WHERE day = ?", (target_day,)
            )
        }
        conn.execute("DELETE FROM plan WHERE day = ?", (target_day,))
        for position, offer_id in enumerate(offer_ids, start=1):
            conn.execute(
                "INSERT INTO plan (day, offer_id, position, status) VALUES (?, ?, ?, ?)",
                (target_day, offer_id, position, previous.get(offer_id, "planned")),
            )


def plan_for(
    handle: DatabaseHandle,
    day: str | None = None,
) -> list[sqlite3.Row]:
    target_day = day or today()
    with handle.db() as conn:
        return list(
            conn.execute(
                """
                SELECT p.position, p.status AS plan_status, o.*
                FROM plan p JOIN offers o ON o.id = p.offer_id
                WHERE p.day = ? ORDER BY p.position
                """,
                (target_day,),
            )
        )


def plan_count(handle: DatabaseHandle, day: str | None = None) -> int:
    target_day = day or today()
    with handle.db() as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM plan WHERE day = ?", (target_day,)).fetchone()[0]
        )


def mark_plan(
    handle: DatabaseHandle,
    offer_id: str,
    status: str,
    day: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    target_day = day or today()
    with handle.session(conn) as db:
        db.execute(
            "UPDATE plan SET status = ? WHERE day = ? AND offer_id = ?",
            (status, target_day, offer_id),
        )


def cleanup_stale_planned(
    handle: DatabaseHandle,
    db_path: Path | None = None,
) -> int:
    """Align stale `planned` rows when the underlying offer is already `applied` or `ignored`."""

    def _apply(conn: sqlite3.Connection) -> int:
        cur1 = conn.execute(
            "UPDATE plan SET status = 'applied' "
            "WHERE status = 'planned' AND offer_id IN ("
            "SELECT id FROM offers WHERE status = 'applied'"
            ")"
        )
        cur2 = conn.execute(
            "UPDATE plan SET status = 'skipped' "
            "WHERE status = 'planned' AND offer_id IN ("
            "SELECT id FROM offers WHERE status = 'ignored'"
            ")"
        )
        return int(cur1.rowcount or 0) + int(cur2.rowcount or 0)

    if db_path is not None:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            with conn:
                return _apply(conn)
        finally:
            conn.close()
    with handle.db() as conn:
        return _apply(conn)
