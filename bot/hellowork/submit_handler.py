"""Backward-compatible re-export shim for ``career_copilot.submission``.

All Playwright session locking, DOM interaction, receipt verification, and
multi-step funnel logic now live in ``src/career_copilot/submission/`` with
zero broad ``except Exception:`` blocks.
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from config import DATA_DIR
from runtime_hooks import recovery_paused

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.submission import (
    ALLOWED_HOSTS,
    CONFIRMATION_TEXTS,
    FINAL_LABELS,
    HELLOWORK_HOSTS,
    NEXT_LABELS,
    FormFillingError,
    FormSelectors,
    FunnelHooks,
    SubmitBlocked,
    SubmitResult,
    UnsafeTargetError,
    human_like_delay,
)
from career_copilot.submission import (
    dom as _dom,
)
from career_copilot.submission import (
    form_fill as _form_fill,
)
from career_copilot.submission import (
    funnel as _funnel,
)
from career_copilot.submission import (
    hellowork_submit as _hw_submit,
)
from career_copilot.submission import (
    receipts as _receipts,
)
from career_copilot.submission import (
    session as _session,
)
from career_copilot.submission.models import (
    assert_local as _assert_local,
)
from career_copilot.submission.models import (
    assert_target as _assert_target,
)
from career_copilot.submission.models import (
    fold as _fold,
)
from career_copilot.submission.models import (
    hellowork_numeric_id as _hellowork_numeric_id,
)
from career_copilot.submission.models import (
    offer_unavailable as _offer_unavailable,
)
from career_copilot.submission.models import (
    slug as _slug,
)

CAPTURE_ROOT = DATA_DIR / "sandbox" / "captures"

_step_signature = _dom.step_signature
_has_antibot = _dom.has_antibot
_dissuasion_state = _dom.dissuasion_state
_wait_funnel = _form_fill.wait_funnel
_fill_fields = _form_fill.fill_fields
_answer = _form_fill.answer
_check_consents = _form_fill.check_consents
_buttons = _dom.buttons
_find_button = _dom.find_button
_required_missing = _dom.required_missing
_first_visible = _dom.first_visible
_confirmation = _dom.confirmation
_wait_confirmation = _dom.wait_confirmation
_error_text = _dom.error_text
_capture = _dom.capture
_dismiss_cookie_banner = _receipts.dismiss_cookie_banner
_open_hellowork_funnel = _receipts.open_hellowork_funnel
_reload_hellowork_funnel = _receipts.reload_hellowork_funnel
_candidatures_empty = _receipts.candidatures_empty
check_hellowork_application = _receipts.check_hellowork_application
list_hellowork_receipts = _receipts.list_hellowork_receipts


def _current_hooks() -> FunnelHooks:
    return FunnelHooks(
        wait_funnel=_wait_funnel,
        fill_fields=_fill_fields,
        human_like_delay=human_like_delay,
        confirmation=_confirmation,
        find_button=_find_button,
        required_missing=_required_missing,
        capture_root=lambda: CAPTURE_ROOT,
        data_dir=lambda: DATA_DIR,
        recovery_paused=recovery_paused,
        check_application=check_hellowork_application,
    )


@contextmanager
def session_lock(
    timeout_s: float = 5.0,
    *,
    user_data_dir: str | Path | None = None,
) -> Iterator[Path]:
    with _session.session_lock(
        timeout_s=timeout_s, user_data_dir=user_data_dir, default_data_dir=DATA_DIR
    ) as lock_path:
        yield lock_path


def launch_persistent(
    user_data_dir: str | Path | None = None,
    *,
    headless: bool = False,
    channel: str | None = "chrome",
    slow_mo: int = 0,
    sandbox: bool = True,
    args: list[str] | None = None,
) -> tuple[Any, Any]:
    target_dir = user_data_dir if user_data_dir is not None else (DATA_DIR / "hw-session")
    return _session.launch_persistent(
        target_dir,
        headless=headless,
        channel=channel,
        slow_mo=slow_mo,
        sandbox=sandbox,
        args=args,
    )


@contextmanager
def session(
    user_data_dir: str | Path = "./user_data",
    *,
    headless: bool = False,
    channel: str | None = "chrome",
    slow_mo: int = 0,
    sandbox: bool = True,
    lock_timeout_s: float = 5.0,
) -> Iterator[tuple[Any, Any]]:
    with _session.session(
        user_data_dir,
        headless=headless,
        channel=channel,
        slow_mo=slow_mo,
        sandbox=sandbox,
        lock_timeout_s=lock_timeout_s,
        lock_fn=session_lock,
        launch_fn=launch_persistent,
    ) as pair:
        yield pair


def execute_auto_submit(page: Any, offer_id: str, **kwargs: Any) -> SubmitResult:
    kwargs.setdefault("hooks", _current_hooks())
    return _funnel.execute_auto_submit(page, offer_id, **kwargs)


def _submit_hellowork_offer(page: Any, offer_url: str, **kwargs: Any) -> SubmitResult:
    kwargs.setdefault("hooks", _current_hooks())
    return _hw_submit.submit_hellowork_offer_inner(page, offer_url, **kwargs)


def submit_hellowork_offer(
    page: Any,
    offer_url: str,
    *,
    offer_id: str,
    offer_title: str = "",
    company: str = "",
    cv_path: str | Path,
    letter_text: str,
    answers: dict[str, str] | None = None,
    dry_run: bool = True,
    accept_consent: bool = False,
    pacing: tuple[float, float] = (2.0, 5.0),
    timeout_ms: int = 20_000,
    before_final_action: Callable[[], None] | None = None,
) -> SubmitResult:
    return _hw_submit.submit_hellowork_offer(
        page,
        offer_url,
        offer_id=offer_id,
        offer_title=offer_title,
        company=company,
        cv_path=cv_path,
        letter_text=letter_text,
        answers=answers,
        dry_run=dry_run,
        accept_consent=accept_consent,
        pacing=pacing,
        timeout_ms=timeout_ms,
        before_final_action=before_final_action,
        hooks=_current_hooks(),
        inner_fn=_submit_hellowork_offer,
    )


__all__ = [
    "ALLOWED_HOSTS",
    "CAPTURE_ROOT",
    "CONFIRMATION_TEXTS",
    "FINAL_LABELS",
    "HELLOWORK_HOSTS",
    "NEXT_LABELS",
    "FormFillingError",
    "FormSelectors",
    "SubmitBlocked",
    "SubmitResult",
    "UnsafeTargetError",
    "_answer",
    "_assert_local",
    "_assert_target",
    "_buttons",
    "_candidatures_empty",
    "_capture",
    "_check_consents",
    "_confirmation",
    "_dismiss_cookie_banner",
    "_dissuasion_state",
    "_error_text",
    "_fill_fields",
    "_find_button",
    "_first_visible",
    "_fold",
    "_has_antibot",
    "_hellowork_numeric_id",
    "_offer_unavailable",
    "_open_hellowork_funnel",
    "_reload_hellowork_funnel",
    "_required_missing",
    "_slug",
    "_step_signature",
    "_submit_hellowork_offer",
    "_wait_confirmation",
    "_wait_funnel",
    "check_hellowork_application",
    "execute_auto_submit",
    "human_like_delay",
    "launch_persistent",
    "list_hellowork_receipts",
    "session",
    "session_lock",
    "submit_hellowork_offer",
]
