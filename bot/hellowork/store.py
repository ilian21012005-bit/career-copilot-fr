"""Backward-compatible re-export shim for ``career_copilot.store``.

All SQLite WAL connection, migrations, offers, applications, submissions, kits,
plan, and alerts logic now lives in ``src/career_copilot/store/`` without
``sys.modules[__name__]`` context passing.
"""

# ruff: noqa: E402
from __future__ import annotations

import functools
import sqlite3
import sys
from pathlib import Path
from typing import Any

from config import DATA_DIR

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.db.migrations import open_wal_connection
from career_copilot.store import (
    MANUAL_APPLICATION_CHANNELS,
    STATUSES,
    DatabaseHandle,
    now_iso,
    today,
)
from career_copilot.store import alerts as _alerts
from career_copilot.store import applications as _apps
from career_copilot.store import kits as _kits
from career_copilot.store import offers as _offers
from career_copilot.store import plan as _plan
from career_copilot.store import submissions as _subs

DB_PATH = DATA_DIR / "hellowork.db"
_PROFILE_UNREAD = object()
_KIT_OFFER_FIELDS = _kits.KIT_OFFER_FIELDS
KIT_SCHEMA_VERSION = _kits.KIT_SCHEMA_VERSION
offer_fingerprint = _kits.offer_fingerprint
file_fingerprint = _kits.file_fingerprint


def _connect() -> sqlite3.Connection:
    return open_wal_connection(DB_PATH, foreign_keys=False)


_HANDLE = DatabaseHandle(
    db_path_getter=lambda: DB_PATH,
    data_dir_getter=lambda: DATA_DIR,
    connect_fn=lambda: _connect(),
)
_INIT_DONE = _HANDLE.init_done
_db = _HANDLE.db
_session = _HANDLE.session
init = _HANDLE.init

# Offers
save_offer = functools.partial(_offers.save_offer, _HANDLE)
set_apply_capability = functools.partial(_offers.set_apply_capability, _HANDLE)
get = functools.partial(_offers.get, _HANDLE)
by_url = functools.partial(_offers.by_url, _HANDLE)
list_offers = functools.partial(_offers.list_offers, _HANDLE)
zone_counts = functools.partial(_offers.zone_counts, _HANDLE)
set_status = functools.partial(_offers.set_status, _HANDLE)
mark_to_finish_from_alert = functools.partial(_offers.mark_to_finish_from_alert, _HANDLE)
counts = functools.partial(_offers.counts, _HANDLE)
event = functools.partial(_offers.event, _HANDLE)
mark_partner_checked = functools.partial(_offers.mark_partner_checked, _HANDLE)

# Plan
set_plan = functools.partial(_plan.set_plan, _HANDLE)
plan_for = functools.partial(_plan.plan_for, _HANDLE)
plan_count = functools.partial(_plan.plan_count, _HANDLE)
mark_plan = functools.partial(_plan.mark_plan, _HANDLE)
cleanup_stale_planned = functools.partial(_plan.cleanup_stale_planned, _HANDLE)

# Applications & submissions
add_application = functools.partial(_apps.add_application, _HANDLE)
applied_today = functools.partial(_apps.applied_today, _HANDLE)
applications = functools.partial(_apps.applications, _HANDLE)
has_application = functools.partial(_apps.has_application, _HANDLE)
has_sent_application = functools.partial(_apps.has_sent_application, _HANDLE)
stats = functools.partial(_apps.stats, _HANDLE)
declare_manual_application = functools.partial(_subs.declare_manual_application, _HANDLE)
release_uncertain_submission = functools.partial(_subs.release_uncertain_submission, _HANDLE)
withdraw_manual_application = functools.partial(_subs.withdraw_manual_application, _HANDLE)
has_unreconciled_submissions = functools.partial(_subs.has_unreconciled_submissions, _HANDLE)
pending_excel_projections = functools.partial(_subs.pending_excel_projections, _HANDLE)
finish_excel_projection = functools.partial(_subs.finish_excel_projection, _HANDLE)
reserve_email_submission = functools.partial(_subs.reserve_email_submission, _HANDLE)
release_email_submission = functools.partial(_subs.release_email_submission, _HANDLE)
claim_submission = functools.partial(_subs.claim_submission, _HANDLE)

# Alerts & mails
mail_seen = functools.partial(_alerts.mail_seen, _HANDLE)
mail_kind = functools.partial(_alerts.mail_kind, _HANDLE)
has_alert_history = functools.partial(_alerts.has_alert_history, _HANDLE)
remember_mail = functools.partial(_alerts.remember_mail, _HANDLE)
set_mail_kind = functools.partial(_alerts.set_mail_kind, _HANDLE)
queue_alert_offer = functools.partial(_alerts.queue_alert_offer, _HANDLE)
queue_alert_link = functools.partial(_alerts.queue_alert_link, _HANDLE)
pending_alert_links = functools.partial(_alerts.pending_alert_links, _HANDLE)
resolve_alert_link = functools.partial(_alerts.resolve_alert_link, _HANDLE)
retry_alert_link = functools.partial(_alerts.retry_alert_link, _HANDLE)
pending_alert_urls = functools.partial(_alerts.pending_alert_urls, _HANDLE)
resolve_alert_offer = functools.partial(_alerts.resolve_alert_offer, _HANDLE)
retry_alert_offer = functools.partial(_alerts.retry_alert_offer, _HANDLE)

