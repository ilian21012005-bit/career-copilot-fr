"""Personalized interview preparation brief generator and private cache."""

from __future__ import annotations

from career_copilot.interview.context import (
    FRENCH_MONTHS,
    PRESET_PITCH_ANGLES,
    build_context_from_config,
    build_formation,
    build_pitch_2min,
    build_projets_phares,
    coerce_iso_date,
    format_stage_dates,
    project_label,
)
from career_copilot.interview.questions_domain import (
    questions_business_marketing,
    questions_student_job,
    select_technical_questions,
)
from career_copilot.interview.questions_tech import (
    questions_engineering_industry,
    questions_it_infra_cyber,
    questions_software_data,
)
from career_copilot.interview.rh_questions import build_recruiter_questions, build_rh_questions
from career_copilot.interview.storage import (
    InterviewDeps,
    generate_deterministic_prep,
    get_candidate_context,
    get_or_create_prep,
    load_prep,
    prep_key,
    save_prep,
)

__all__ = [
    "FRENCH_MONTHS",
    "PRESET_PITCH_ANGLES",
    "InterviewDeps",
    "build_context_from_config",
    "build_formation",
    "build_pitch_2min",
    "build_projets_phares",
    "build_recruiter_questions",
    "build_rh_questions",
    "coerce_iso_date",
    "format_stage_dates",
    "generate_deterministic_prep",
    "get_candidate_context",
    "get_or_create_prep",
    "load_prep",
    "prep_key",
    "project_label",
    "questions_business_marketing",
    "questions_engineering_industry",
    "questions_it_infra_cyber",
    "questions_software_data",
    "questions_student_job",
    "save_prep",
    "select_technical_questions",
]
