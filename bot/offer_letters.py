"""Backward-compatible re-export shim for ``career_copilot.letters``.

All cover-letter generation, offer-fit scoring, validation, and PDF rendering
now live in ``src/career_copilot/letters/`` using explicit typed dependency injection.
"""

# ruff: noqa: E402
from __future__ import annotations

import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import candidate_config
import letter_ai
import page_fetch
import pdfs
from config import DATA_DIR, SENDER_NAME
from private_storage import (
    ensure_private_directory,
    protect_private_file,
    write_private_text,
)

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.letters import (
    ALTERNANCE_MARKERS as _ALTERNANCE_MARKERS,
    FACT_STOPWORDS as _FACT_STOPWORDS,
    MONTHS,
    NOISE,
    PROFILE_UNREAD as _PROFILE_UNREAD,
    UNTRUSTED_JOB_OFFER_SYSTEM_RULE,
    LetterDeps,
    LetterRenderContext,
    bad_mission as _bad_mission,
    bad_sentence as _bad_sentence,
    campaign_of_target as _campaign_of_target,
    candidate_name as _candidate_name_impl,
    compact_untrusted_text,
    compose as _compose_impl,
    compute_fit_gaps as _compute_fit_gaps,
    compute_offer_fit as _compute_offer_fit_impl,
    dateline as _dateline_impl,
    dating_city as _dating_city_impl,
    education_intro as _education_intro,
    ensure_pdf as _ensure_pdf_impl,
    first_sentence as _first_sentence,
    fold as _fold,
    format_date_fr as _format_date_fr,
    format_untrusted_job_offer,
    french as _french,
    has_word as _has,
    header_line as _header_line_impl,
    heading as _heading,
    html_document as _html,
    is_alternance_text as _is_alternance_text,
    is_candidate_bac3_or_less as _is_candidate_bac3_or_less,
    is_stage as _is_stage,
    job_availability_paragraph as _job_availability_paragraph,
    job_availability_text as _job_availability_text,
    job_body as _job_body_impl,
    job_tasks as _job_tasks,
    join_fr as _join,
    lines as _lines,
    load as _load_impl,
    load_many as _load_many_impl,
    lower_first as _lower_first,
    marketing as _marketing,
    mission_sentence as _mission_sentence,
    missions as _missions,
    mobility_closing as _mobility_closing,
    notes as _notes,
    objective as _objective,
    pdf_name as _pdf_name_impl,
    pdf_path as _pdf_path_impl,
    profile_digest as _profile_digest,
    relevance_score as _relevance_score,
    render_experiences_and_projects as _render_experiences_and_projects,
    restate as _restate,
    sanitize_untrusted_text,
    save as _save_impl,
    section as _section,
    select_relevant_facts as _select_relevant_facts,
    short_title as _short_title,
    skill_owned as _skill_owned,
    stage_body as _stage_body_impl,
    stage_profile as _stage_profile_impl,
    subject_for as _subject_for,
    url_key as _key,
    usable_goal as _usable_goal,
    validation_is_current as _validation_is_current_impl,
    validation_metadata as _validation_metadata_impl,
)

FOLDER = DATA_DIR / "lettres"
LOG = logging.getLogger("offer_letters")
_CANDIDATE_NAME: str = ""

_build_ai_prompt = letter_ai._build_ai_prompt
_has_verified_candidate_facts = letter_ai._has_verified_candidate_facts


def _render_context() -> LetterRenderContext:
    return LetterRenderContext(
        _candidate_name=_candidate_name,
        _dateline=_dateline,
        _header_line=_header_line,
        _subject_for=_subject_for,
        _format_date_fr=_format_date_fr,
        _job_availability_text=_job_availability_text,
    )


def _profile_fingerprint() -> str | None:
    from hellowork.store import profile_fingerprint

    return profile_fingerprint()


def _ai_profile() -> str:
    from hellowork.profile import ai_profile

    return ai_profile()


def _deps() -> LetterDeps:
    return LetterDeps(
        folder=lambda: FOLDER,
        get_profile=candidate_config.get_profile,
        ensure_private_directory=ensure_private_directory,
        protect_private_file=protect_private_file,
        write_private_text=write_private_text,
        read_offer_page=page_fetch.read_offer,
        html_to_pdf=pdfs.html_to_pdf,
        profile_fingerprint=_profile_fingerprint,
        ai_profile=_ai_profile,
        name_override=lambda: _CANDIDATE_NAME,
        sender_name=lambda: str(SENDER_NAME or ""),
        compose_ai_fn=_compose_ai,
        ensure_pdf_fn=ensure_pdf,
        load_fn=load,
        validation_is_current_fn=validation_is_current,
        validation_metadata_fn=validation_metadata,
    )


def _candidate_name(cfg: candidate_config.CandidateProfileConfig | None = None) -> str:
    profile = cfg if cfg is not None else candidate_config.get_profile()
    return _candidate_name_impl(
        profile, name_override=_CANDIDATE_NAME, sender_name=str(SENDER_NAME or "")
    )


def _header_line(cfg: candidate_config.CandidateProfileConfig | None = None) -> str:
    profile = cfg if cfg is not None else candidate_config.get_profile()
    return _header_line_impl(
        profile, name_override=_CANDIDATE_NAME, sender_name=str(SENDER_NAME or "")
    )


def _dating_city(cfg: candidate_config.CandidateProfileConfig | None = None) -> str:
    profile = cfg if cfg is not None else candidate_config.get_profile()
    return _dating_city_impl(profile)


