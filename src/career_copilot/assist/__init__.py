"""Assisted application helpers, ATS adapters, and Sprint ATS queue."""

from __future__ import annotations

from career_copilot.assist.ats_adapters import (
    ATS_ADAPTERS,
    BASE_QUESTION_SELECTORS,
    POLLUTED_PARTNER_URL_MARKERS,
    SUBMIT_FORBIDDEN_MARKERS,
    detect_ats,
    merge_question_selectors,
    resolve_ats_adapter,
    resolve_target_url,
)
from career_copilot.assist.deps import AssistDeps, offer_from_row_safe, row_get
from career_copilot.assist.email_extract import extract_public_recruiter_email, is_idf_offer
from career_copilot.assist.prefill import (
    CONFIRMED_STATUSES,
    build_prefill_payload,
    detect_blocking_gate,
    fill_first_matching,
    has_visible_email_input,
    is_submit_like_element,
    launch_assisted_prefill,
    open_form_if_needed,
    question_value,
    read_letter_text_safe,
    ui_probe_errors,
    upload_first_matching,
)
from career_copilot.assist.sprint import (
    batch_prepare_idf,
    build_sprint_item,
    build_sprint_queue,
    sprint_sort_key,
)

__all__ = [
    "ATS_ADAPTERS",
    "BASE_QUESTION_SELECTORS",
    "CONFIRMED_STATUSES",
    "POLLUTED_PARTNER_URL_MARKERS",
    "SUBMIT_FORBIDDEN_MARKERS",
    "AssistDeps",
    "batch_prepare_idf",
    "build_prefill_payload",
    "build_sprint_item",
    "build_sprint_queue",
    "detect_ats",
    "detect_blocking_gate",
    "extract_public_recruiter_email",
    "fill_first_matching",
    "has_visible_email_input",
    "is_idf_offer",
    "is_submit_like_element",
    "launch_assisted_prefill",
    "merge_question_selectors",
    "offer_from_row_safe",
    "open_form_if_needed",
    "question_value",
    "read_letter_text_safe",
    "resolve_ats_adapter",
    "resolve_target_url",
    "row_get",
    "sprint_sort_key",
    "ui_probe_errors",
    "upload_first_matching",
]
