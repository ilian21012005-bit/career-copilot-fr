"""Explicit CLI dependency container and shared operational helpers."""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from career_copilot.fs_privacy import write_private_text

LOG = logging.getLogger("career_copilot.hellowork_cli")

BLOCKING_ERROR_PREFIXES: tuple[str, ...] = ("plan:", "alertes:", "envoi automatique")
AUTO_SUBMIT_CAPABILITY = "auto_hellowork"


@dataclass(frozen=True)
class CliDeps:
    """Explicit dependencies injected into HelloWork CLI command handlers."""

    store: Any
    daily: Any
    report: Any
    offers: Any
    scoring: Any
    geo: Any
    kit: Any
    profile: Any
    alerts: Any
    offer_letters: Any
    suivi: Any
    submit_handler: Any
    partner_deep: Any
    lm_ai: Any
    ready_queue: Any
    ats_alive: Any
    jobspy_source: Any
    load_env: Callable[[], dict[str, str]]
    data_dir: Callable[[], Path]
    stats_line_fn: Callable[[], str] | None = None
    apply_rows_fn: Callable[..., bool] | None = None
    offer_from_row_fn: Callable[[Any], Any] | None = None
    stage_cv_is_valid_fn: Callable[[Any, Path | None], bool] | None = None
    alert_hw_session_once_fn: Callable[[str, str], None] | None = None
    reconcile_pending_fn: Callable[[Any, Callable[[str], None]], int] | None = None
    reconcile_excel_fn: Callable[[Callable[[str], None]], bool] | None = None


def has_auto_submit_capability(row: Any) -> bool:
    """Fail closed unless partner analysis explicitly approved HelloWork auto-submit."""
    try:
        capability = row["apply_capability"]
    except (KeyError, IndexError, TypeError):
        return False
    return str(capability or "").strip() == AUTO_SUBMIT_CAPABILITY


def stage_cv_is_valid(row: Any, cv_path: Path | None) -> bool:
    """Refuse stage submission with a generic, missing, or non-single-page CV."""
    title = str(row["title"] or "")
    contract = str(row["contract"] or "")
    if "stage" not in f"{title} {contract}".casefold():
        return True
    if not cv_path or not cv_path.is_file() or "stage-personnalise" not in cv_path.name.casefold():
        return False
    try:
        cv_mod = importlib.import_module("hellowork.cv_personalize")
        return bool(cv_mod.pdf_page_count(cv_path) == 1)
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        LOG.warning("Validation CV stage impossible pour %s : %s", cv_path, exc)
        return False


def alert_hw_session_once(deps: CliDeps, status: str, detail: str) -> None:
    """Send at most one Telegram alert every 12h if Chrome HW needs reconnect/CAPTCHA."""
    flag = deps.data_dir() / "hellowork" / "hw-session-alert.json"
    now = datetime.now().astimezone()
    try:
        if flag.exists():
            prev = json.loads(flag.read_text(encoding="utf-8"))
            prev_at = datetime.fromisoformat(prev.get("at", ""))
            if (now - prev_at).total_seconds() < 12 * 3600 and prev.get("status") == status:
                return
    except (OSError, ValueError, TypeError) as exc:
        LOG.debug("Lecture flag alerte session ignorée : %s", exc)
    try:
        payload = json.dumps(
            {
                "at": now.isoformat(timespec="seconds"),
                "status": status,
                "detail": detail[:240],
            }
        )
        write_private_text(flag, payload)
    except (OSError, ValueError) as exc:
        LOG.debug("Écriture flag alerte session ignorée : %s", exc)
    try:
        notifier = importlib.import_module("notifier")
        notifier.send_telegram(
            f"⚠️ <b>Session HelloWork bloquée ({status})</b>\n"
            f"{detail[:280]}\n"
            "Action requise : reconnecte `data/hw-session` via VNC/Chrome."
        )
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        LOG.debug("Notification Telegram session ignorée : %s", exc)


def has_blocking_errors(result: dict[str, Any]) -> bool:
    return any(str(error).startswith(BLOCKING_ERROR_PREFIXES) for error in result.get("errors", []))


def find_offer(deps: CliDeps, offer_id: str) -> Any:
    row = deps.store.get(offer_id)
    if row:
        return row
    row = deps.store.by_url(offer_id)
    if row:
        return row
    if offer_id.startswith("http"):
        return deps.store.get(deps.offers.offer_id(offer_id))
    return None


def urls_from_file(path: Path) -> list[str]:
    if not path.exists():
        print(f"Fichier introuvable : {path}")
        return []
    return [
        line
        for raw in path.read_text(encoding="utf-8").splitlines()
        if (line := raw.strip()) and not line.startswith("#") and line.startswith("http")
    ]


def stats_line(deps: CliDeps) -> str:
    stats = deps.store.stats()
    today_count = stats["aujourd'hui"]
    return (
        f"Offres : {stats['offres']} · dossiers : {stats['dossiers']} · "
        f"candidatures : {stats['candidatures']} · aujourd'hui : {today_count}"
    )


def json_dict(raw: str | None) -> dict[str, Any]:
    return dict(json.loads(raw)) if raw else {}


def json_list(raw: str | None) -> list[str]:
    return list(json.loads(raw)) if raw else []


def short(text: str, limit: int) -> str:
    compact = " ".join((text or "").split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                continue


def resolve_submit_cap(
    *, send: bool, enforce_eligibility: bool, max_submits: int | None
) -> int | None:
    if max_submits is not None:
        return max_submits
    if send and enforce_eligibility:
        return max(1, min(int(os.getenv("HW_MAX_AUTO_SUBMIT", "10") or "10"), 20))
    return None
