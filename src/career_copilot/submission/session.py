"""Playwright persistent browser session lifecycle and flock concurrency guard."""

from __future__ import annotations

import errno
import importlib
import os
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from career_copilot.submission.models import BROWSER_ERRORS, LOG


def _file_lock_mod() -> Any:
    return importlib.import_module("file_lock")


@contextmanager
def session_lock(
    timeout_s: float = 5.0,
    *,
    user_data_dir: str | Path | None = None,
    default_data_dir: Path | None = None,
) -> Generator[Path]:
    """Serialize persistent Chrome profile access across processes via flock."""
    fcntl = _file_lock_mod()
    base_dir = (
        Path(user_data_dir)
        if user_data_dir is not None
        else ((default_data_dir or Path("data")) / "hw-session")
    )
    profile_dir = base_dir.expanduser().absolute()
    if profile_dir.is_symlink():
        raise ValueError("Profil Chrome symbolique interdit")
    profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        profile_dir.chmod(0o700)
    lock_path = profile_dir / ".apply.lock"
    if lock_path.is_symlink():
        raise ValueError("Verrou de session Chrome symbolique interdit")

    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    if os.name != "nt":
        os.chmod(lock_path, 0o600)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if not isinstance(exc, BlockingIOError) and exc.errno not in (
                    errno.EAGAIN,
                    errno.EACCES,
                    errno.EWOULDBLOCK,
                ):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        f"Profil Chrome déjà verrouillé ({lock_path}) après {timeout_s:.1f}s"
                    ) from exc
                time.sleep(min(0.05, max(0.005, remaining)))
        yield lock_path
    finally:
        try:
            if acquired:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def launch_persistent(
    user_data_dir: str | Path,
    *,
    headless: bool = False,
    channel: str | None = "chrome",
    slow_mo: int = 0,
    sandbox: bool = True,
    args: list[str] | None = None,
) -> tuple[Any, Any]:
    """Launch a sandboxed persistent Chromium context preserving local session state."""
    sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright

    profile_dir = Path(user_data_dir).expanduser().absolute()
    if profile_dir.is_symlink():
        raise ValueError("Profil Chrome symbolique interdit")
    profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        profile_dir.chmod(0o700)
    playwright = sync_playwright().start()
    try:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            channel=channel,
            slow_mo=slow_mo,
            chromium_sandbox=sandbox,
            args=list(args) if args else [],
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
            timezone_id="Europe/Paris",
        )
    except BaseException:
        playwright.stop()
        raise
    return playwright, context


@contextmanager
def session(
    user_data_dir: str | Path = "./user_data",
    *,
    headless: bool = False,
    channel: str | None = "chrome",
    slow_mo: int = 0,
    sandbox: bool = True,
    lock_timeout_s: float = 5.0,
    lock_fn: Callable[..., Any] | None = None,
    launch_fn: Callable[..., tuple[Any, Any]] | None = None,
) -> Generator[tuple[Any, Any]]:
    """Context manager guaranteeing flock release and Playwright teardown."""
    active_lock = lock_fn or session_lock
    active_launch = launch_fn or launch_persistent
    with active_lock(timeout_s=lock_timeout_s, user_data_dir=user_data_dir):
        playwright, context = active_launch(
            user_data_dir,
            headless=headless,
            channel=channel,
            slow_mo=slow_mo,
            sandbox=sandbox,
        )
        try:
            yield playwright, context
        finally:
            try:
                context.close()
            finally:
                try:
                    playwright.stop()
                except BROWSER_ERRORS as exc:
                    LOG.debug("Arrêt Playwright ignoré lors du nettoyage : %s", exc)
