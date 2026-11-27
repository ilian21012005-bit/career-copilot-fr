"""Logging, atomic last-run state persistence, scheduling checks, and retries."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from career_copilot.daily.deps import BLOCKING_ERROR_PREFIXES, RECOVERABLE_ERRORS, DailyDeps


def configure_logger(deps: DailyDeps, name: str = "hellowork.daily") -> logging.Logger:
    log_dir = deps.log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d")
    log_path = (log_dir / f"daily-{stamp}.log").resolve()

    if name == "hellowork" or name.startswith("hellowork."):
        parent = logging.getLogger("hellowork")
        existing_files = [h for h in parent.handlers if isinstance(h, logging.FileHandler)]
        has_target = any(Path(h.baseFilename).resolve() == log_path for h in existing_files)
        if not has_target:
            for old in existing_files:
                parent.removeHandler(old)
                old.close()
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s")
            )
            parent.addHandler(handler)
        if not any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            for h in parent.handlers
        ):
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
            parent.addHandler(console)
        parent.setLevel(logging.INFO)
        log = logging.getLogger(name)
        log.propagate = True
        if log is not parent:
            log.setLevel(logging.INFO)
        return log

    log = logging.getLogger(name)
    if log.handlers:
        return log
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s"))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    log.addHandler(handler)
    log.addHandler(console)
    log.setLevel(logging.INFO)
    return log


def retry[T](
    fn: Callable[[], T],
    log: logging.Logger,
    label: str,
    delay: float = 3.0,
    sleep: Callable[[float], Any] = time.sleep,
    attempts: int = 3,
) -> T:
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except RECOVERABLE_ERRORS as exc:
            if attempt == attempts:
                raise
            log.warning("%s : échec (%s), nouvelle tentative dans %.0fs", label, exc, delay)
            if delay:
                sleep(delay * attempt)
    raise RuntimeError(f"{label} : tentatives épuisées")  # pragma: no cover


def last_state(deps: DailyDeps) -> dict[str, Any]:
    path = deps.state_path()
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def write_state(deps: DailyDeps, summary: dict[str, Any], *, auto_submit: bool = False) -> None:
    state_path = deps.state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data = last_state(deps)
    errors = summary.get("errors", [])
    blocking = any(str(error).startswith(BLOCKING_ERROR_PREFIXES) for error in errors)
    auto_hard_blocking = bool(summary.get("auto_fatal_error")) or any(
        str(error).startswith(("plan:", "alertes:", "mails:")) for error in errors
    )
    auto_ok = not blocking or (
        int(summary.get("auto_submitted") or 0) > 0 and not auto_hard_blocking
    )
    data.setdefault("last_auto_success_at", data.get("last_success_at", ""))
    data.update(
        {
            "last_run_at": summary.get("finished_at"),
            "last_summary": summary,
            "last_success_at": (
                summary.get("finished_at") if not blocking else data.get("last_success_at", "")
            ),
        }
    )
    if auto_submit and auto_ok:
        data["last_auto_success_at"] = summary.get("finished_at")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=state_path.parent,
            prefix="last-run-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, state_path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def ran_today(
    deps: DailyDeps,
    *,
    auto_submit: bool = False,
    min_interval_seconds: int = 3 * 3600,
) -> bool:
    """Return True only if a successful run happened within `min_interval_seconds` today."""
    state = last_state(deps)
    stamp = (
        state.get("last_auto_success_at", state.get("last_success_at", ""))
        if auto_submit
        else state.get("last_success_at", "")
    ) or ""
    if not stamp:
        return False
    now = datetime.now().astimezone()
    if len(stamp) <= 10:
        return stamp[:10] == now.date().isoformat()
    try:
        then = datetime.fromisoformat(stamp)
        if then.tzinfo is None:
            then = then.replace(tzinfo=now.tzinfo)
        return (
            then.date() == now.date() and abs((now - then).total_seconds()) < min_interval_seconds
        )
    except ValueError:
        return stamp[:10] == now.date().isoformat()
