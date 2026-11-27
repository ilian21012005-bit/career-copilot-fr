"""Browser submission engine package (session locks, DOM filling, receipts, funnels)."""

from __future__ import annotations

from . import dom, form_fill, funnel, hellowork_submit, receipts, session
from .funnel import FunnelHooks, execute_auto_submit
from .hellowork_submit import submit_hellowork_offer, submit_hellowork_offer_inner
from .models import (
    ALLOWED_HOSTS,
    BROWSER_ERRORS,
    CONFIRMATION_TEXTS,
    FINAL_LABELS,
    HELLOWORK_HOSTS,
    NEXT_LABELS,
    FormFillingError,
    FormSelectors,
    SubmitBlocked,
    SubmitResult,
    UnsafeTargetError,
    assert_local,
    assert_target,
    fold,
    hellowork_numeric_id,
    human_like_delay,
    offer_unavailable,
    slug,
)
from .receipts import check_hellowork_application, list_hellowork_receipts
from .session import launch_persistent, session_lock

__all__ = [
    "ALLOWED_HOSTS",
    "BROWSER_ERRORS",
    "CONFIRMATION_TEXTS",
    "FINAL_LABELS",
    "HELLOWORK_HOSTS",
    "NEXT_LABELS",
    "FormFillingError",
    "FormSelectors",
    "FunnelHooks",
    "SubmitBlocked",
    "SubmitResult",
    "UnsafeTargetError",
    "assert_local",
    "assert_target",
    "check_hellowork_application",
    "dom",
    "execute_auto_submit",
    "fold",
    "form_fill",
    "funnel",
    "hellowork_numeric_id",
    "hellowork_submit",
    "human_like_delay",
    "launch_persistent",
    "list_hellowork_receipts",
    "offer_unavailable",
    "receipts",
    "session",
    "session_lock",
    "slug",
    "submit_hellowork_offer",
    "submit_hellowork_offer_inner",
]
