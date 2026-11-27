"""Bounded daily/sync run persistence and execution helpers for Career Copilot API."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from typing import Any, Literal, cast

from career_copilot.api.schemas_ops import (
    DailyRunTriggerResponse,
    RunDetailResponse,
    RunListResponse,
    RunSummary,
    SyncRunTriggerResponse,
)
from career_copilot.store.connection import DatabaseHandle, now_iso


class ApiServiceError(RuntimeError):
    """Typed domain error carrying HTTP status code and machine-readable error code."""

    def __init__(self, status_code: int, detail: str, *, code: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def _row_to_run_summary(row: sqlite3.Row) -> RunSummary:
    return RunSummary(
        id=int(row["id"]),
        kind=cast(Literal["daily", "sync"], str(row["kind"])),
        status=cast(Literal["running", "success", "failed"], str(row["status"])),
        started_at=str(row["started_at"]),
        duration_seconds=(
            float(row["duration_seconds"]) if row["duration_seconds"] is not None else None
        ),
        summary=str(row["summary"] or ""),
    )


def _row_to_run_detail(row: sqlite3.Row) -> RunDetailResponse:
    run_id = int(row["id"])
    return RunDetailResponse(
        id=run_id,
        run_id=run_id,
        kind=cast(Literal["daily", "sync"], str(row["kind"])),
        status=cast(Literal["running", "success", "failed"], str(row["status"])),
        started_at=str(row["started_at"]),
        finished_at=str(row["finished_at"]) if row["finished_at"] is not None else None,
        duration_seconds=(
            float(row["duration_seconds"]) if row["duration_seconds"] is not None else None
        ),
        summary=str(row["summary"] or ""),
        error_code=str(row["error_code"] or ""),
        synced_messages=int(row["synced_messages"] or 0),
    )


def list_runs(handle: DatabaseHandle, *, limit: int = 8) -> RunListResponse:
    bounded = max(1, min(int(limit), 50))
    with handle.db() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (bounded,)).fetchall()
    return RunListResponse(runs=[_row_to_run_summary(row) for row in rows])


def get_run(handle: DatabaseHandle, run_id: int) -> RunDetailResponse | None:
    with handle.db() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (int(run_id),)).fetchone()
    return _row_to_run_detail(row) if row is not None else None


def trigger_daily_run(
    handle: DatabaseHandle,
    *,
    auto_submit: bool = False,
    runner: Callable[[int, bool], dict[str, Any] | None] | None = None,
) -> DailyRunTriggerResponse:
    """Create a bounded daily run record (409 if another daily run is active)."""
    started_at = now_iso()
    with handle.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT id FROM runs WHERE kind = 'daily' AND status = 'running' LIMIT 1"
        ).fetchone()
        if active is not None:
            raise ApiServiceError(
                409,
                "Un cycle quotidien est déjà en cours",
                code="run_already_active",
            )
        cursor = conn.execute(
            "INSERT INTO runs (kind, status, started_at, summary) VALUES ('daily', 'running', ?, ?)",
            (started_at, "auto_submit=true" if auto_submit else "auto_submit=false"),
        )
        run_id = int(cursor.lastrowid or 0)

    if runner is not None:
        t0 = time.monotonic()
        try:
            res = runner(run_id, bool(auto_submit))
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            duration = round(max(0.0, time.monotonic() - t0), 3)
            with handle.db() as conn:
                conn.execute(
                    "UPDATE runs SET status = 'failed', finished_at = ?, "
                    "duration_seconds = ?, summary = ?, error_code = ? WHERE id = ?",
                    (now_iso(), duration, str(exc), "daily_run_failed", run_id),
                )
            return DailyRunTriggerResponse(run_id=run_id, status="failed")
        if isinstance(res, dict) and res.get("completed"):
            duration = round(max(0.0, time.monotonic() - t0), 3)
            with handle.db() as conn:
                conn.execute(
                    "UPDATE runs SET status = 'success', finished_at = ?, "
                    "duration_seconds = ?, summary = ? WHERE id = ?",
                    (now_iso(), duration, str(res.get("summary") or "ok"), run_id),
                )
            return DailyRunTriggerResponse(run_id=run_id, status="success")

    return DailyRunTriggerResponse(run_id=run_id, status="running")


def trigger_sync_run(
    handle: DatabaseHandle,
    *,
    source: str = "imap",
    runner: Callable[[str], int] | None = None,
) -> SyncRunTriggerResponse:
    """Record and execute a bounded inbox sync run."""
    started_at = now_iso()
    t0 = time.monotonic()
    with handle.db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT id FROM runs WHERE kind = 'sync' AND status = 'running' LIMIT 1"
        ).fetchone()
        if active is not None:
            raise ApiServiceError(
                409,
                "Une synchronisation est déjà en cours",
                code="run_already_active",
            )
        cursor = conn.execute(
            "INSERT INTO runs (kind, status, started_at, summary) VALUES ('sync', 'running', ?, ?)",
            (started_at, f"source={source}"),
        )
        run_id = int(cursor.lastrowid or 0)

    synced_messages = 0
    status: Literal["success", "failed"] = "success"
    error_code = ""
    summary = f"Synchronisation {source} terminée"
    if runner is not None:
        try:
            synced_messages = max(0, int(runner(source)))
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            status = "failed"
            error_code = "sync_failed"
            summary = str(exc)

    duration = round(max(0.0, time.monotonic() - t0), 3)
    with handle.db() as conn:
        conn.execute(
            "UPDATE runs SET status = ?, finished_at = ?, duration_seconds = ?, "
            "summary = ?, error_code = ?, synced_messages = ? WHERE id = ?",
            (status, now_iso(), duration, summary, error_code, synced_messages, run_id),
        )
    return SyncRunTriggerResponse(
        run_id=run_id,
        status=status,
        synced_messages=synced_messages,
    )
