"""Offer persistence, filtering, status transitions, and event logging."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from typing import Any

from career_copilot.store.connection import STATUSES, DatabaseHandle, now_iso


def event(
    handle: DatabaseHandle,
    kind: str,
    offer_id: str = "",
    detail: str = "",
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Append an audit event row."""
    with handle.session(conn) as db:
        db.execute(
            "INSERT INTO events (at, kind, offer_id, detail) VALUES (?, ?, ?, ?)",
            (now_iso(), kind, offer_id, detail),
        )


def save_offer(handle: DatabaseHandle, offer: Any, score: Any) -> str:
    """Insert or update an offer without overwriting its existing lifecycle status."""
    stamp = now_iso()
    geo = (
        getattr(offer, "latitude", None),
        getattr(offer, "longitude", None),
        getattr(offer, "zone", "") or "",
        getattr(offer, "distance_km", None),
        getattr(offer, "location_status", "") or "unknown",
    )
    with handle.db() as conn:
        row = conn.execute(
            "SELECT status, first_seen FROM offers WHERE id = ?", (offer.id,)
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO offers (id, url, title, company, city, department, contract,
                    posted_at, salary, description, missions, profile, benefits, apply_mode,
                    score, score_parts, reasons, gaps, status, first_seen, last_seen,
                    latitude, longitude, zone, distance_km, location_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?,
                    ?, ?, ?, ?, ?)
                """,
                (
                    offer.id,
                    offer.url,
                    offer.title,
                    offer.company,
                    offer.city,
                    offer.department,
                    offer.contract,
                    offer.posted_at,
                    offer.salary,
                    offer.description,
                    offer.missions,
                    offer.profile,
                    offer.benefits,
                    offer.apply_mode,
                    score.value,
                    json.dumps(score.parts, ensure_ascii=False),
                    json.dumps(score.reasons, ensure_ascii=False),
                    json.dumps(score.gaps, ensure_ascii=False),
                    stamp,
                    stamp,
                    *geo,
                ),
            )
            return "new"
        conn.execute(
            """
            UPDATE offers SET url = ?, title = ?, company = ?, city = ?, department = ?,
                contract = ?, posted_at = ?, salary = ?, description = ?, missions = ?,
                profile = ?, benefits = ?, apply_mode = ?, score = ?, score_parts = ?,
                reasons = ?, gaps = ?, last_seen = ?,
                latitude = ?, longitude = ?, zone = ?, distance_km = ?, location_status = ?
            WHERE id = ?
            """,
            (
                offer.url,
                offer.title,
                offer.company,
                offer.city,
                offer.department,
                offer.contract,
                offer.posted_at,
                offer.salary,
                offer.description,
                offer.missions,
                offer.profile,
                offer.benefits,
                offer.apply_mode,
                score.value,
                json.dumps(score.parts, ensure_ascii=False),
                json.dumps(score.reasons, ensure_ascii=False),
                json.dumps(score.gaps, ensure_ascii=False),
                stamp,
                *geo,
                offer.id,
            ),
        )
        return str(row["status"])


def set_apply_capability(
    handle: DatabaseHandle,
    offer_id: str,
    capability: str,
    *,
    only_if_empty: bool = False,
) -> None:
    """Set `apply_capability` for an offer, optionally preserving existing non-empty values."""
    cap = str(capability or "").strip()
    if not offer_id or not cap:
        return
    with handle.db() as conn:
        if only_if_empty:
            conn.execute(
                """
                UPDATE offers
                   SET apply_capability = ?
                 WHERE id = ?
                   AND (apply_capability IS NULL OR apply_capability = '')
                """,
                (cap, offer_id),
            )
        else:
            conn.execute(
                "UPDATE offers SET apply_capability = ? WHERE id = ?",
                (cap, offer_id),
            )


def get(
    handle: DatabaseHandle,
    offer_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> sqlite3.Row | None:
    with handle.session(conn) as db:
        return db.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()


def by_url(handle: DatabaseHandle, url: str) -> sqlite3.Row | None:
    with handle.db() as conn:
        return conn.execute("SELECT * FROM offers WHERE url = ?", (url,)).fetchone()


def list_offers(
    handle: DatabaseHandle,
    status: str | None = None,
    min_score: int = 0,
    limit: int = 200,
    zone: str | None = None,
    location: str | None = None,
    *,
    eligible: bool = False,
    require_kit: bool = False,
    exclude_capabilities: tuple[str, ...] = (),
    after: tuple[int, str, str] | None = None,
) -> list[sqlite3.Row]:
    query = "SELECT * FROM offers WHERE score >= ?"
    params: list[Any] = [min_score]
    if status:
        query += " AND status = ?"
        params.append(status)
    if zone:
        query += " AND zone = ? AND location_status = 'in_zone'"
        params.append(zone)
    if location:
        query += " AND location_status = ?"
        params.append(location)
    if eligible:
        query += """ AND status IN ('new', 'shortlist', 'prepared')
                     AND NOT EXISTS (SELECT 1 FROM applications a
                                     WHERE a.offer_id = offers.id AND a.status != 'withdrawn')
                     AND NOT EXISTS (SELECT 1 FROM email_submission_claims c WHERE c.offer_id = offers.id)"""
    if require_kit:
        query += " AND EXISTS (SELECT 1 FROM kits k WHERE k.offer_id = offers.id)"
    if exclude_capabilities:
        placeholders = ",".join("?" for _ in exclude_capabilities)
        query += f" AND COALESCE(apply_capability, '') NOT IN ({placeholders})"
        params.extend(exclude_capabilities)
    if after is not None:
        query += " AND (score, first_seen, id) < (?, ?, ?)"
        params.extend(after)
    query += " ORDER BY score DESC, first_seen DESC, id DESC LIMIT ?"
    params.append(limit)
    with handle.db() as conn:
        return list(conn.execute(query, params))


def zone_counts(handle: DatabaseHandle) -> dict[str, int]:
    with handle.db() as conn:
        rows = conn.execute(
            """
            SELECT CASE
                     WHEN location_status = 'in_zone' THEN zone
                     WHEN location_status = 'unknown' THEN 'à vérifier'
                     ELSE 'hors zone'
                   END AS label,
                   COUNT(*) AS n
            FROM offers GROUP BY label ORDER BY n DESC
            """
        ).fetchall()
    return {str(row["label"]): int(row["n"]) for row in rows}


def set_status(
    handle: DatabaseHandle,
    offer_id: str,
    status: str,
    note: str = "",
    *,
    conn: sqlite3.Connection | None = None,
    expected_statuses: tuple[str, ...] | None = None,
) -> bool:
    """Update offer status (with optional optimistic status guard) and record an event."""
    if status not in STATUSES:
        raise ValueError(f"statut inconnu : {status} (choix : {', '.join(STATUSES)})")
    condition = ""
    expected = () if expected_statuses is None else tuple(expected_statuses)
    if expected_statuses is not None:
        if not expected:
            return False
        placeholders = ",".join("?" for _ in expected)
        condition = f" AND status IN ({placeholders})"
    with handle.session(conn) as db:
        if note:
            sql = f"UPDATE offers SET status = ?, notes = ? WHERE id = ?{condition}"  # noqa: S608
            cursor = db.execute(sql, (status, note, offer_id, *expected))
        else:
            sql = f"UPDATE offers SET status = ? WHERE id = ?{condition}"  # noqa: S608
            cursor = db.execute(sql, (status, offer_id, *expected))
        updated = cursor.rowcount > 0
        if updated:
            event(handle, status, offer_id, note, conn=db)
        return updated


def mark_to_finish_from_alert(handle: DatabaseHandle, offer_id: str) -> bool:
    """Mark an offer `to_finish` without downgrading confirmed or ignored offers."""
    with handle.db() as conn:
        cursor = conn.execute(
            "UPDATE offers SET status = 'to_finish', notes = 'à finaliser chez le recruteur' "
            "WHERE id = ? AND status IN ('new', 'shortlist', 'prepared', 'to_finish') "
            "AND NOT EXISTS (SELECT 1 FROM applications "
            "WHERE offer_id = ? AND status = 'sent')",
            (offer_id, offer_id),
        )
    return cursor.rowcount > 0


def counts(handle: DatabaseHandle) -> dict[str, int]:
    with handle.db() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM offers GROUP BY status").fetchall()
    return {str(row["status"]): int(row["n"]) for row in rows}


def mark_partner_checked(
    handle: DatabaseHandle,
    offer_ids: list[str] | tuple[str, ...],
    checked_at: str | None = None,
) -> None:
    """Batch-update `partner_checked_at` after ATS liveness probes."""
    ids = [str(oid) for oid in offer_ids if oid]
    if not ids:
        return
    stamp = checked_at or now_iso()
    with handle.db() as conn:
        conn.executemany(
            "UPDATE offers SET partner_checked_at = ? WHERE id = ?",
            [(stamp, oid) for oid in ids],
        )


def skip(
    handle: DatabaseHandle,
    offer_id: str,
    note: str = "",
    *,
    mark_plan_fn: Callable[[str, str], None] | None = None,
) -> None:
    """Ignore an offer and mark it skipped in today's plan."""
    from career_copilot.store import plan as plan_mod

    row = get(handle, offer_id)
    set_status(handle, offer_id, "ignored", note)
    if mark_plan_fn is not None:
        mark_plan_fn(offer_id, "skipped")
    else:
        plan_mod.mark_plan(handle, offer_id, "skipped")
    if row:
        event(handle, "skipped", offer_id, f"{row['company']} — {note}")
