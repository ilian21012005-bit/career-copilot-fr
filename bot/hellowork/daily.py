"""Backward-compatible re-export shim for ``career_copilot.daily``.

All daily pipeline planning, discovery, state persistence, and orchestration
now live in ``src/career_copilot/daily/``.
"""

# ruff: noqa: E402
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

import filters
import interview_prep
import offer_letters
import store as mail_store
from config import DATA_DIR, load_env

from . import (
    alerts,
    assist_apply,
    ats_alive,
    cv_personalize,
    dedup,
    geo,
    jobspy_source,
    kit,
    lm_ai,
    partner_deep,
    profile,
    ready_queue,
    report,
    store,
)
from . import offer as offers
from . import score as scoring
from .text import fold

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.daily import (
    BLOCKING_ERROR_PREFIXES,
    BUCKET_ORDER as _BUCKET_ORDER,
    MAX_PER_COMPANY_IN_PLAN,
    TRACK_BUCKETS as _TRACK_BUCKETS,
    DailyDeps,
)
from career_copilot.daily import (
    build as _build_impl,
    configure_logger as _configure_logger_impl,
    discover as _discover_impl,
    is_duplicate_of_any as _is_duplicate_of_any_impl,
    last_state as _last_state_impl,
    log_summary as _log_summary_impl,
    offer_bucket as _offer_bucket_impl,
    prepare as _prepare_impl,
    prepare_interview_preps as _prepare_interview_preps_impl,
    ran_today as _ran_today_impl,
    remaining_today as _remaining_today_impl,
    retry as _retry_impl,
    route_public_emails as _route_public_emails_impl,
    row_fingerprint as _row_fingerprint_impl,
    run as _run_impl,
    run_if_due as _run_if_due_impl,
    scan_response_radar as _scan_response_radar_impl,
    select_balanced as _select_balanced_impl,
    sync_public_sources as _sync_public_sources_impl,
    tag_student_job_if_matched as _tag_student_job_impl,
    write_state as _write_state_impl,
)

LOG_DIR = DATA_DIR / "hellowork" / "logs"
STATE_PATH = DATA_DIR / "hellowork" / "last-run.json"


def _deps() -> DailyDeps:
    return DailyDeps(
        store=store,
        offers=offers,
        scoring=scoring,
        geo=geo,
        kit=kit,
        profile=profile,
        alerts=alerts,
        dedup=dedup,
        cv_personalize=cv_personalize,
        assist_apply=assist_apply,
        ats_alive=ats_alive,
        lm_ai=lm_ai,
        partner_deep=partner_deep,
        ready_queue=ready_queue,
        report=report,
        jobspy_source=jobspy_source,
        filters=filters,
        interview_prep=interview_prep,
        offer_letters=offer_letters,
        mail_store=mail_store,
        load_env=load_env,
        fold=fold,
        data_dir=lambda: DATA_DIR,
        log_dir=lambda: LOG_DIR,
        state_path=lambda: STATE_PATH,
        logger_fn=logger,
        build_fn=build,
        prepare_kits_fn=prepare_kits,
        discover_fn=_discover,
        sync_public_sources_fn=sync_public_sources,
        route_public_emails_fn=_route_public_emails,
        prepare_interview_preps_fn=_prepare_interview_preps,
        scan_response_radar_fn=_scan_response_radar,
        write_state_fn=_write_state,
        tag_student_job_fn=_tag_student_job_if_matched,
        run_fn=run,
        ran_today_fn=ran_today,
    )


def _row_fingerprint(row: Any) -> tuple[str, str, set[str]] | None:
    return _row_fingerprint_impl(_deps(), row)


def _is_duplicate_of_any(
    fp: tuple[str, str, set[str]] | None,
    fingerprints: list[tuple[str, str, set[str]]],
    *,
    threshold: float = 0.55,
) -> bool:
    return _is_duplicate_of_any_impl(_deps(), fp, fingerprints, threshold=threshold)


def _offer_bucket(row: Any) -> str:
    return _offer_bucket_impl(_deps(), row)


