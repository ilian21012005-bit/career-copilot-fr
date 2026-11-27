"""Application recording, deduplication, confirmation, and summary statistics."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from career_copilot.store import offers as offers_mod
from career_copilot.store import plan as plan_mod
from career_copilot.store.connection import (
    MANUAL_APPLICATION_CHANNELS,
    DatabaseHandle,
    now_iso,
)

_VALID_PROOF_KINDS = frozenset({"authenticated_receipt", "ats_receipt", "smtp_accepted"})


def _find_duplicate_application(
    db: sqlite3.Connection,
    *,
    offer_id: str,
    company: str,
    title: str,
    external_id: str,
    day: str,
) -> tuple[sqlite3.Row | None, bool]:
    """Return `(duplicate_row, foreign_external_collision)`."""
    duplicate = None
    if external_id:
        duplicate = db.execute(
            "SELECT offer_id FROM applications WHERE external_id = ?",
            (external_id,),
        ).fetchone()
        if duplicate and str(duplicate["offer_id"] or "") != str(offer_id or ""):
            return duplicate, True
    elif offer_id:
        duplicate = db.execute(
            "SELECT 1 FROM applications WHERE offer_id = ? AND status != 'withdrawn'",
            (offer_id,),
        ).fetchone()
    else:
        duplicate = db.execute(
            """
            SELECT 1 FROM applications
            WHERE company = ? AND title = ? AND status != 'withdrawn'
              AND COALESCE(offer_id, '') = ''
            """,
            (company, title),
        ).fetchone()
        if not duplicate:
            duplicate = db.execute(
                "SELECT 1 FROM applications WHERE company = ? AND status != 'withdrawn' "
                "AND substr(applied_at, 1, 10) = ?",
                (company, day),
            ).fetchone()

    if not duplicate and offer_id:
        duplicate = db.execute(
            "SELECT 1 FROM applications WHERE offer_id = ? AND status != 'withdrawn'",
            (offer_id,),
        ).fetchone()
    return duplicate, False


def _upgrade_duplicate_application(
    db: sqlite3.Connection,
    *,
    offer_id: str,
    channel: str,
    external_id: str,
    proof_kind: str,
    proof_reference: str,
    day: str,
    mark_offer: bool,
) -> None:
    if proof_kind and offer_id:
        db.execute(
            """UPDATE applications SET proof_kind = ?, proof_reference = ?
               WHERE id = (SELECT id FROM applications WHERE offer_id = ? AND status != 'withdrawn'
                           ORDER BY id LIMIT 1)
                 AND (COALESCE(proof_kind, '') = ''
                      OR (proof_kind = 'smtp_accepted' AND ? != 'smtp_accepted'))""",
            (proof_kind, proof_reference, offer_id, proof_kind),
        )
    if external_id and offer_id:
        db.execute(
            "UPDATE applications SET external_id = ? WHERE offer_id = ? "
            "AND substr(applied_at, 1, 10) = ? AND COALESCE(external_id, '') = ''",
            (external_id, offer_id, day),
        )
    if mark_offer and offer_id:
        db.execute(
            "UPDATE offers SET status = CASE WHEN status IN ('interview', 'replied') "
            "THEN status ELSE 'applied' END WHERE id = ?",
            (offer_id,),
        )
        db.execute(
            "UPDATE plan SET status = 'applied' WHERE offer_id = ? "
            "AND status IN ('planned', 'submission_pending', 'submission_unknown')",
            (offer_id,),
        )
        db.execute(
            "UPDATE applications SET status = 'sent', channel = ? WHERE offer_id = ? "
            "AND substr(applied_at, 1, 10) = ? AND status = 'to_finish'",
            (channel, offer_id, day),
        )


def add_application(
    handle: DatabaseHandle,
    offer_id: str,
    company: str,
    title: str,
    channel: str,
    evidence: str = "",
    applied_at: str = "",
    mark_offer: bool = True,
    external_id: str = "",
    *,
    proof_kind: str = "",
    proof_reference: str = "",
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Record an application idempotently. Returns False if already recorded."""
    if proof_kind and proof_kind not in _VALID_PROOF_KINDS:
        raise ValueError("Type de preuve d'envoi inconnu")
    if bool(proof_kind) != bool(proof_reference):
        raise ValueError("La référence et le type de preuve sont requis ensemble")
    stamp = applied_at or now_iso()
    day = stamp[:10]
    with handle.session(conn) as db:
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        duplicate, foreign_collision = _find_duplicate_application(
            db,
            offer_id=offer_id,
            company=company,
            title=title,
            external_id=external_id,
            day=day,
        )
        if foreign_collision:
            return False
        if duplicate:
            _upgrade_duplicate_application(
                db,
                offer_id=offer_id,
                channel=channel,
                external_id=external_id,
                proof_kind=proof_kind,
                proof_reference=proof_reference,
                day=day,
                mark_offer=mark_offer,
            )
            return False

        db.execute(
            """
            INSERT INTO applications (offer_id, company, title, applied_at, channel, evidence, external_id,
                                      proof_kind, proof_reference, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer_id,
                company,
                title,
                stamp,
                channel,
                evidence,
                external_id,
                proof_kind,
                proof_reference,
                "to_finish" if channel == "hellowork-redirect" else "sent",
            ),
        )
        if mark_offer and offer_id:
            db.execute(
                "UPDATE offers SET status = CASE WHEN status IN ('interview', 'replied') "
                "THEN status ELSE 'applied' END WHERE id = ?",
                (offer_id,),
            )
            db.execute(
                "UPDATE plan SET status = 'applied' WHERE offer_id = ? "
                "AND status IN ('planned', 'submission_pending', 'submission_unknown')",
                (offer_id,),
            )
        offers_mod.event(handle, "application", offer_id, f"{company} — {channel}", conn=db)
        return True


def applied_today(handle: DatabaseHandle) -> int:
    day = datetime.now().astimezone().date().isoformat()
    with handle.db() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM applications "
                "WHERE status = 'sent' AND status != 'withdrawn' AND substr(applied_at, 1, 10) = ?",
                (day,),
            ).fetchone()[0]
        )


def applications(handle: DatabaseHandle, since_days: int = 30) -> list[sqlite3.Row]:
    limit = (datetime.now().astimezone() - timedelta(days=since_days)).isoformat(timespec="seconds")
    with handle.db() as conn:
        return list(
            conn.execute(
                "SELECT * FROM applications WHERE status != 'withdrawn' AND applied_at >= ? "
                "ORDER BY applied_at DESC",
                (limit,),
            )
        )


def has_application(handle: DatabaseHandle, offer_id: str) -> bool:
    if not offer_id:
        return False
    with handle.db() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM applications WHERE offer_id = ? AND status != 'withdrawn' LIMIT 1",
                (offer_id,),
            ).fetchone()
            is not None
        )


def has_sent_application(handle: DatabaseHandle, offer_id: str) -> bool:
    if not offer_id:
        return False
    with handle.db() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM applications WHERE offer_id = ? AND status = 'sent' LIMIT 1",
                (offer_id,),
            ).fetchone()
            is not None
        )


def stats(handle: DatabaseHandle) -> dict[str, int]:
    with handle.db() as conn:
        offers_count = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
        preparable = conn.execute(
            "SELECT COUNT(*) FROM offers WHERE score >= 80 AND status IN ('new', 'shortlist')"
        ).fetchone()[0]
        prepared = conn.execute("SELECT COUNT(*) FROM kits").fetchone()[0]
        sent = conn.execute("SELECT COUNT(*) FROM applications WHERE status = 'sent'").fetchone()[0]
    return {
        "offres": int(offers_count),
        "prêtes à préparer": int(preparable),
        "dossiers": int(prepared),
        "candidatures": int(sent),
        "aujourd'hui": applied_today(handle),
    }


def confirm(
    handle: DatabaseHandle,
    offer_id: str,
    channel: str = "hellowork-manual",
    note: str = "",
    *,
    applied_at: str = "",
    proof_kind: str = "",
    proof_reference: str = "",
    project_to_excel: bool = False,
    mark_plan_fn: Callable[..., Any] | None = None,
) -> bool:
    """Confirm an application atomically inside a single transaction."""
    from career_copilot.store import submissions as sub_mod

    if channel in MANUAL_APPLICATION_CHANNELS:
        return sub_mod.declare_manual_application(
            handle,
            offer_id,
            channel=channel,
            note=note,
            applied_at=applied_at,
            allow_existing=False,
        )
    with handle.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = offers_mod.get(handle, offer_id, conn=conn)
        if row is None:
            return False
        stamp = applied_at or now_iso()
        recorded = add_application(
            handle,
            offer_id,
            row["company"],
            row["title"],
            channel=channel,
            evidence=note,
            applied_at=stamp,
            proof_kind=proof_kind,
            proof_reference=proof_reference,
            conn=conn,
        )
        if project_to_excel:
            conn.execute(
                "INSERT OR IGNORE INTO application_excel_projection VALUES (?, ?, ?)",
                (offer_id, stamp, note),
            )
        current = offers_mod.get(handle, offer_id, conn=conn) or row
        status_changed = current["status"] not in ("applied", "interview", "replied")
        if status_changed:
            offers_mod.set_status(handle, offer_id, "applied", note, conn=conn)
        if mark_plan_fn is not None:
            mark_plan_fn(offer_id, "applied", conn=conn)
        else:
            plan_mod.mark_plan(handle, offer_id, "applied", conn=conn)
        if recorded or status_changed:
            offers_mod.event(handle, "confirmed", offer_id, f"{row['company']} — {note}", conn=conn)
        return recorded
