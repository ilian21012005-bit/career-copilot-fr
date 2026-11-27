"""Submission claims, manual declarations, reconciliation, and Excel projections."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from career_copilot.store import applications as apps_mod
from career_copilot.store import offers as offers_mod
from career_copilot.store import plan as plan_mod
from career_copilot.store.connection import (
    MANUAL_APPLICATION_CHANNELS,
    DatabaseHandle,
    now_iso,
    today,
)


def declare_manual_application(
    handle: DatabaseHandle,
    offer_id: str,
    *,
    channel: str,
    note: str = "",
    applied_at: str = "",
    allow_existing: bool = True,
) -> bool:
    if channel not in MANUAL_APPLICATION_CHANNELS:
        raise ValueError("Canal de déclaration manuelle invalide")
    with handle.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        offer = offers_mod.get(handle, offer_id, conn=conn)
        if offer is None or offer["status"] not in ("new", "shortlist", "prepared", "applied"):
            return False
        if conn.execute(
            "SELECT 1 FROM email_submission_claims WHERE offer_id = ?", (offer_id,)
        ).fetchone():
            return False
        if offer["status"] != "applied" and apps_mod.add_application(
            handle,
            offer_id,
            offer["company"],
            offer["title"],
            channel,
            note,
            applied_at=applied_at,
            conn=conn,
        ):
            offers_mod.set_status(handle, offer_id, "applied", note, conn=conn)
            return True
        return (
            allow_existing
            and conn.execute(
                """SELECT 1 FROM applications WHERE offer_id = ? AND channel IN (?, ?, ?)
                   AND status = 'sent' AND COALESCE(external_id, '') = ''
                   AND COALESCE(proof_kind, '') = ''""",
                (offer_id, *sorted(MANUAL_APPLICATION_CHANNELS)),
            ).fetchone()
            is not None
        )


def release_uncertain_submission(
    handle: DatabaseHandle,
    offer_id: str,
    status: str,
    note: str = "",
) -> bool:
    if status not in ("new", "prepared"):
        return False
    with handle.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        offer = offers_mod.get(handle, offer_id, conn=conn)
        if offer is None or offer["status"] not in ("submission_pending", "submission_unknown"):
            return False
        if conn.execute(
            "SELECT 1 FROM applications WHERE offer_id = ? AND status != 'withdrawn'",
            (offer_id,),
        ).fetchone():
            return False
        if conn.execute(
            "SELECT 1 FROM email_submission_claims WHERE offer_id = ?", (offer_id,)
        ).fetchone():
            return False
        return offers_mod.set_status(
            handle,
            offer_id,
            status,
            f"Absence d’envoi vérifiée manuellement. {note}".strip(),
            conn=conn,
        )


def withdraw_manual_application(handle: DatabaseHandle, offer_id: str) -> bool:
    with handle.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        offer = offers_mod.get(handle, offer_id, conn=conn)
        if offer is None or offer["status"] != "applied":
            return False
        if conn.execute(
            "SELECT 1 FROM email_submission_claims WHERE offer_id = ?", (offer_id,)
        ).fetchone():
            return False
        rows = conn.execute(
            "SELECT channel, external_id, proof_kind, status FROM applications "
            "WHERE offer_id = ? AND status != 'withdrawn'",
            (offer_id,),
        ).fetchall()
        if not rows or any(
            row["channel"] not in MANUAL_APPLICATION_CHANNELS
            or row["external_id"]
            or row["proof_kind"]
            or row["status"] != "sent"
            for row in rows
        ):
            return False
        prepared = conn.execute("SELECT 1 FROM kits WHERE offer_id = ?", (offer_id,)).fetchone()
        conn.execute(
            "UPDATE applications SET status = 'withdrawn' WHERE offer_id = ? AND status = 'sent'",
            (offer_id,),
        )
        return offers_mod.set_status(
            handle,
            offer_id,
            "prepared" if prepared else "new",
            "Déclaration annulée par l’utilisateur",
            conn=conn,
        )


def has_unreconciled_submissions(handle: DatabaseHandle) -> bool:
    with handle.db() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM offers WHERE status IN ('submission_pending', 'submission_unknown') LIMIT 1"
            ).fetchone()
            is not None
        )


def pending_excel_projections(handle: DatabaseHandle) -> list[sqlite3.Row]:
    with handle.db() as conn:
        return conn.execute(
            """SELECT o.*, p.applied_at AS projection_applied_at, p.note AS projection_note
               FROM application_excel_projection p JOIN offers o ON o.id = p.offer_id
               ORDER BY p.applied_at, p.offer_id"""
        ).fetchall()


def finish_excel_projection(handle: DatabaseHandle, offer_id: str, applied_at: str) -> None:
    with handle.db() as conn:
        conn.execute(
            "DELETE FROM application_excel_projection WHERE offer_id = ? AND applied_at = ?",
            (offer_id, applied_at),
        )


def reserve_email_submission(
    handle: DatabaseHandle,
    offer_id: str,
    target_id: str,
    reserve_mail: Callable[[], bool],
) -> bool:
    with handle.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        candidate = conn.execute(
            """SELECT id FROM offers WHERE id = ? AND status IN ('new', 'shortlist', 'prepared')
               AND NOT EXISTS (SELECT 1 FROM applications WHERE offer_id = ? AND status != 'withdrawn')
               AND NOT EXISTS (SELECT 1 FROM plan WHERE day = ? AND offer_id = ? AND status = 'skipped')""",
            (offer_id, offer_id, today(), offer_id),
        ).fetchone()
        if not candidate:
            return False
        existing = conn.execute(
            "SELECT target_id FROM email_submission_claims WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        if existing and existing["target_id"] != target_id:
            return False
        if not reserve_mail():
            return False
        conn.execute(
            "INSERT OR IGNORE INTO email_submission_claims VALUES (?, ?)",
            (offer_id, target_id),
        )
        return True


def release_email_submission(
    handle: DatabaseHandle,
    offer_id: str,
    target_id: str,
    can_release: Callable[[], bool] | None = None,
) -> None:
    with handle.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if can_release is not None and not can_release():
            return
        conn.execute(
            "DELETE FROM email_submission_claims WHERE offer_id = ? AND target_id = ?",
            (offer_id, target_id),
        )


def claim_submission(handle: DatabaseHandle, offer_id: str) -> bool:
    note = "Envoi engagé ; vérifier l'espace candidat en cas d'interruption"
    with handle.db() as conn:
        result = conn.execute(
            """UPDATE offers SET status = 'submission_unknown', notes = ?
               WHERE id = ? AND status IN ('new', 'shortlist', 'prepared')
                 AND NOT EXISTS (SELECT 1 FROM applications WHERE offer_id = ? AND status != 'withdrawn')
                 AND NOT EXISTS (SELECT 1 FROM plan WHERE day = ? AND offer_id = ? AND status = 'skipped')
                 AND NOT EXISTS (SELECT 1 FROM email_submission_claims WHERE offer_id = ?)""",
            (note, offer_id, offer_id, today(), offer_id, offer_id),
        )
        if result.rowcount != 1:
            return False
        conn.execute(
            "UPDATE plan SET status = 'submission_unknown' WHERE day = ? AND offer_id = ?",
            (today(), offer_id),
        )
        conn.execute(
            "INSERT INTO events (at, kind, offer_id, detail) VALUES (?, ?, ?, ?)",
            (now_iso(), "submission_unknown", offer_id, note),
        )
    return True


def mark_submission_unknown(
    handle: DatabaseHandle,
    offer_id: str,
    note: str = "",
    *,
    mark_plan_fn: Callable[[str, str], None] | None = None,
) -> None:
    offers_mod.set_status(handle, offer_id, "submission_unknown", note)
    if mark_plan_fn is not None:
        mark_plan_fn(offer_id, "submission_unknown")
    else:
        plan_mod.mark_plan(handle, offer_id, "submission_unknown")


def mark_submission_pending(
    handle: DatabaseHandle,
    offer_id: str,
    note: str = "",
    *,
    mark_plan_fn: Callable[[str, str], None] | None = None,
) -> None:
    offers_mod.set_status(handle, offer_id, "submission_pending", note)
    if mark_plan_fn is not None:
        mark_plan_fn(offer_id, "submission_pending")
    else:
        plan_mod.mark_plan(handle, offer_id, "submission_pending")
