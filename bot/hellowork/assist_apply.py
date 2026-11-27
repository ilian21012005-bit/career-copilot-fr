"""Backward-compatible re-export shim for ``career_copilot.assist``.

All recruiter e-mail extraction, ATS adapters, assisted Playwright prefill,
batch IDF preparation, and Sprint ATS queue logic now live in
``src/career_copilot/assist/``.
"""

# ruff: noqa: E402
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import offer_letters

from . import kit, profile, store
from . import offer as offers
from . import score as scoring

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.assist import (
    ATS_ADAPTERS,
    AssistDeps,
    detect_ats,
    extract_public_recruiter_email,
    is_idf_offer,
)
from career_copilot.assist import (
    BASE_QUESTION_SELECTORS as _BASE_QUESTION_SELECTORS,
)
from career_copilot.assist import (
    CONFIRMED_STATUSES as _CONFIRMED_STATUSES,
)
from career_copilot.assist import (
    POLLUTED_PARTNER_URL_MARKERS as _POLLUTED_PARTNER_URL_MARKERS,
)
from career_copilot.assist import (
    SUBMIT_FORBIDDEN_MARKERS as _SUBMIT_FORBIDDEN_MARKERS,
)
from career_copilot.assist import (
    batch_prepare_idf as _batch_prepare_idf_impl,
)
from career_copilot.assist import (
    build_prefill_payload as _build_prefill_payload_impl,
)
from career_copilot.assist import (
    build_sprint_item as _build_sprint_item_impl,
)
from career_copilot.assist import (
    build_sprint_queue as _build_sprint_queue_impl,
)
from career_copilot.assist import (
    detect_blocking_gate as _detect_blocking_gate,
)
from career_copilot.assist import (
    fill_first_matching as _fill_first_matching,
)
from career_copilot.assist import (
    has_visible_email_input as _has_visible_email_input,
)
from career_copilot.assist import (
    is_submit_like_element as _is_submit_like_element,
)
from career_copilot.assist import (
    launch_assisted_prefill as _launch_assisted_prefill_impl,
)
from career_copilot.assist import (
    merge_question_selectors as _merge_question_selectors,
)
from career_copilot.assist import (
    offer_from_row_safe as _offer_from_row_safe_impl,
)
from career_copilot.assist import (
    open_form_if_needed as _open_form_if_needed,
)
from career_copilot.assist import (
    question_value as _question_value,
)
from career_copilot.assist import (
    read_letter_text_safe as _read_letter_text_safe_impl,
)
from career_copilot.assist import (
    resolve_ats_adapter as _resolve_ats_adapter,
)
from career_copilot.assist import (
    resolve_target_url as _resolve_target_url,
)
from career_copilot.assist import (
    row_get as _row_get,
)
from career_copilot.assist import (
    sprint_sort_key as _sprint_sort_key,
)
from career_copilot.assist import (
    ui_probe_errors as _ui_probe_errors,
)
from career_copilot.assist import (
    upload_first_matching as _upload_first_matching,
)

log = logging.getLogger("hellowork.assist_apply")


def _deps() -> AssistDeps:
    return AssistDeps(
        store=store,
        offers=offers,
        scoring=scoring,
        kit=kit,
        profile=profile,
        offer_letters=offer_letters,
    )


def _offer_from_row_safe(row: Any) -> offers.Offer:
    return _offer_from_row_safe_impl(row, offers.Offer)


def _read_letter_text_safe(offer_url: str, letter_path: str) -> str:
    return _read_letter_text_safe_impl(offer_url, letter_path, offer_letters)


def batch_prepare_idf(min_score: int = 68, limit: int = 10) -> dict[str, Any]:
    return _batch_prepare_idf_impl(_deps(), min_score=min_score, limit=limit)


def build_prefill_payload(row: Any, kit_data: Any = None) -> dict[str, Any]:
    return _build_prefill_payload_impl(row, kit_data, _deps())


def launch_assisted_prefill(offer_id: str, *, headless: bool = False) -> dict[str, Any]:
    return _launch_assisted_prefill_impl(offer_id, _deps(), headless=headless)


def _build_sprint_item(row: dict[str, Any], kit_data: Any) -> dict[str, Any]:
    return _build_sprint_item_impl(row, kit_data, _deps())


def build_sprint_queue(
    limit: int = 15,
    min_score: int = 65,
    auto_prepare: bool = False,
) -> dict[str, Any]:
    return _build_sprint_queue_impl(
        _deps(), limit=limit, min_score=min_score, auto_prepare=auto_prepare
    )


__all__ = [
    "ATS_ADAPTERS",
    "_BASE_QUESTION_SELECTORS",
    "_CONFIRMED_STATUSES",
    "_POLLUTED_PARTNER_URL_MARKERS",
    "_SUBMIT_FORBIDDEN_MARKERS",
    "_build_sprint_item",
    "_detect_blocking_gate",
    "_fill_first_matching",
    "_has_visible_email_input",
    "_is_submit_like_element",
    "_merge_question_selectors",
    "_offer_from_row_safe",
    "_open_form_if_needed",
    "_question_value",
    "_read_letter_text_safe",
    "_resolve_ats_adapter",
    "_resolve_target_url",
    "_row_get",
    "_sprint_sort_key",
    "_ui_probe_errors",
    "_upload_first_matching",
    "batch_prepare_idf",
    "build_prefill_payload",
    "build_sprint_queue",
    "detect_ats",
    "extract_public_recruiter_email",
    "is_idf_offer",
    "launch_assisted_prefill",
    "log",
    "profile",
]