def _select_balanced(
    prepared: list[Any],
    remaining: list[Any],
    existing: list[Any],
    room: int,
    goal: int,
) -> list[Any]:
    return _select_balanced_impl(_deps(), prepared, remaining, existing, room, goal)


def build(
    target: int | None = None, cap: int | None = None, zone: str | None = None
) -> list[Any]:
    return _build_impl(_deps(), target=target, cap=cap, zone=zone)


def prepare(limit: int | None = None) -> list[dict[str, Any]]:
    return _prepare_impl(_deps(), limit=limit)


def prepare_kits() -> list[dict[str, Any]]:
    """Prépare les dossiers de la file, en sautant ceux qui existent déjà."""
    return prepare()


def remaining_today() -> int:
    return _remaining_today_impl(_deps())


def logger(name: str = "hellowork.daily") -> logging.Logger:
    return _configure_logger_impl(_deps(), name=name)


def _scan_response_radar(log: logging.Logger) -> dict[str, int]:
    return _scan_response_radar_impl(_deps(), log)


def _discover(log: Any, cap: int, delay: float, sleep: Any, errors: list[str]) -> dict[str, int]:
    return _discover_impl(_deps(), log, cap, delay, sleep, errors)


def _retry(
    fn: Any,
    log: Any,
    label: str,
    delay: float = 3.0,
    sleep: Any = time.sleep,
    attempts: int = 3,
) -> Any:
    return _retry_impl(fn, log, label, delay=delay, sleep=sleep, attempts=attempts)


def last_state() -> dict[str, Any]:
    return _last_state_impl(_deps())


def _write_state(summary: dict[str, Any], *, auto_submit: bool = False) -> None:
    _write_state_impl(_deps(), summary, auto_submit=auto_submit)


def ran_today(*, auto_submit: bool = False, min_interval_seconds: int = 3 * 3600) -> bool:
    return _ran_today_impl(
        _deps(), auto_submit=auto_submit, min_interval_seconds=min_interval_seconds
    )


def run(
    sync: bool = True,
    prepare: bool = True,
    max_offers: int | None = None,
    target: int | None = None,
    log: logging.Logger | None = None,
    retry_delay: float = 3.0,
    sleep: Any = time.sleep,
    record_state: bool = True,
    auto_submit: bool = False,
) -> dict[str, Any]:
    return _run_impl(
        _deps(),
        sync=sync,
        prepare_flag=prepare,
        max_offers=max_offers,
        target=target,
        log=log,
        retry_delay=retry_delay,
        sleep=sleep,
        record_state=record_state,
        auto_submit=auto_submit,
    )


def run_if_due(*, auto_submit: bool = False, **kwargs: Any) -> dict[str, Any]:
    return _run_if_due_impl(_deps(), auto_submit=auto_submit, **kwargs)


def sync_public_sources(
    env: dict[str, str] | None = None, log: logging.Logger | None = None
) -> dict[str, int]:
    return _sync_public_sources_impl(_deps(), env=env, log=log)


def _tag_student_job_if_matched(offer: Any) -> bool:
    return _tag_student_job_impl(_deps(), offer)


def _route_public_emails(log: logging.Logger) -> int:
    return _route_public_emails_impl(_deps(), log)


def _prepare_interview_preps(log: logging.Logger) -> int:
    return _prepare_interview_preps_impl(_deps(), log)


def _log_summary(log: Any, summary: dict[str, Any]) -> None:
    _log_summary_impl(log, summary)


__all__ = [
    "BLOCKING_ERROR_PREFIXES",
    "LOG_DIR",
    "MAX_PER_COMPANY_IN_PLAN",
    "STATE_PATH",
    "_BUCKET_ORDER",
    "_TRACK_BUCKETS",
    "_discover",
    "_is_duplicate_of_any",
    "_log_summary",
    "_offer_bucket",
    "_prepare_interview_preps",
    "_retry",
    "_route_public_emails",
    "_row_fingerprint",
    "_scan_response_radar",
    "_select_balanced",
    "_tag_student_job_if_matched",
    "_write_state",
    "build",
    "last_state",
    "logger",
    "prepare",
    "prepare_kits",
    "ran_today",
    "remaining_today",
    "run",
    "run_if_due",
    "sync_public_sources",
]