# Kits (wrappers preserve test monkeypatching of module attributes)
application_offer_ids = functools.partial(_kits.application_offer_ids, _HANDLE)
_normalize_kit_paths = functools.partial(_kits.normalize_kit_paths, _HANDLE)
kits_for = functools.partial(_kits.kits_for, _HANDLE)
kit_for = functools.partial(_kits.kit_for, _HANDLE)


def profile_fingerprint() -> str | None:
    return _kits.profile_fingerprint(kit_schema_version=KIT_SCHEMA_VERSION)


def save_kit(
    offer_id: str, subject: str, letter: Path | None, cv: Path | None, dossier: Path
) -> None:
    _kits.save_kit(
        _HANDLE,
        offer_id,
        subject,
        letter,
        cv,
        dossier,
        offer_fp_fn=offer_fingerprint,
        file_fp_fn=file_fingerprint,
        profile_fp_fn=profile_fingerprint,
    )


def kit_is_current(offer_id: str, kit: dict[str, Any] | None = None) -> bool:
    return _kits.kit_is_current(_HANDLE, offer_id, kit, offer_fp_fn=offer_fingerprint)


def kit_documents_current(
    kit: dict[str, Any] | None,
    letter_text: str | None = None,
    *,
    profile_source: Any = _PROFILE_UNREAD,
) -> bool:
    kwargs: dict[str, Any] = {
        "file_fp_fn": file_fingerprint,
        "profile_fp_fn": profile_fingerprint,
    }
    if profile_source is not _PROFILE_UNREAD:
        kwargs["profile_source"] = profile_source
    return _kits.kit_documents_current(kit, letter_text, **kwargs)


def validation_is_current(
    target: dict[str, Any] | str | None,
    *,
    profile_source: Any = _PROFILE_UNREAD,
) -> bool:
    if profile_source is _PROFILE_UNREAD:
        return _kits.validation_is_current(_HANDLE, target)
    return _kits.validation_is_current(_HANDLE, target, profile_source=profile_source)


def confirm(
    offer_id: str,
    channel: str = "hellowork-manual",
    note: str = "",
    *,
    applied_at: str = "",
    proof_kind: str = "",
    proof_reference: str = "",
    project_to_excel: bool = False,
) -> bool:
    return _apps.confirm(
        _HANDLE,
        offer_id,
        channel=channel,
        note=note,
        applied_at=applied_at,
        proof_kind=proof_kind,
        proof_reference=proof_reference,
        project_to_excel=project_to_excel,
        mark_plan_fn=mark_plan,
    )


def skip(offer_id: str, note: str = "") -> None:
    _offers.skip(_HANDLE, offer_id, note, mark_plan_fn=mark_plan)


def mark_submission_unknown(offer_id: str, note: str = "") -> None:
    _subs.mark_submission_unknown(_HANDLE, offer_id, note, mark_plan_fn=mark_plan)


def mark_submission_pending(offer_id: str, note: str = "") -> None:
    _subs.mark_submission_pending(_HANDLE, offer_id, note, mark_plan_fn=mark_plan)


__all__ = [
    "DB_PATH",
    "KIT_SCHEMA_VERSION",
    "MANUAL_APPLICATION_CHANNELS",
    "STATUSES",
    "add_application",
    "application_offer_ids",
    "applications",
    "applied_today",
    "by_url",
    "claim_submission",
    "cleanup_stale_planned",
    "confirm",
    "counts",
    "declare_manual_application",
    "event",
    "file_fingerprint",
    "finish_excel_projection",
    "get",
    "has_alert_history",
    "has_application",
    "has_sent_application",
    "has_unreconciled_submissions",
    "init",
    "kit_documents_current",
    "kit_for",
    "kit_is_current",
    "kits_for",
    "list_offers",
    "mail_kind",
    "mail_seen",
    "mark_partner_checked",
    "mark_plan",
    "mark_submission_pending",
    "mark_submission_unknown",
    "mark_to_finish_from_alert",
    "now_iso",
    "offer_fingerprint",
    "pending_alert_links",
    "pending_alert_urls",
    "pending_excel_projections",
    "plan_count",
    "plan_for",
    "profile_fingerprint",
    "queue_alert_link",
    "queue_alert_offer",
    "release_email_submission",
    "release_uncertain_submission",
    "remember_mail",
    "reserve_email_submission",
    "resolve_alert_link",
    "resolve_alert_offer",
    "retry_alert_link",
    "retry_alert_offer",
    "save_kit",
    "save_offer",
    "set_apply_capability",
    "set_mail_kind",
    "set_plan",
    "set_status",
    "skip",
    "stats",
    "today",
    "validation_is_current",
    "withdraw_manual_application",
    "zone_counts",
]
