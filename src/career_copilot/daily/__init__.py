"""Modular daily pipeline package (`career_copilot.daily`)."""

from __future__ import annotations

from .deps import (
    BLOCKING_ERROR_PREFIXES,
    BUCKET_ORDER,
    MAX_PER_COMPANY_IN_PLAN,
    RECOVERABLE_ERRORS,
    TRACK_BUCKETS,
    DailyDeps,
)
from .discovery import (
    discover,
    prepare_interview_preps,
    route_public_emails,
    scan_response_radar,
    sync_public_sources,
    tag_student_job_if_matched,
)
from .planner import (
    build,
    is_duplicate_of_any,
    offer_bucket,
    prepare,
    remaining_today,
    row_fingerprint,
    select_balanced,
)
from .runner import log_summary, run, run_if_due
from .state import configure_logger, last_state, ran_today, retry, write_state

__all__ = [
    "BLOCKING_ERROR_PREFIXES",
    "BUCKET_ORDER",
    "DailyDeps",
    "MAX_PER_COMPANY_IN_PLAN",
    "RECOVERABLE_ERRORS",
    "TRACK_BUCKETS",
    "build",
    "configure_logger",
    "discover",
    "is_duplicate_of_any",
    "last_state",
    "log_summary",
    "offer_bucket",
    "prepare",
    "prepare_interview_preps",
    "ran_today",
    "remaining_today",
    "retry",
    "route_public_emails",
    "row_fingerprint",
    "run",
    "run_if_due",
    "scan_response_radar",
    "select_balanced",
    "sync_public_sources",
    "tag_student_job_if_matched",
    "write_state",
]