def _dateline(
    cfg: candidate_config.CandidateProfileConfig | None = None,
    *,
    today: date | None = None,
) -> str:
    profile = cfg if cfg is not None else candidate_config.get_profile()
    return _dateline_impl(profile, today=today)


def compute_offer_fit(
    title: str,
    source_text: str,
    *,
    stage: bool = True,
    campaign: str | None = None,
) -> dict[str, object]:
    return _compute_offer_fit_impl(
        candidate_config.get_profile(), title, source_text, stage=stage, campaign=campaign
    )


def validation_metadata(
    letter: str, stage: bool, kind: str, *, profile_source: Any = _PROFILE_UNREAD
) -> dict[str, Any]:
    return _validation_metadata_impl(
        _deps(), letter, stage, kind, profile_source=profile_source
    )


def validation_is_current(
    data: dict[str, Any], *, profile_source: Any = _PROFILE_UNREAD
) -> bool:
    return _validation_is_current_impl(_deps(), data, profile_source=profile_source)


def save(
    target: dict[str, Any],
    page_text: str | None = None,
    missions: list[str] | None = None,
) -> Path:
    return _save_impl(_deps(), target, page_text=page_text, mission_items=missions)


def load(url: str) -> dict[str, Any] | None:
    return _load_impl(_deps(), url)


def load_many(urls: list[str]) -> dict[str, dict[str, Any]]:
    return _load_many_impl(_deps(), urls)


def ensure_pdf(url: str) -> Path | None:
    return _ensure_pdf_impl(_deps(), url)


def pdf_path(url: str) -> Path:
    return _pdf_path_impl(_deps(), url)


def pdf_name(url: str) -> str:
    return _pdf_name_impl(_deps(), url)


def _compose(
    title: str,
    company: str,
    city: str,
    stage: bool,
    source: str,
    missions: list[str] | None = None,
    *,
    campaign: str | None = None,
) -> tuple[str, str, str]:
    return _compose_impl(
        _deps(), title, company, city, stage, source, missions, campaign=campaign
    )


def _ai_stage_evidence(
    cfg: candidate_config.CandidateProfileConfig, extra_ai_profile: str
) -> str:
    return letter_ai._ai_stage_evidence(cfg, extra_ai_profile, _render_context())


def _ai_job_evidence(cfg: candidate_config.CandidateProfileConfig) -> str:
    return letter_ai._ai_job_evidence(cfg, _render_context())


def _compose_ai(
    title: str,
    company: str,
    city: str,
    stage: bool,
    source: str,
    missions: list[str] | None = None,
    *,
    campaign: str | None = None,
) -> tuple[str, str, str] | None:
    return letter_ai.compose_ai(
        title,
        company,
        city,
        stage,
        source,
        missions,
        campaign=campaign,
        context=_render_context(),
    )


def _stage_body(
    company: str,
    place: str,
    short: str,
    lines_list: list[str],
    source: str,
    missions: list[str] | None = None,
    *,
    campaign: str = "stage",
) -> str:
    cfg = candidate_config.get_profile()
    return _stage_body_impl(
        cfg,
        _candidate_name(cfg),
        company,
        place,
        short,
        lines_list,
        source,
        missions,
        campaign=campaign,
    )


def _job_body(company: str, place: str, short: str, source: str) -> str:
    cfg = candidate_config.get_profile()
    return _job_body_impl(cfg, _candidate_name(cfg), company, place, short, source)


def _stage_profile(
    source: str,
    *,
    cfg: candidate_config.CandidateProfileConfig | None = None,
) -> str:
    profile = cfg if cfg is not None else candidate_config.get_profile()
    return _stage_profile_impl(profile, source)


__all__ = [
    "FOLDER",
    "LOG",
    "MONTHS",
    "NOISE",
    "UNTRUSTED_JOB_OFFER_SYSTEM_RULE",
    "_ALTERNANCE_MARKERS",
    "_CANDIDATE_NAME",
    "_FACT_STOPWORDS",
    "_ai_job_evidence",
    "_ai_stage_evidence",
    "_bad_mission",
    "_bad_sentence",
    "_build_ai_prompt",
    "_campaign_of_target",
    "_candidate_name",
    "_compose",
    "_compose_ai",
    "_compute_fit_gaps",
    "_dateline",
    "_dating_city",
    "_education_intro",
    "_first_sentence",
    "_fold",
    "_format_date_fr",
    "_french",
    "_has",
    "_has_verified_candidate_facts",
    "_header_line",
    "_heading",
    "_html",
    "_is_alternance_text",
    "_is_candidate_bac3_or_less",
    "_is_stage",
    "_job_availability_paragraph",
    "_job_availability_text",
    "_job_body",
    "_job_tasks",
    "_join",
    "_key",
    "_lines",
    "_lower_first",
    "_marketing",
    "_mission_sentence",
    "_missions",
    "_mobility_closing",
    "_notes",
    "_objective",
    "_profile_digest",
    "_relevance_score",
    "_render_experiences_and_projects",
    "_restate",
    "_section",
    "_select_relevant_facts",
    "_short_title",
    "_skill_owned",
    "_stage_body",
    "_stage_profile",
    "_subject_for",
    "_usable_goal",
    "compact_untrusted_text",
    "compute_offer_fit",
    "ensure_pdf",
    "format_untrusted_job_offer",
    "load",
    "load_many",
    "pdf_name",
    "pdf_path",
    "re",
    "sanitize_untrusted_text",
    "save",
    "validation_is_current",
    "validation_metadata",
]
