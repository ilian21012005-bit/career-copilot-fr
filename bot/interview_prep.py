"""Backward-compatible re-export shim for ``career_copilot.interview``.

All candidate context formatting, preset interview question banks, pitch
generation, and private JSON caching now live in
``src/career_copilot/interview/``.
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import candidate_config
from config import DATA_DIR
from private_storage import ensure_private_directory, write_private_text

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.interview import (
    FRENCH_MONTHS as _FRENCH_MONTHS,
)
from career_copilot.interview import (
    PRESET_PITCH_ANGLES as _PRESET_PITCH_ANGLES,
)
from career_copilot.interview import (
    InterviewDeps,
)
from career_copilot.interview import (
    build_context_from_config as _build_context_from_config,
)
from career_copilot.interview import (
    build_formation as _build_formation,
)
from career_copilot.interview import (
    build_pitch_2min as _build_pitch_2min,
)
from career_copilot.interview import (
    build_projets_phares as _build_projets_phares,
)
from career_copilot.interview import (
    build_recruiter_questions as _build_recruiter_questions,
)
from career_copilot.interview import (
    build_rh_questions as _build_rh_questions,
)
from career_copilot.interview import (
    coerce_iso_date as _coerce_iso_date,
)
from career_copilot.interview import (
    format_stage_dates as _format_stage_dates,
)
from career_copilot.interview import (
    generate_deterministic_prep as _generate_deterministic_prep_impl,
)
from career_copilot.interview import (
    get_candidate_context as _get_candidate_context_impl,
)
from career_copilot.interview import (
    get_or_create_prep as _get_or_create_prep_impl,
)
from career_copilot.interview import (
    load_prep as _load_prep_impl,
)
from career_copilot.interview import (
    prep_key as _key,
)
from career_copilot.interview import (
    project_label as _project_label,
)
from career_copilot.interview import (
    questions_business_marketing as _questions_business_marketing,
)
from career_copilot.interview import (
    questions_engineering_industry as _questions_engineering_industry,
)
from career_copilot.interview import (
    questions_it_infra_cyber as _questions_it_infra_cyber,
)
from career_copilot.interview import (
    questions_software_data as _questions_software_data,
)
from career_copilot.interview import (
    questions_student_job as _questions_student_job,
)
from career_copilot.interview import (
    save_prep as _save_prep_impl,
)
from career_copilot.interview import (
    select_technical_questions as _select_technical_questions,
)

FOLDER = DATA_DIR / "interview_prep"


def _deps() -> InterviewDeps:
    return InterviewDeps(
        get_profile=candidate_config.get_profile,
        folder=lambda: FOLDER,
        ensure_private_directory=ensure_private_directory,
        write_private_text=write_private_text,
        load_prep_fn=load_prep,
        save_prep_fn=save_prep,
        generate_prep_fn=generate_deterministic_prep,
    )


def load_prep(url: str) -> dict[str, Any] | None:
    return _load_prep_impl(url, FOLDER)


def save_prep(url: str, data: dict[str, Any]) -> Path:
    return _save_prep_impl(
        url,
        data,
        FOLDER,
        ensure_private_directory=ensure_private_directory,
        write_private_text=write_private_text,
    )


def get_candidate_context() -> dict[str, Any]:
    return _get_candidate_context_impl(candidate_config.get_profile)


def generate_deterministic_prep(target: dict[str, Any]) -> dict[str, Any]:
    return _generate_deterministic_prep_impl(target, candidate_config.get_profile)


def get_or_create_prep(target: dict[str, Any], force_regenerate: bool = False) -> dict[str, Any]:
    return _get_or_create_prep_impl(target, _deps(), force_regenerate=force_regenerate)


__all__ = [
    "FOLDER",
    "_FRENCH_MONTHS",
    "_PRESET_PITCH_ANGLES",
    "_build_context_from_config",
    "_build_formation",
    "_build_pitch_2min",
    "_build_projets_phares",
    "_build_recruiter_questions",
    "_build_rh_questions",
    "_coerce_iso_date",
    "_format_stage_dates",
    "_key",
    "_project_label",
    "_questions_business_marketing",
    "_questions_engineering_industry",
    "_questions_it_infra_cyber",
    "_questions_software_data",
    "_questions_student_job",
    "_select_technical_questions",
    "generate_deterministic_prep",
    "get_candidate_context",
    "get_or_create_prep",
    "load_prep",
    "save_prep",
]
