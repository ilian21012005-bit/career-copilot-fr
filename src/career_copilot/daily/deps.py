"""Explicit dependency container and constants for the daily pipeline."""

from __future__ import annotations

import imaplib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BLOCKING_ERROR_PREFIXES: tuple[str, ...] = (
    "plan:",
    "alertes:",
    "mails:",
    "envoi automatique",
)

MAX_PER_COMPANY_IN_PLAN = 2

TRACK_BUCKETS: dict[str, str] = {
    "reseau": "sys_reseau",
    "sysadmin": "sys_reseau",
    "devops": "cloud_devops",
    "support": "support_ops",
    "it_ops": "support_ops",
    "soc": "cyber_soc",
    "cyber": "cyber_soc",
    "qualite": "qualite_data",
    "data_it": "qualite_data",
}

BUCKET_ORDER: tuple[str, ...] = (
    "sys_reseau",
    "cloud_devops",
    "support_ops",
    "cyber_soc",
    "qualite_data",
    "job_etudiant",
)

RECOVERABLE_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    LookupError,
    AttributeError,
    ImportError,
    sqlite3.Error,
    imaplib.IMAP4.error,
)


@dataclass(frozen=True)
class DailyDeps:
    """Explicit dependencies injected into daily pipeline modules (zero globals)."""

    store: Any
    offers: Any
    scoring: Any
    geo: Any
    kit: Any
    profile: Any
    alerts: Any
    dedup: Any
    cv_personalize: Any
    assist_apply: Any
    ats_alive: Any
    lm_ai: Any
    partner_deep: Any
    ready_queue: Any
    report: Any
    jobspy_source: Any
    filters: Any
    interview_prep: Any
    offer_letters: Any
    mail_store: Any
    load_env: Callable[[], dict[str, str]]
    fold: Callable[[str], str]
    data_dir: Callable[[], Path]
    log_dir: Callable[[], Path]
    state_path: Callable[[], Path]
    logger_fn: Callable[[str], Any] | None = None
    build_fn: Callable[..., list[Any]] | None = None
    prepare_kits_fn: Callable[[], list[dict[str, Any]]] | None = None
    discover_fn: Callable[..., dict[str, Any]] | None = None
    sync_public_sources_fn: Callable[..., dict[str, int]] | None = None
    route_public_emails_fn: Callable[[Any], int] | None = None
    prepare_interview_preps_fn: Callable[[Any], int] | None = None
    scan_response_radar_fn: Callable[[Any], dict[str, int]] | None = None
    write_state_fn: Callable[..., None] | None = None
    tag_student_job_fn: Callable[[Any], bool] | None = None
    run_fn: Callable[..., dict[str, Any]] | None = None
    ran_today_fn: Callable[..., bool] | None = None
